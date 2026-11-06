import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import User, utcnow
from ..security import clear_session, constant_eq, get_current_user, issue_session, throttle
from ..services import ldap_auth

log = logging.getLogger("codingapp.auth")
router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


def user_out(u: User) -> dict:
    return {"id": u.id, "username": u.username, "display_name": u.display_name or u.username,
            "email": u.email, "is_admin": u.is_admin, "source": u.source}


def _upsert(db: Session, source: str, username: str, **fields) -> User:
    u = db.scalar(select(User).where(User.source == source, User.username == username))
    if not u:
        u = User(source=source, username=username)
        db.add(u)
    for k, v in fields.items():
        setattr(u, k, v)
    u.last_login = utcnow()
    db.commit()
    return u


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    username = body.username.strip()
    ip = request.client.host if request.client else "?"
    keys = (f"u:{username.lower()}", f"ip:{ip}")
    if throttle.blocked(*keys):
        raise HTTPException(429, "Too many failed attempts. Try again in a few minutes.")

    user = None
    # 1) built-in administrator from .env
    if settings.admin_password and constant_eq(username, settings.admin_username) \
            and constant_eq(body.password, settings.admin_password):
        user = _upsert(db, "local", settings.admin_username,
                       display_name="Administrator", is_admin=True)
    # 2) Active Directory / LDAP
    if user is None:
        cfg = ldap_auth.load_config(db, with_secret=True)
        if cfg["enabled"]:
            try:
                res = ldap_auth.authenticate(cfg, username, body.password)
            except PermissionError as e:
                throttle.fail(*keys)
                raise HTTPException(403, str(e))
            except ConnectionError as e:
                raise HTTPException(503, str(e))
            if res:
                user = _upsert(db, "ldap", res.get("username") or username.lower(), display_name=res["display_name"],
                               email=res["email"], is_admin=res["is_admin"])
    if user is None:
        throttle.fail(*keys)
        log.info("Failed login for %r from %s", username, ip)
        raise HTTPException(401, "Invalid username or password")
    throttle.reset(*keys)
    issue_session(response, user)
    return user_out(user)


@router.post("/logout")
def logout(response: Response):
    clear_session(response)
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return user_out(user)
