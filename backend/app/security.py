import hmac
import time
from collections import defaultdict, deque

import jwt
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import User

COOKIE_NAME = "codingapp_session"
ALGO = "HS256"


def constant_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def issue_session(response: Response, user: User) -> None:
    exp = int(time.time()) + settings.session_hours * 3600
    token = jwt.encode({"sub": str(user.id), "exp": exp}, settings.secret_key, algorithm=ALGO)
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_hours * 3600,
        httponly=True,
        samesite="strict",
        secure=settings.cookie_secure,
        path="/",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(401, "Not authenticated")
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGO])
        user = db.get(User, int(payload["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(401, "Invalid session")
    if not user:
        raise HTTPException(401, "Invalid session")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Administrator access required")
    return user


class LoginThrottle:
    """Simple in-memory brute-force protection: N failures per window per username/IP."""

    def __init__(self, max_failures: int = 10, window: int = 300):
        self.max_failures = max_failures
        self.window = window
        self._fails: dict[str, deque] = defaultdict(deque)

    def _prune(self, key: str) -> deque:
        q = self._fails[key]
        now = time.time()
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def blocked(self, *keys: str) -> bool:
        return any(len(self._prune(k)) >= self.max_failures for k in keys)

    def fail(self, *keys: str) -> None:
        for k in keys:
            self._prune(k).append(time.time())

    def reset(self, *keys: str) -> None:
        for k in keys:
            self._fails.pop(k, None)


throttle = LoginThrottle()
