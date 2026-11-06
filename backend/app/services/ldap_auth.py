"""Active Directory / LDAP authentication configured by the administrator.

Two ways to find users:
- service account (bind DN + password stored): search with the service account, then verify the
  user's password by binding as the user's DN;
- no service account: bind directly as the user (e.g. bob@corp.local) and search with the user's
  own rights. This works on Active Directory, which forbids anonymous searches by default.
  If no sign-in name can be built, an anonymous search is tried (some OpenLDAP setups allow it).
"""
import json
import logging
import ssl
from typing import Optional

from ldap3 import ANONYMOUS, BASE, NONE, SIMPLE, SUBTREE, Connection, Server, Tls
from ldap3.core.exceptions import (LDAPBindError, LDAPException, LDAPOperationResult,
                                   LDAPPasswordIsMandatoryError)
from ldap3.utils.conv import escape_filter_chars
from sqlalchemy.orm import Session

from ..models import Setting
from .crypto import decrypt, encrypt

log = logging.getLogger("codingapp.ldap")
KEY = "ldap"
AD_NESTED_RULE = "1.2.840.113556.1.4.1941"  # LDAP_MATCHING_RULE_IN_CHAIN

DEFAULTS = {
    "enabled": False,
    "server_url": "ldap://dc01.example.local:389",
    "start_tls": False,
    "verify_cert": True,
    "ca_cert_path": "",
    "timeout": 10,
    "bind_dn": "",  # optional service account
    "bind_password": "",  # stored encrypted; blank = users sign in directly
    "user_bind_format": "",  # {username}@corp.local or CORP\{username}; blank = from search base
    "search_base": "DC=example,DC=local",
    "user_filter": "(&(objectClass=user)(sAMAccountName={username}))",
    "display_name_attr": "displayName",
    "email_attr": "mail",
    "required_group_dn": "",
    "admin_group_dn": "",
    "nested_groups": True,
}


def load_config(db: Session, with_secret: bool = False) -> dict:
    row = db.get(Setting, KEY)
    cfg = dict(DEFAULTS)
    if row:
        try:
            cfg.update(json.loads(row.value))
        except ValueError:
            pass
    stored = cfg.get("bind_password", "")
    cfg["bind_password"] = decrypt(stored) if with_secret else ""
    cfg["bind_password_set"] = bool(stored)
    return cfg


def save_config(db: Session, new: dict) -> dict:
    current = load_config(db, with_secret=True)
    merged = {k: new.get(k, current[k]) for k in DEFAULTS}
    # empty password in the form = keep existing one
    if not new.get("bind_password"):
        merged["bind_password"] = current["bind_password"]
    if new.get("clear_bind_password"):
        merged["bind_password"] = ""
    merged["bind_password"] = encrypt(merged["bind_password"])
    merged["timeout"] = max(1, min(int(merged["timeout"] or 10), 120))
    row = db.get(Setting, KEY) or Setting(key=KEY)
    row.value = json.dumps(merged)
    db.add(row)
    db.commit()
    return load_config(db)


# ---------------------------------------------------------------- connections

def _server(cfg: dict) -> Server:
    url = cfg["server_url"].strip()
    tls = Tls(
        validate=ssl.CERT_REQUIRED if cfg["verify_cert"] else ssl.CERT_NONE,
        ca_certs_file=cfg["ca_cert_path"] or None,
    )
    return Server(url, use_ssl=url.lower().startswith("ldaps://"), tls=tls,
                  connect_timeout=cfg["timeout"], get_info=NONE)


def _open(cfg: dict, conn: Connection) -> Connection:
    conn.open()
    if cfg["start_tls"]:
        conn.start_tls()
    conn.bind()
    return conn


def _connect(cfg: dict, user: str, password: str) -> Connection:
    """Authenticated bind. Never anonymous: an empty password is refused here."""
    if not user or not password:
        raise LDAPPasswordIsMandatoryError("password is mandatory")
    return _open(cfg, Connection(_server(cfg), user=user, password=password, authentication=SIMPLE,
                                 receive_timeout=cfg["timeout"], raise_exceptions=True, auto_bind=False))


def _anonymous(cfg: dict) -> Connection:
    return _open(cfg, Connection(_server(cfg), authentication=ANONYMOUS,
                                 receive_timeout=cfg["timeout"], raise_exceptions=True, auto_bind=False))


