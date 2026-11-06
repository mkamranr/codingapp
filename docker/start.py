"""CodingApp runtime entrypoint (baked into the runtime image).

The image contains only Python and the libraries. The application itself is mounted at /code:
    /code/app/              Python package (FastAPI backend)
    /code/static/           built web UI
    /code/VERSION           application version
    /code/requirements.txt  libraries this code needs (must match the image)

    python start.py                 check the code, then run it
    python start.py --check [DIR]   only check DIR (default /code); exit 1 on a problem
"""
import os
import sys

CODE = os.environ.get("CODE_DIR", "/code")
RUNTIME_REQS = os.environ.get("RUNTIME_REQUIREMENTS", "/opt/runtime/requirements.txt")


def _reqs(path):
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return None
    out = set()
    for line in lines:
        line = line.split("#", 1)[0].strip().lower().replace(" ", "")
        if line and not line.startswith("-"):
            out.add(line)
    return out


def check(code: str) -> str:
    if not os.path.isfile(os.path.join(code, "app", "main.py")):
        return (f"No application code in {code} (expected {code}/app/main.py). "
                "Check that the 'code' folder exists in the install folder and is mounted.")
    need, have = _reqs(os.path.join(code, "requirements.txt")), _reqs(RUNTIME_REQS)
    if need is not None and have is not None and need != have:
        missing = sorted(need - have)
        extra = sorted(have - need)
        msg = ["This code needs different Python libraries than this runtime image has."]
        if missing:
            msg.append("  needed but not in the image: " + ", ".join(missing))
        if extra:
            msg.append("  in the image but not wanted: " + ", ".join(extra))
        msg.append("Install the FULL package (it contains a new runtime image) instead of a code-only update.")
        return "\n".join(msg)
    return ""


def version(code: str) -> str:
    try:
        with open(os.path.join(code, "VERSION"), encoding="utf-8") as f:
            return f.read().strip() or "dev"
    except FileNotFoundError:
        return "dev"


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        code = sys.argv[2] if len(sys.argv) > 2 else CODE
        err = check(code)
        print(err or f"OK: code version {version(code)} is compatible with this runtime image")
        sys.exit(1 if err else 0)

    err = check(CODE)
    if err:
        print("ERROR: " + err, file=sys.stderr, flush=True)
        sys.exit(2)
    os.environ["APP_VERSION"] = version(CODE)  # the code decides the version, not .env
    os.environ.setdefault("STATIC_DIR", os.path.join(CODE, "static"))
    os.environ.setdefault("FORWARDED_ALLOW_IPS", "*")  # read by uvicorn (trust the reverse proxy)
    os.chdir(CODE)
    print(f"CodingApp {os.environ['APP_VERSION']} starting from {CODE}", flush=True)
    os.execvp(sys.executable, [
        sys.executable, "-m", "uvicorn", "app.main:app", "--app-dir", CODE,
        "--host", "0.0.0.0", "--port", "8090", "--proxy-headers", "--timeout-keep-alive", "75",
    ])


if __name__ == "__main__":
    main()
