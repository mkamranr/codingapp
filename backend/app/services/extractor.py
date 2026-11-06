"""Safe extraction of uploaded source files and zip archives."""
import io
import stat
import zipfile
from dataclasses import dataclass, field
from typing import Optional

from .paths import safe_relpath

SKIP_DIRS = {
    ".git", ".svn", ".hg", "node_modules", "__pycache__", ".venv", "venv", "env",
    ".idea", ".vscode", ".vs", "dist", "build", "out", "target", "bin", "obj",
    ".next", ".nuxt", ".gradle", ".mypy_cache", ".pytest_cache", ".tox", "coverage",
    ".cache", "__MACOSX", ".terraform", "Pods", "DerivedData",
}
SKIP_FILES = {".DS_Store", "Thumbs.db"}
LOCKFILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Cargo.lock",
             "composer.lock", "Gemfile.lock", "go.sum"}
BINARY_EXT = {
    "png", "jpg", "jpeg", "gif", "bmp", "ico", "webp", "tif", "tiff", "psd", "svgz",
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt",
    "zip", "gz", "tgz", "bz2", "xz", "7z", "rar", "tar", "jar", "war", "ear", "whl", "nupkg",
    "exe", "dll", "so", "dylib", "a", "lib", "o", "obj", "class", "pyc", "pyo", "pdb", "bin",
    "mp3", "mp4", "wav", "avi", "mov", "mkv", "flac", "ogg", "webm",
    "ttf", "otf", "woff", "woff2", "eot",
    "db", "sqlite", "sqlite3", "mdb", "parquet", "pkl", "pt", "pth", "onnx", "h5", "safetensors",
}
MAX_RATIO = 200  # per-entry compression ratio guard (zip bomb)
LOCKFILE_MAX = 1024 * 1024


class ExtractError(ValueError):
    pass


@dataclass
class Limits:
    max_total_bytes: int
    max_files: int
    max_file_bytes: int


@dataclass
class ExtractResult:
    files: list = field(default_factory=list)  # list[tuple[path, content]]
    skipped: list = field(default_factory=list)  # list[tuple[path, reason]]
    root_name: Optional[str] = None


def decode_text(data: bytes) -> Optional[str]:
    if b"\x00" in data[:8192]:
        return None
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    # Too many control chars -> binary
    sample = data[:8192]
    ctrl = sum(1 for b in sample if b < 9 or 13 < b < 32)
    if sample and ctrl / len(sample) > 0.05:
        return None
    return data.decode("latin-1")


def _skip_reason(path: str, size: int, limits: Limits) -> Optional[str]:
    parts = path.split("/")
    if any(p in SKIP_DIRS for p in parts[:-1]):
        return "ignored folder"
    name = parts[-1]
    if name in SKIP_FILES:
        return "ignored file"
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext in BINARY_EXT:
        return "binary file"
    if name in LOCKFILES and size > LOCKFILE_MAX:
        return "large lockfile"
    if size > limits.max_file_bytes:
        return f"file larger than {limits.max_file_bytes // 1024} KB"
    return None


def _add(result: ExtractResult, path: str, data: bytes, limits: Limits) -> None:
    reason = _skip_reason(path, len(data), limits)
    if reason:
        result.skipped.append((path, reason))
        return
    text = decode_text(data)
    if text is None:
        result.skipped.append((path, "binary content"))
        return
    result.files.append((path, text.replace("\r\n", "\n")))


def extract_zip(data: bytes, limits: Limits, result: ExtractResult, prefix: str = "") -> None:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ExtractError("Invalid or corrupted zip file")
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if len(infos) > limits.max_files * 4:
        raise ExtractError(f"Zip contains too many entries ({len(infos)})")
    declared = sum(i.file_size for i in infos)
    if declared > limits.max_total_bytes * 4:
        raise ExtractError("Zip uncompressed size exceeds the limit")

    total = 0
    for info in infos:
        mode = info.external_attr >> 16
        raw_name = info.filename
        path = safe_relpath(raw_name)
        if path is None:
            result.skipped.append((raw_name, "unsafe path"))
            continue
        if prefix:
            path = f"{prefix}/{path}"
        if stat.S_ISLNK(mode):
            result.skipped.append((path, "symlink"))
            continue
        reason = _skip_reason(path, info.file_size, limits)
        if reason:
            result.skipped.append((path, reason))
            continue
        if info.compress_size and info.file_size / max(info.compress_size, 1) > MAX_RATIO \
                and info.file_size > 1024 * 1024:
            raise ExtractError(f"Suspicious compression ratio in {path}")
        # Read with a hard cap: never trust declared sizes.
        cap = limits.max_file_bytes + 1
        with zf.open(info) as fh:
            content = fh.read(cap)
        if len(content) > limits.max_file_bytes:
            result.skipped.append((path, f"file larger than {limits.max_file_bytes // 1024} KB"))
            continue
        total += len(content)
        if total > limits.max_total_bytes:
            raise ExtractError(
                f"Extracted content exceeds {limits.max_total_bytes // (1024 * 1024)} MB"
            )
        _add(result, path, content, limits)
        if len(result.files) > limits.max_files:
            raise ExtractError(f"Too many files (limit {limits.max_files})")


def strip_common_root(result: ExtractResult) -> None:
    """If every file lives under one top-level folder, strip it and remember it as root_name."""
    paths = [p for p, _ in result.files]
    if not paths:
        return
    firsts = {p.split("/", 1)[0] for p in paths}
    if len(firsts) == 1 and all("/" in p for p in paths):
        root = firsts.pop()
        result.root_name = root
        result.files = [(p.split("/", 1)[1], c) for p, c in result.files]
        result.skipped = [
            (p.split("/", 1)[1] if p.startswith(root + "/") else p, r) for p, r in result.skipped
        ]


def process_uploads(items: list, limits: Limits) -> ExtractResult:
    """items: list of (filename, bytes). Zips are expanded, other files added as-is."""
    result = ExtractResult()
    only_one_zip = len(items) == 1 and items[0][0].lower().endswith(".zip")
    for filename, data in items:
        if filename.lower().endswith(".zip"):
            sub = ExtractResult()
            extract_zip(data, limits, sub)
            strip_common_root(sub)
            if only_one_zip:
                result.root_name = sub.root_name or filename[:-4]
            result.files.extend(sub.files)
            result.skipped.extend(sub.skipped)
        else:
            path = safe_relpath(filename)
            if path is None:
                result.skipped.append((filename, "unsafe path"))
                continue
            _add(result, path, data, limits)
    # de-duplicate (last wins)
    dedup = {}
    for p, c in result.files:
        dedup[p] = c
    result.files = list(dedup.items())
    if len(result.files) > limits.max_files:
        raise ExtractError(f"Too many files (limit {limits.max_files})")
    return result
