"""Offline self-test, executed INSIDE the freshly built image (container started with --network none).
Proves the image starts and serves the UI + API with zero network access."""
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.request

BASE = os.environ.get("SELFTEST_URL", "http://127.0.0.1:8090")
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def get(path, data=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(data).encode() if data else None,
                                 headers={"Content-Type": "application/json"} if data else {})
    with opener.open(req, timeout=30) as r:
        return r.status, r.read().decode("utf-8", "replace")


def check(name, cond):
    print(("  ok    " if cond else "  FAIL  ") + name)
    if not cond:
        sys.exit(1)


for _ in range(60):
    try:
        status, body = get("/api/health")
        break
    except Exception:
        time.sleep(1)
else:
    print("  FAIL  server did not start"); sys.exit(1)

health = json.loads(body)
check(f"health endpoint (version {health.get('version')})", status == 200 and health["ok"])
check("LLM reported unreachable (expected: no network)", health["llm"] is False)

status, html = get("/")
check("web UI index.html served", status == 200 and '<div id="root">' in html)
check("no external scripts/styles in index.html", not re.search(r'(src|href)="https?://', html))
assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', html)
check(f"{len(assets)} bundled assets referenced", len(assets) >= 2)
for a in assets:
    s, _ = get(a)
    check(f"asset {a}", s == 200)
s, _ = get("/c/123")
check("client-side routes fall back to index.html", s == 200)

s, body = get("/api/auth/login", {"username": "admin", "password": "selftest-pass"})
check("built-in admin login", s == 200 and json.loads(body)["is_admin"])
s, body = get("/api/conversations", {"title": "selftest"})
check("database write (create conversation)", s == 200 and json.loads(body)["id"] > 0)
s, body = get("/api/admin/llm")
check("admin LLM status endpoint", s == 200 and json.loads(body)["thinking"] in ("default", "on", "off"))
print("SELFTEST PASSED")
