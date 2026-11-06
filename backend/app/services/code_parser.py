"""Parse fenced code blocks carrying a file path out of LLM responses."""
import re
from dataclasses import dataclass
from typing import Optional

from .paths import safe_relpath

OPEN_RE = re.compile(r"^( {0,3})(`{3,}|~{3,})(.*)$")
CLOSE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*$")
ATTR_RE = re.compile(r"""(\w+)\s*=\s*(?:"([^"]*)"|'([^']*)'|(\S+))""")
PATH_KEYS = ("path", "file", "filename", "filepath", "name")


@dataclass
class Block:
    start: int  # line index of opening fence
    end: int  # line index of closing fence (or last line if unterminated)
    lang: str
    path: Optional[str]
    action: str
    content: str
    closed: bool


@dataclass
class ParsedFile:
    path: str
    content: str
    lang: str
    action: str  # write | delete


def strip_think(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    if "</think>" in text:  # opening tag was part of the prompt template
        text = text.split("</think>", 1)[1]
    return text.lstrip("\n")


def parse_info(info: str) -> tuple:
    info = info.strip()
    attrs = {}
    for m in ATTR_RE.finditer(info):
        attrs[m.group(1).lower()] = next(g for g in m.groups()[1:] if g is not None)
    first = info.split()[0] if info.split() else ""
    lang = "" if "=" in first else first
    path = next((attrs[k] for k in PATH_KEYS if k in attrs), None)
    if not path and lang and ":" in lang:  # ```python:src/app.py
        lang, path = lang.split(":", 1)
    action = attrs.get("action", "write").lower()
    return lang.lower(), path, "delete" if action == "delete" else "write"


def iter_blocks(text: str) -> list:
    lines = text.split("\n")
    blocks = []
    i, n = 0, len(lines)
    while i < n:
        m = OPEN_RE.match(lines[i])
        if not m:
            i += 1
            continue
        fence, info = m.group(2), m.group(3)
        if fence[0] == "`" and "`" in info:
            i += 1
            continue
        lang, path, action = parse_info(info)
        j = i + 1
        closed = False
        while j < n:
            c = CLOSE_RE.match(lines[j])
            if c and c.group(1)[0] == fence[0] and len(c.group(1)) >= len(fence):
                closed = True
                break
            j += 1
        body = "\n".join(lines[i + 1 : j])
        blocks.append(Block(i, min(j, n - 1), lang, path, action, body, closed))
        i = j + 1
    return blocks


def parse_files(text: str) -> list:
    """Return files (last occurrence wins) from blocks that declare a path."""
    out = {}
    for b in iter_blocks(strip_think(text)):
        if not b.path or not b.closed:
            continue
        path = safe_relpath(b.path)
        if not path:
            continue
        content = b.content
        if content and not content.endswith("\n"):
            content += "\n"
        out[path] = ParsedFile(path, "" if b.action == "delete" else content, b.lang, b.action)
    return list(out.values())


def compress_for_history(text: str) -> str:
    """Replace file blocks with a short placeholder: the latest version lives in the workspace."""
    text = strip_think(text)
    lines = text.split("\n")
    blocks = [b for b in iter_blocks(text) if b.path]
    if not blocks:
        return text
    out, cursor = [], 0
    for b in blocks:
        out.extend(lines[cursor : b.start])
        verb = "deleted" if b.action == "delete" else "written in full"
        out.append(f"[File `{b.path}` {verb} here; its current version is in the project files.]")
        cursor = b.end + 1
    out.extend(lines[cursor:])
    return "\n".join(out)
