import io
import json
import zipfile
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import llm_client
from app.services import ldap_auth


class FakeLLM:
    def __init__(self, chunks_per_call):
        self.calls = []
        self.chunks_per_call = chunks_per_call

    async def info(self, force=False):
        return {"ok": True, "model": "fake", "context_tokens": 8192, "context_source": "config",
                "base_url": "x", "max_output_tokens": 2048, "models": ["fake"], "error": ""}

    async def stream(self, messages, max_tokens, model, continue_final=False, thinking=None):
        self.calls.append({"messages": messages, "continue": continue_final, "thinking": thinking})
        chunks, finish = self.chunks_per_call[len(self.calls) - 1]
        for c in chunks:
            yield ("content", c)
        yield ("finish", finish)


@pytest.fixture()
def client(monkeypatch):
    return TestClient(app)


def login(c, user="admin", pw="test-pass"):
    return c.post("/api/auth/login", json={"username": user, "password": pw})


def sse_events(text):
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(l.split(": ", 1) for l in block.split("\n"))
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def test_auth_required(client):
    assert client.get("/api/conversations").status_code == 401
    assert login(client, pw="wrong").status_code == 401
    r = login(client)
    assert r.status_code == 200 and r.json()["is_admin"]
    assert client.get("/api/auth/me").json()["username"] == "admin"


def test_full_flow(client, monkeypatch):
    fake = FakeLLM([
        (["I fixed it.\n\n```python path=src/calc.py\ndef add(a, b):\n", "    return a + b\n"], "length"),
        (["```\nDone.\n"], "stop"),
    ])
    for mod in ("app.routers.chat", "app.routers.conversations"):
        monkeypatch.setattr(f"{mod}.llm", fake)
    login(client)
    cid = client.post("/api/conversations", json={}).json()["id"]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("calc/src/calc.py", "def add(a, b):\n    return a - b\n")
        zf.writestr("calc/README.md", "# calc\n")
    r = client.post(f"/api/conversations/{cid}/files",
                    files=[("files", ("calc.zip", buf.getvalue(), "application/zip"))])
    assert r.status_code == 200, r.text
    assert r.json()["root_name"] == "calc" and r.json()["added"] == 2

    r = client.post(f"/api/conversations/{cid}/messages", json={"content": "fix add in calc.py"})
    events = sse_events(r.text)
    kinds = [e for e, _ in events]
    assert "continuing" in kinds and kinds[-1] == "done"
    files_ev = next(d for e, d in events if e == "files")
    assert [f["path"] for f in files_ev["files"]] == ["src/calc.py"]
    assert fake.calls[1]["continue"] is True
    assert "return a - b" in fake.calls[0]["messages"][0]["content"]

    conv = client.get(f"/api/conversations/{cid}").json()
    assert conv["messages"][1]["finish_reason"] == "stop"
    calc = next(f for f in conv["files"] if f["path"] == "src/calc.py")
    assert calc["modified"]

    # single file download
    d = client.get(f"/api/files/{files_ev['files'][0]['id']}/download")
    assert d.text == "def add(a, b):\n    return a + b\n"
    assert 'filename="calc.py"' in d.headers["content-disposition"]

    # full + changed zips
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/conversations/{cid}/export.zip").content))
    assert set(z.namelist()) == {"calc/src/calc.py", "calc/README.md"}
    assert "a + b" in z.read("calc/src/calc.py").decode()
    z = zipfile.ZipFile(io.BytesIO(
        client.get(f"/api/conversations/{cid}/export.zip?mode=changed").content))
    assert z.namelist() == ["calc/src/calc.py"]


def test_other_user_cannot_access(client, monkeypatch):
    login(client)
    cid = client.post("/api/conversations", json={}).json()["id"]
    cfg = {**ldap_auth.DEFAULTS, "enabled": True, "bind_password": "x"}
    monkeypatch.setattr("app.routers.auth.ldap_auth.load_config", lambda db, with_secret=False: cfg)
    monkeypatch.setattr("app.routers.auth.ldap_auth.authenticate",
                        lambda cfg, u, p: {"display_name": "Bob", "email": "", "is_admin": False}
                        if p == "bobpw" else None)
    c2 = TestClient(app)
    assert login(c2, "bob", "bobpw").status_code == 200
    assert c2.get(f"/api/conversations/{cid}").status_code == 404
    assert c2.get("/api/admin/ldap").status_code == 403


