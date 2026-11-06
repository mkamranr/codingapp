"""Builds the chat prompt so that it uses as much of the model's context window as possible."""
import posixpath
import re
from dataclasses import dataclass, field
from typing import Callable

from .code_parser import compress_for_history
from .tokens import estimate

SYSTEM_PROMPT = """You are CodingApp, an expert software engineer and code reviewer. The user's project files are provided below. Answer questions about the code precisely (reference file paths and line numbers where useful), find bugs, explain behaviour, and fix or improve code when asked.

Rules for returning code:
1. Whenever you create or modify a project file, output the COMPLETE, final content of that file. Never output partial files, diffs, or placeholders such as "... rest unchanged ...".
2. Put each file in its own fenced code block whose info string has the language and the file path relative to the project root, exactly like:
```python path=src/app/main.py
<full file content>
```
3. Keep the existing folder structure and file names from the project tree. Use forward slashes. New files go in a sensible location in that tree.
4. If a file's content itself contains ``` then use a longer fence (````) for that block.
5. To delete a file output an empty block: ```text path=old/unused.py action=delete```
6. Code that is not a project file (shell commands, short examples) uses a normal fence WITHOUT path=.
7. Briefly explain the problem and the fix before the code, and finish with a short list of the files you changed.
8. Only output files that actually change."""

FILE_OVERHEAD = 14  # tokens for the <file> wrapper
MSG_OVERHEAD = 8
MIN_RECENT_MESSAGES = 4

_IMPORT_RES = [
    re.compile(r"^\s*from\s+([\w.]+)\s+import", re.M),
    re.compile(r"^\s*import\s+([\w.]+)", re.M),
    re.compile(r"""(?:require\(|from\s+|import\s+)['"]([^'"]+)['"]"""),
    re.compile(r"""#\s*include\s+["<]([^">]+)[">]"""),
    re.compile(r"^\s*using\s+([\w.]+)\s*;", re.M),
    re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)\s*;", re.M),
]


@dataclass
class CtxFile:
    path: str
    content: str
    tokens: int
    generated: bool = False


@dataclass
class HistMsg:
    role: str
    content: str


@dataclass
class BuildResult:
    messages: list
    input_tokens: int
    max_tokens: int
    info: dict = field(default_factory=dict)


class ContextTooSmall(ValueError):
    pass


def render_tree(paths: list) -> str:
    lines, seen = [], set()
    for p in sorted(paths):
        parts = p.split("/")
        for depth in range(1, len(parts)):
            d = "/".join(parts[:depth])
            if d not in seen:
                seen.add(d)
                lines.append("  " * (depth - 1) + parts[depth - 1] + "/")
        lines.append("  " * (len(parts) - 1) + parts[-1])
    return "\n".join(lines)


def _stem(p: str) -> str:
    base = posixpath.basename(p)
    return base.split(".", 1)[0].lower()


def _referenced_stems(contents: list) -> set:
    stems = set()
    for text in contents:
        for rx in _IMPORT_RES:
            for m in rx.finditer(text):
                ref = m.group(1).replace("\\", "/")
                last = re.split(r"[./]", ref.strip("./"))
                if last and last[-1]:
                    stems.add(last[-1].lower())
                    if last[-1] == "index" and len(last) > 1:
                        stems.add(last[-2].lower())
    return stems


def rank_files(files: list, pinned: set, user_text: str) -> list:
    low = user_text.lower()

    def mentioned(f: CtxFile) -> bool:
        base = posixpath.basename(f.path).lower()
        return f.path.lower() in low or (len(base) >= 3 and base in low)

    focus = [f for f in files if f.path in pinned or mentioned(f)]
    refs = _referenced_stems([f.content for f in focus])

    def tier(f: CtxFile) -> int:
        if f.path in pinned:
            return 0
        if mentioned(f):
            return 1
        if f.generated:
            return 2
        if _stem(f.path) in refs:
            return 3
        return 4

    return sorted(files, key=lambda f: (tier(f), f.tokens, f.path))


def build_messages(
    files: list,
    history: list,
    user_text: str,
    *,
    pinned: set,
    context_tokens: int,
    max_output_tokens: int,
    root_name: str = "",
    count: Callable[[str], int] = estimate,
    assistant_prefix: str = "",
) -> BuildResult:
    reserve_out = min(max_output_tokens, context_tokens // 2)
    margin = max(256, int(context_tokens * 0.02))
    prefix_tokens = count(assistant_prefix) if assistant_prefix else 0
    budget = context_tokens - reserve_out - margin - prefix_tokens

    tree = render_tree([f.path for f in files])
    header = f"\n\n# Project: {root_name or 'uploaded files'}\n## File tree\n```\n{tree}\n```\n" \
        if files else "\n\n(No project files have been uploaded yet.)\n"
    fixed = count(SYSTEM_PROMPT) + count(header) + count(user_text) + 3 * MSG_OVERHEAD
    remaining = budget - fixed - 6 * len(files)  # room for "omitted" notes
    if remaining < 0:
        raise ContextTooSmall(
            "Your message (plus the system prompt) is larger than the model's context window."
        )

    # 1) most recent history is mandatory (as long as it fits)
    hist = [HistMsg(m.role, compress_for_history(m.content) if m.role == "assistant" else m.content)
            for m in history if m.content.strip()]
    hist_tok = [count(h.content) + MSG_OVERHEAD for h in hist]
    keep = [False] * len(hist)
    for i in range(len(hist) - 1, max(-1, len(hist) - 1 - MIN_RECENT_MESSAGES), -1):
        if hist_tok[i] <= remaining:
            keep[i] = True
            remaining -= hist_tok[i]

    # 2) as many files as fit, by priority
    included, omitted = [], []
    for f in rank_files(files, pinned, user_text):
        need = f.tokens + FILE_OVERHEAD
        if need <= remaining:
            included.append(f)
            remaining -= need
        else:
            omitted.append(f.path)

    # 3) older history, newest first
    for i in range(len(hist) - 1, -1, -1):
        if not keep[i] and hist_tok[i] <= remaining:
            keep[i] = True
            remaining -= hist_tok[i]

    # Stable ordering (sorted by path) keeps the prompt prefix identical across turns,
    # which lets vLLM's prefix cache skip re-processing the project on follow-up questions.
    parts = [SYSTEM_PROMPT, header]
    if included:
        parts.append("## Files\n")
        for f in sorted(included, key=lambda x: x.path):
            parts.append(f'<file path="{f.path}">\n{f.content}\n</file>\n')
    if omitted:
        parts.append(
            "\nNOTE: These files exist but their content was omitted because the context window "
            "is full. Ask the user to pin them if you need them:\n"
            + "\n".join(f"- {p}" for p in sorted(omitted))
        )
    system = "".join(parts)

    msgs = [{"role": "system", "content": system}]
    msgs += [{"role": h.role, "content": h.content} for h, k in zip(hist, keep) if k]
    msgs.append({"role": "user", "content": user_text})
    if assistant_prefix:
        msgs.append({"role": "assistant", "content": assistant_prefix})

    input_tokens = budget + prefix_tokens - remaining
    max_tokens = max(256, min(max_output_tokens, context_tokens - input_tokens - margin))
    info = {
        "context_tokens": context_tokens,
        "input_tokens": input_tokens,
        "max_tokens": max_tokens,
        "included": sorted(f.path for f in included),
        "omitted": sorted(omitted),
        "history_included": sum(keep),
        "history_total": len(hist),
    }
    return BuildResult(msgs, input_tokens, max_tokens, info)
