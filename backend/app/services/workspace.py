"""Versioned per-conversation project files."""
import json
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Conversation, WorkspaceFile


def _all_latest(db: Session, cid: int, upto_message_id: Optional[int] = None) -> dict:
    rows = db.scalars(
        select(WorkspaceFile)
        .where(WorkspaceFile.conversation_id == cid)
        .order_by(WorkspaceFile.version, WorkspaceFile.id)
    )
    latest: dict = {}
    for r in rows:
        if upto_message_id is not None and r.message_id is not None and r.message_id > upto_message_id:
            continue
        latest[r.path] = r
    return latest


def latest_files(db: Session, cid: int, upto_message_id: Optional[int] = None) -> dict:
    """path -> WorkspaceFile (latest non-deleted version)."""
    return {p: r for p, r in _all_latest(db, cid, upto_message_id).items() if not r.deleted}


def save_files(db: Session, cid: int, files: list, origin: str,
               message_id: Optional[int] = None) -> list:
    """files: list of dicts {path, content, tokens, deleted}. Returns created rows."""
    current = _all_latest(db, cid)
    created = []
    for f in files:
        prev = current.get(f["path"])
        if f.get("deleted") and (prev is None or prev.deleted):
            continue
        row = WorkspaceFile(
            conversation_id=cid,
            path=f["path"],
            content=f.get("content", ""),
            tokens=f.get("tokens", 0),
            deleted=bool(f.get("deleted")),
            origin=origin,
            version=(prev.version + 1) if prev else (0 if origin == "upload" else 1),
            message_id=message_id,
        )
        db.add(row)
        created.append(row)
    db.flush()
    return created


def get_pinned(conv: Conversation) -> set:
    try:
        return set(json.loads(conv.pinned_json or "[]"))
    except ValueError:
        return set()


def set_pinned(conv: Conversation, pinned: set) -> None:
    conv.pinned_json = json.dumps(sorted(pinned))
