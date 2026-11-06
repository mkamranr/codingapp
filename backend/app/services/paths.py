import posixpath
import re
from typing import Optional

_DRIVE = re.compile(r"^[A-Za-z]:")


def safe_relpath(name: str) -> Optional[str]:
    """Normalize a user/LLM-supplied path to a safe relative POSIX path, or None if unsafe."""
    if not name:
        return None
    p = name.strip().strip('"').strip("'").replace("\\", "/")
    if p.startswith("/") or _DRIVE.match(p) or "\x00" in p:
        return None
    parts = []
    for part in p.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            return None
        parts.append(part)
    if not parts:
        return None
    return posixpath.join(*parts)