def uses_service_account(cfg: dict) -> bool:
    return bool(cfg.get("bind_password"))


def _service_connect(cfg: dict) -> Connection:
    """Search connection: the service account if configured, else anonymous."""
    if uses_service_account(cfg):
        return _connect(cfg, cfg["bind_dn"], cfg["bind_password"])
    return _anonymous(cfg)


# ---------------------------------------------------------------- names

def _domain_from_base(base: str) -> str:
    parts = [p.strip()[3:] for p in (base or "").split(",") if p.strip().lower().startswith("dc=")]
    return ".".join(parts)


def short_name(username: str) -> str:
    """'CORP\\bob' / 'bob@corp.local' / 'bob' -> 'bob'"""
    return username.split("\\")[-1].split("@")[0]


def user_principal(cfg: dict, username: str) -> str:
    """Name to bind with as the user when there is no service account ('' = anonymous search)."""
    if "@" in username or "\\" in username:
        return username
    fmt = (cfg.get("user_bind_format") or "").strip()
    if not fmt:
        dom = _domain_from_base(cfg.get("search_base", ""))
        fmt = f"{{username}}@{dom}" if dom else ""
    return fmt.replace("{username}", username) if fmt else ""


def _search_name(cfg: dict, username: str, principal: str) -> str:
    if "userprincipalname" in cfg["user_filter"].lower():
        return principal if "@" in principal else username
    return short_name(username)


# ---------------------------------------------------------------- lookups

def _first(entry: dict, attr: str) -> str:
    v = entry.get(attr)
    if isinstance(v, list):
        v = v[0] if v else ""
    return str(v) if v else ""


def _find_user(conn: Connection, cfg: dict, username: str) -> Optional[dict]:
    flt = cfg["user_filter"].replace("{username}", escape_filter_chars(username))
    attrs = [a for a in {cfg["display_name_attr"], cfg["email_attr"], "memberOf"} if a]
    conn.search(cfg["search_base"], flt, SUBTREE, attributes=attrs, size_limit=2)
    entries = [e for e in conn.response if e.get("type") == "searchResEntry"]
    if len(entries) != 1:
        return None
    e = entries[0]
    return {"dn": e["dn"], "attrs": e.get("attributes", {})}


def _in_group(conn: Connection, cfg: dict, user: dict, group_dn: str) -> bool:
    if not group_dn:
        return False
    member_of = user["attrs"].get("memberOf") or []
    if isinstance(member_of, str):
        member_of = [member_of]
    if any(g.lower() == group_dn.lower() for g in member_of):
        return True
    if cfg["nested_groups"]:
        flt = f"(memberOf:{AD_NESTED_RULE}:={escape_filter_chars(group_dn)})"
        try:
            conn.search(user["dn"], flt, BASE, attributes=["distinguishedName"])
            return any(e.get("type") == "searchResEntry" for e in conn.response)
        except LDAPException:
            return False
    return False


def _result(conn: Connection, cfg: dict, user: Optional[dict], username: str) -> dict:
    if cfg["required_group_dn"]:
        if not user:
            raise PermissionError("Your directory entry could not be read to check group membership")
        if not _in_group(conn, cfg, user, cfg["required_group_dn"]):
            raise PermissionError("You are not a member of the group allowed to use this app")
    attrs = user["attrs"] if user else {}
    return {
        "username": short_name(username).lower(),
        "display_name": _first(attrs, cfg["display_name_attr"]) or short_name(username),
        "email": _first(attrs, cfg["email_attr"]),
        "is_admin": bool(user) and _in_group(conn, cfg, user, cfg["admin_group_dn"]),
    }


# ---------------------------------------------------------------- login