def test_ldap_config_password_not_returned(client):
    login(client)
    r = client.put("/api/admin/ldap", json={"enabled": False, "server_url": "ldap://dc:389",
                                            "bind_dn": "cn=svc", "bind_password": "secret",
                                            "search_base": "dc=x"})
    assert r.status_code == 200
    body = r.json()
    assert body["bind_password"] == "" and body["bind_password_set"] is True
    # saving again with blank password keeps it
    client.put("/api/admin/ldap", json={"server_url": "ldap://dc:389", "bind_password": ""})
    assert client.get("/api/admin/ldap").json()["bind_password_set"] is True


def test_ldap_filter_escaping(monkeypatch):
    captured = {}

    class FakeConn:
        response = []

        def search(self, base, flt, scope, **kw):
            captured["flt"] = flt

    ldap_auth._find_user(FakeConn(), ldap_auth.DEFAULTS, "a*)(uid=*")
    assert "a\\2a\\29\\28uid=\\2a" in captured["flt"]


def test_ldap_empty_password_rejected():
    cfg = {**ldap_auth.DEFAULTS, "enabled": True}
    assert ldap_auth.authenticate(cfg, "bob", "") is None


def test_thinking_setting(client, monkeypatch):
    fake = FakeLLM([(["ok"], "stop"), (["ok"], "stop"), (["ok"], "stop")])
    monkeypatch.setattr("app.routers.chat.llm", fake)
    monkeypatch.setattr("app.routers.admin.llm", fake)
    login(client)
    cid = client.post("/api/conversations", json={}).json()["id"]
    assert client.get("/api/admin/llm").json()["thinking"] == "default"
    expected = []
    for mode, flag in (("default", None), ("off", False), ("on", True)):
        assert client.put("/api/admin/llm/settings", json={"thinking": mode}).json()["thinking"] == mode
        client.post(f"/api/conversations/{cid}/messages", json={"content": "hi"})
        expected.append(flag)
    assert [c["thinking"] for c in fake.calls] == expected
    assert client.put("/api/admin/llm/settings", json={"thinking": "maybe"}).status_code == 400
    client.put("/api/admin/llm/settings", json={"thinking": "default"})



class RecConn:
    """Fake ldap3 Connection modelling Active Directory: one user bob / right-pw, anonymous binds
    succeed but anonymous searches fail with 000004DC."""
    binds = []
    VALID = {"CN=bob,DC=x,DC=local", "bob@x.local", r"X\bob", "CN=svc,DC=x,DC=local"}

    def __init__(self, server, user=None, password=None, authentication=None, **kw):
        self.user, self.password, self.auth = user, password, authentication
        self.response = []

    def open(self): pass
    def start_tls(self): pass
    def unbind(self): pass

    def bind(self):
        RecConn.binds.append((self.auth, self.user))
        if self.auth == ldap_auth.SIMPLE and not (self.user in self.VALID and self.password in ("right-pw", "svc-pw")):
            from ldap3.core.exceptions import LDAPInvalidCredentialsResult
            raise LDAPInvalidCredentialsResult("invalid credentials")

    def search(self, base, flt, scope, **kw):
        if self.auth == ldap_auth.ANONYMOUS:
            from ldap3.core.exceptions import LDAPOperationsErrorResult
            raise LDAPOperationsErrorResult("000004DC: a successful bind must be completed")
        self.response = [{"type": "searchResEntry", "dn": "CN=bob,DC=x,DC=local",
                          "attributes": {"displayName": "Bob", "memberOf": ["CN=Admins,DC=x,DC=local"]}}]             if "bob" in flt else []


AD = {**ldap_auth.DEFAULTS, "enabled": True, "search_base": "DC=x,DC=local", "bind_dn": "", "bind_password": ""}


def test_ldap_principal_names():
    assert ldap_auth.user_principal(AD, "bob") == "bob@x.local"  # derived from the search base
    assert ldap_auth.user_principal({**AD, "user_bind_format": r"X\{username}"}, "bob") == r"X\bob"
    assert ldap_auth.user_principal(AD, "bob@other.com") == "bob@other.com"
    assert ldap_auth.user_principal({**AD, "search_base": "ou=people"}, "bob") == ""  # -> anonymous
    assert ldap_auth.short_name(r"X\Bob") == "Bob" and ldap_auth.short_name("bob@x.local") == "bob"


