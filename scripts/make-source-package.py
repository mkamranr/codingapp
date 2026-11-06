"""Create packages/codingapp-<version>-source.zip: everything the internet build server needs.
Usage:  python scripts/make-source-package.py"""
import stat
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text().strip()
EXCLUDE_DIRS = {".venv", "node_modules", "dist", "data", "release", "packages", "__pycache__",
                ".pytest_cache", ".git", ".idea", ".vscode"}
EXCLUDE_FILES = {".env"}
TEXT_EXT = {".sh", ".yml", ".yaml", ".py", ".md", ".txt", ".json", ".ts", ".tsx", ".css", ".html",
            ".svg", ".example", ".ps1", ""}

prefix = f"codingapp-{VERSION}-source"
out = ROOT / "packages" / f"{prefix}.zip"
out.parent.mkdir(exist_ok=True)

count = 0
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
    for p in sorted(ROOT.rglob("*")):
        rel = p.relative_to(ROOT)
        if any(part in EXCLUDE_DIRS for part in rel.parts) or not p.is_file() or p.name in EXCLUDE_FILES:
            continue
        data = p.read_bytes()
        if p.suffix in TEXT_EXT and p.suffix != ".ps1" and b"\x00" not in data:
            data = data.replace(b"\r\n", b"\n")  # LF for everything Linux will execute or read
        info = zipfile.ZipInfo(f"{prefix}/{rel.as_posix()}", date_time=(2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        mode = 0o755 if p.suffix == ".sh" else 0o644
        info.external_attr = (stat.S_IFREG | mode) << 16
        zf.writestr(info, data)
        count += 1

print(f"{out}  ({count} files, {out.stat().st_size // 1024} KB)")
sys.exit(0)