def authenticate(cfg: dict, username: str, password: str) -> Optional[dict]:
    """Returns {"username", "display_name", "email", "is_admin"} on success, None on bad
    credentials. Raises PermissionError when the user is not in the required group and
    ConnectionError when the directory is unreachable."""
    if not cfg.get("enabled") or not username or not password:  # empty password = anonymous bind!
        return None
    principal = "" if uses_service_account(cfg) else user_principal(cfg, username)

    if principal:  # no service account: bind as the user, then search with the user's own rights
        try:
            conn = _connect(cfg, principal, password)
        except (LDAPOperationResult, LDAPBindError):
            return None  # wrong password / unknown user / account disabled
        except LDAPException as e:
            log.error("LDAP connection failed: %s", e)
            raise ConnectionError("Directory server unavailable") from e
        try:
            try:
                user = _find_user(conn, cfg, _search_name(cfg, username, principal))
            except LDAPException as e:
                log.warning("LDAP search as %s failed: %s", principal, e)
                user = None
            return _result(conn, cfg, user, username)
        finally:
            conn.unbind()

    try:  # service account (or anonymous) search, then verify the password against the user's DN
        svc = _service_connect(cfg)
    except LDAPException as e:
        log.error("LDAP %s bind failed: %s", "service" if uses_service_account(cfg) else "anonymous", e)
        raise ConnectionError("Directory server unavailable") from e
    try:
        user = _find_user(svc, cfg, _search_name(cfg, username, ""))
        if not user:
            return None
        try:
            _connect(cfg, user["dn"], password).unbind()
        except LDAPException:
            return None
        return _result(svc, cfg, user, username)
    finally:
        svc.unbind()


# ---------------------------------------------------------------- admin test

ANON_HINT = ("This directory does not allow anonymous searches. Either enter a service account and "
             "its password, or set the user sign-in format so users sign in directly.")


def _describe(conn: Connection, cfg: dict, user: dict, steps: list) -> None:
    steps.append(f"Found user: {user['dn']}")
    if cfg["required_group_dn"]:
        ok = _in_group(conn, cfg, user, cfg["required_group_dn"])
        steps.append(f"Member of required group: {'yes' if ok else 'NO'}")
    if cfg["admin_group_dn"]:
        ok = _in_group(conn, cfg, user, cfg["admin_group_dn"])
        steps.append(f"Member of admin group: {'yes' if ok else 'no'}")


def test_connection(cfg: dict, test_username: str = "", test_password: str = "") -> dict:
    steps: list = []
    svc_mode = uses_service_account(cfg)
    pattern = "" if svc_mode else user_principal(cfg, "{username}")

    if pattern:  # direct sign-in mode
        try:
            _anonymous(cfg).unbind()
            steps.append(f"Server reachable. No service account: users sign in as {pattern}")
        except LDAPException as e:
            return {"ok": False, "steps": steps, "error": f"Cannot connect: {e}"}
        if not test_username:
            return {"ok": True, "steps": steps, "error": ""}
        if not test_password:
            return {"ok": False, "steps": steps, "error": "Enter the test user's password too: without a "
                    "service account the app signs in as the user to look them up."}
        principal = user_principal(cfg, test_username)
        try:
            conn = _connect(cfg, principal, test_password)
            steps.append(f"Signed in as {principal}")
        except LDAPException as e:
            return {"ok": False, "steps": steps, "error": f"Sign-in as {principal} failed: {e}"}
        try:
            user = _find_user(conn, cfg, _search_name(cfg, test_username, principal))
            if not user:
                return {"ok": False, "steps": steps, "error": "Signed in, but the user filter found no unique "
                        "entry under the search base: check the search base and the filter."}
            _describe(conn, cfg, user, steps)
            return {"ok": True, "steps": steps, "error": ""}
        except LDAPException as e:
            return {"ok": False, "steps": steps, "error": str(e)}
        finally:
            conn.unbind()

    try:
        conn = _service_connect(cfg)
        steps.append(f"Connected and bound as {cfg['bind_dn']}" if svc_mode
                     else "Connected (anonymous bind, no service account)")
    except LDAPException as e:
        return {"ok": False, "steps": steps, "error": f"{'Service' if svc_mode else 'Anonymous'} bind failed: {e}"}
    hint = "" if svc_mode else " " + ANON_HINT
    try:
        if test_username:
            user = _find_user(conn, cfg, _search_name(cfg, test_username, ""))
            if not user:
                return {"ok": False, "steps": steps,
                        "error": f"User '{test_username}' not found (or not unique) with the filter.{hint}"}
            _describe(conn, cfg, user, steps)
            if test_password:
                try:
                    _connect(cfg, user["dn"], test_password).unbind()
                    steps.append("User password accepted")
                except LDAPException as e:
                    return {"ok": False, "steps": steps, "error": f"User password rejected: {e}"}
        return {"ok": True, "steps": steps, "error": ""}
    except LDAPException as e:
        return {"ok": False, "steps": steps, "error": f"{e}.{hint}"}
    finally:
        conn.unbind()
