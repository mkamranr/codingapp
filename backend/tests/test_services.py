import io
import zipfile

import pytest

from app.services.code_parser import compress_for_history, parse_files, strip_think
from app.services.context_builder import CtxFile, HistMsg, build_messages
from app.services.extractor import ExtractError, Limits, process_uploads
from app.services.paths import safe_relpath
from app.services.zip_builder import build_zip

LIM = Limits(10 * 1024 * 1024, 100, 512 * 1024)


def make_zip(entries: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


# ---------- paths ----------
@pytest.mark.parametrize("bad", ["../x", "/etc/passwd", "C:/win.ini", "a/../../b", "", "a\x00b"])
def test_unsafe_paths(bad):
    assert safe_relpath(bad) is None


def test_safe_path_normalizes():
    assert safe_relpath("./src\\app//main.py") == "src/app/main.py"


# ---------- extractor ----------
def test_zip_root_strip_and_skips():
    z = make_zip({
        "proj/src/main.py": "print('hi')\r\n",
        "proj/node_modules/x/index.js": "x",
        "proj/logo.png": b"\x89PNG\x00\x00",
        "proj/data.bin2": b"\x00\x01\x02",
        "../evil.py": "boom",
    })
    r = process_uploads([("proj.zip", z)], LIM)
    assert r.root_name == "proj"
    assert r.files == [("src/main.py", "print('hi')\n")]
    reasons = dict(r.skipped)
    assert reasons["node_modules/x/index.js"] == "ignored folder"
    assert reasons["logo.png"] == "binary file"
    assert reasons["data.bin2"] == "binary content"
    assert reasons["../evil.py"] == "unsafe path"


def test_zip_bomb_rejected():
    z = make_zip({"big.txt": "a" * (5 * 1024 * 1024)})
    with pytest.raises(ExtractError):
        process_uploads([("b.zip", z)], Limits(10 * 1024 * 1024, 100, 8 * 1024 * 1024))


def test_too_large_total():
    z = make_zip({f"f{i}.txt": "x" * 400_000 for i in range(30)})
    with pytest.raises(ExtractError):
        process_uploads([("b.zip", z)], Limits(5 * 1024 * 1024, 100, 512 * 1024))


def test_invalid_zip():
    with pytest.raises(ExtractError):
        process_uploads([("x.zip", b"not a zip")], LIM)


def test_plain_files_and_latin1():
    r = process_uploads([("a.py", b"x = 1\n"), ("b.txt", "café".encode("latin-1"))], LIM)
    assert dict(r.files) == {"a.py": "x = 1\n", "b.txt": "café"}


# ---------- code parser ----------
RESP = """Fixed the bug.

```python path=src/main.py
def f():
    return 1
```

Some shell:
```bash
pip install x
```

````markdown path="README.md"
# Title
```js
code()
```
````

```text path=old.py action=delete
```
"""


def test_parse_files():
    files = {f.path: f for f in parse_files(RESP)}
    assert set(files) == {"src/main.py", "README.md", "old.py"}
    assert files["src/main.py"].content == "def f():\n    return 1\n"
    assert "```js" in files["README.md"].content
    assert files["old.py"].action == "delete"


def test_parse_colon_style_and_unterminated():
    files = parse_files("```ts:web/app.ts\nlet a=1\n```\n```python path=x.py\nunfinished")
    assert [f.path for f in files] == ["web/app.ts"]


def test_think_stripped():
    assert strip_think("<think>```python path=a.py\nx\n```</think>ok") == "ok"
    assert parse_files("reasoning```python path=a.py\n```</think>\nno files") == []


def test_compress_history():
    out = compress_for_history(RESP)
    assert "def f()" not in out
    assert "[File `src/main.py` written in full here" in out
    assert "pip install x" in out


# ---------- context builder ----------
def test_context_budget_and_ranking():
    files = [CtxFile(f"f{i}.py", "x" * 3200, 1000) for i in range(10)]
    files.append(CtxFile("app/target.py", "import helper\n", 1000))
    files.append(CtxFile("app/helper.py", "y", 1000))
    r = build_messages(files, [], "please fix target.py", pinned={"f9.py"},
                       context_tokens=8192, max_output_tokens=2048)
    inc = r.info["included"]
    assert "f9.py" in inc and "app/target.py" in inc and "app/helper.py" in inc
    assert r.info["omitted"]
    assert r.input_tokens + r.max_tokens <= 8192
    assert "content was omitted" in r.messages[0]["content"]


def test_context_all_fit_and_history():
    files = [CtxFile("a.py", "print(1)", 5)]
    hist = [HistMsg("user", "q1"), HistMsg("assistant", "```python path=a.py\nprint(1)\n```")]
    r = build_messages(files, hist, "q2", pinned=set(), context_tokens=262144,
                       max_output_tokens=32768)
    assert r.info["omitted"] == [] and r.info["history_included"] == 2
    assert r.max_tokens == 32768
    assert r.messages[-1] == {"role": "user", "content": "q2"}
    assert "current version is in the project files" in r.messages[2]["content"]


# ---------- zip builder ----------
def test_build_zip_structure():
    data = build_zip({"src/a.py": "a", "b.txt": "b"}, "proj", ["old.py"])
    names = set(zipfile.ZipFile(io.BytesIO(data)).namelist())
    assert names == {"proj/src/a.py", "proj/b.txt", "proj/DELETED_FILES.txt"}
