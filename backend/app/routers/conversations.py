import json
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Conversation, Message, User, WorkspaceFile, utcnow
from ..security import get_current_user
from ..services import workspace
from ..services.extractor import ExtractError, Limits, process_uploads
from ..services.llm_client import llm
from ..services.tokens import counter
from .deps import own_conversation

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


def conv_out(c: Conversation) -> dict:
    return {"id": c.id, "title": c.title, "root_name": c.root_name,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None}


def files_out(db: Session, conv: Conversation) -> list:
    pinned = workspace.get_pinned(conv)
    rows = workspace.latest_files(db, conv.id)
    return [{"id": r.id, "path": p, "tokens": r.tokens, "version": r.version,
             "modified": r.origin == "generated", "pinned": p in pinned, "size": len(r.content)}
            for p, r in sorted(rows.items())]


def message_out(m: Message, files: list) -> dict:
    try:
        ctx = json.loads(m.context_json or "{}")
    except ValueError:
        ctx = {}
    return {"id": m.id, "role": m.role, "content": m.content, "reasoning": m.reasoning,
            "finish_reason": m.finish_reason, "tokens": m.tokens, "context": ctx,
            "files": files, "created_at": m.created_at.isoformat() if m.created_at else None}


class ConvIn(BaseModel):
    title: Optional[str] = None


@router.get("")
def list_conversations(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(Conversation).where(Conversation.user_id == user.id)
                      .order_by(Conversation.updated_at.desc()))
    return [conv_out(c) for c in rows]


@router.post("")
def create_conversation(body: ConvIn, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    c = Conversation(user_id=user.id, title=(body.title or "New chat")[:200])
    db.add(c)
    db.commit()
    return conv_out(c)


@router.get("/{cid}")
def get_conversation(conv: Conversation = Depends(own_conversation), db: Session = Depends(get_db)):
    msgs = list(db.scalars(select(Message).where(Message.conversation_id == conv.id)
                           .order_by(Message.id)))
    gen = db.scalars(select(WorkspaceFile).where(
        WorkspaceFile.conversation_id == conv.id, WorkspaceFile.message_id.is_not(None)))
    by_msg: dict = {}
    for f in gen:
        by_msg.setdefault(f.message_id, []).append(
            {"id": f.id, "path": f.path, "action": "delete" if f.deleted else "write"})
    return {**conv_out(conv),
            "messages": [message_out(m, by_msg.get(m.id, [])) for m in msgs],
            "files": files_out(db, conv)}


@router.patch("/{cid}")
def rename(body: ConvIn, conv: Conversation = Depends(own_conversation),
           db: Session = Depends(get_db)):
    if body.title:
        conv.title = body.title.strip()[:200]
        db.commit()
    return conv_out(conv)


@router.delete("/{cid}")
def remove(conv: Conversation = Depends(own_conversation), db: Session = Depends(get_db)):
    db.execute(delete(WorkspaceFile).where(WorkspaceFile.conversation_id == conv.id))
    db.execute(delete(Message).where(Message.conversation_id == conv.id))
    db.delete(conv)
    db.commit()
    return {"ok": True}


class PinIn(BaseModel):
    path: str
    pinned: bool


@router.post("/{cid}/pins")
def pin(body: PinIn, conv: Conversation = Depends(own_conversation), db: Session = Depends(get_db)):
    pinned = workspace.get_pinned(conv)
    (pinned.add if body.pinned else pinned.discard)(body.path)
    workspace.set_pinned(conv, pinned)
    db.commit()
    return {"pinned": sorted(pinned)}


@router.get("/{cid}/file")
def file_content(path: str, conv: Conversation = Depends(own_conversation),
                 db: Session = Depends(get_db)):
    row = workspace.latest_files(db, conv.id).get(path)
    if not row:
        raise HTTPException(404, "File not found")
    return {"id": row.id, "path": row.path, "content": row.content, "version": row.version,
            "modified": row.origin == "generated"}


@router.delete("/{cid}/files")
def remove_files(path: Optional[str] = None, conv: Conversation = Depends(own_conversation),
                 db: Session = Depends(get_db)):
    """Remove one file (path=...) or all files (no path) from the project."""
    if path is None:
        db.execute(delete(WorkspaceFile).where(WorkspaceFile.conversation_id == conv.id))
        conv.root_name = ""
    else:
        workspace.save_files(db, conv.id, [{"path": path, "deleted": True}], origin="upload")
    db.commit()
    return {"files": files_out(db, conv)}


@router.post("/{cid}/files")
async def upload(request: Request, files: list[UploadFile] = File(...),
                 conv: Conversation = Depends(own_conversation), db: Session = Depends(get_db)):
    limit = settings.max_upload_mb * 1024 * 1024
    items, total = [], 0
    for uf in files:
        chunks = []
        while True:
            chunk = await uf.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise HTTPException(413, f"Upload exceeds {settings.max_upload_mb} MB")
            chunks.append(chunk)
        items.append((uf.filename or "file.txt", b"".join(chunks)))

    limits = Limits(settings.max_extracted_mb * 1024 * 1024, settings.max_files,
                    settings.max_file_kb * 1024)
    try:
        result = process_uploads(items, limits)
    except ExtractError as e:
        raise HTTPException(400, str(e))
    if not result.files:
        raise HTTPException(400, "No readable source files found in the upload")

    info = await llm.info()
    toks = await counter.count_many([c for _, c in result.files], info["model"])
    workspace.save_files(db, conv.id, [
        {"path": p, "content": c, "tokens": t} for (p, c), t in zip(result.files, toks)
    ], origin="upload")
    if result.root_name and not conv.root_name:
        conv.root_name = result.root_name
    if conv.title == "New chat":
        conv.title = (result.root_name or result.files[0][0])[:200]
    conv.updated_at = utcnow()
    db.commit()
    return {
        "added": len(result.files),
        "added_tokens": sum(toks),
        "skipped": [{"path": p, "reason": r} for p, r in result.skipped[:500]],
        "skipped_total": len(result.skipped),
        "root_name": conv.root_name,
        "title": conv.title,
        "files": files_out(db, conv),
    }