def test_ldap_direct_user_bind(monkeypatch):
    """No service account on AD: sign in as the user, then search as the user."""
    monkeypatch.setattr(ldap_auth, "Connection", RecConn)
    RecConn.binds = []
    cfg = {**AD, "admin_group_dn": "CN=Admins,DC=x,DC=local"}
    r = ldap_auth.authenticate(cfg, "bob", "right-pw")
    assert r == {"username": "bob", "display_name": "Bob", "email": "", "is_admin": True}
    assert RecConn.binds == [(ldap_auth.SIMPLE, "bob@x.local")]
    assert ldap_auth.authenticate(cfg, r"X\bob", "right-pw")["username"] == "bob"
    assert ldap_auth.authenticate(cfg, "bob", "wrong") is None
    assert ldap_auth.authenticate(cfg, "bob", "") is None
    with pytest.raises(PermissionError):
        ldap_auth.authenticate({**cfg, "required_group_dn": "CN=Other,DC=x,DC=local", "nested_groups": False},
                               "bob", "right-pw")
    t = ldap_auth.test_connection(cfg, "bob", "right-pw")
    assert t["ok"] and "Signed in as bob@x.local" in t["steps"] and "Member of admin group: yes" in t["steps"]
    assert not ldap_auth.test_connection(cfg, "bob", "")["ok"]          # asks for the test password
    assert not ldap_auth.test_connection(cfg, "bob", "wrong")["ok"]


def test_ldap_anonymous_search_blocked_gives_hint(monkeypatch):
    monkeypatch.setattr(ldap_auth, "Connection", RecConn)
    cfg = {**AD, "search_base": "ou=people"}  # no domain -> no sign-in name -> anonymous search
    t = ldap_auth.test_connection(cfg, "bob")
    assert not t["ok"] and "anonymous" in t["steps"][0] and "service account" in t["error"]


def test_ldap_service_account_bind(monkeypatch):
    monkeypatch.setattr(ldap_auth, "Connection", RecConn)
    RecConn.binds = []
    cfg = {**AD, "bind_dn": "CN=svc,DC=x,DC=local", "bind_password": "svc-pw"}
    assert ldap_auth.authenticate(cfg, "bob", "right-pw")["display_name"] == "Bob"
    assert RecConn.binds == [(ldap_auth.SIMPLE, "CN=svc,DC=x,DC=local"), (ldap_auth.SIMPLE, "CN=bob,DC=x,DC=local")]
    assert ldap_auth.authenticate(cfg, "bob", "wrong") is None
    t = ldap_auth.test_connection(cfg, "bob", "right-pw")
    assert t["ok"] and "User password accepted" in t["steps"]


def test_ldap_user_bind_never_anonymous():
    from ldap3.core.exceptions import LDAPException
    with pytest.raises(LDAPException):
        ldap_auth._connect(ldap_auth.DEFAULTS, "CN=bob,DC=x", "")


def test_ldap_test_endpoint_can_force_no_service_account(client, monkeypatch):
    client.post("/api/auth/login", json={"username": "admin", "password": "test-pass"})
    client.put("/api/admin/ldap", json={"server_url": "ldap://dc:389", "bind_dn": "CN=svc,DC=x", "bind_password": "pw"})
    seen = {}
    monkeypatch.setattr("app.routers.admin.ldap_auth.test_connection",
                        lambda cfg, u, p: seen.update(pw=cfg["bind_password"], tp=p) or {"ok": True, "steps": [], "error": ""})
    client.post("/api/admin/ldap/test", json={"server_url": "ldap://dc:389", "clear_bind_password": True,
                                              "test_username": "bob", "test_password": "tp"})
    assert seen == {"pw": "", "tp": "tp"}
    client.post("/api/admin/ldap/test", json={"server_url": "ldap://dc:389"})
    assert seen["pw"] == "pw"
    r = client.put("/api/admin/ldap", json={"server_url": "ldap://dc:389", "user_bind_format": r"X\{username}",
                                            "clear_bind_password": True})
    assert r.json()["bind_password_set"] is False and r.json()["user_bind_format"] == r"X\{username}"
