import posixpath
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Conversation, User, WorkspaceFile
from ..security import get_current_user
from ..services import workspace
from ..services.zip_builder import build_zip
from .deps import own_conversation

router = APIRouter(prefix="/api", tags=["downloads"])


def _disposition(filename: str) -> str:
    ascii_name = filename.encode("ascii", "replace").decode().replace('"', "_")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


@router.get("/files/{file_id}/download")
def download_file(file_id: int, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    row = db.get(WorkspaceFile, file_id)
    conv = db.get(Conversation, row.conversation_id) if row else None
    if not row or not conv or conv.user_id != user.id:
        raise HTTPException(404, "File not found")
    return Response(row.content.encode("utf-8"), media_type="application/octet-stream",
                    headers={"Content-Disposition": _disposition(posixpath.basename(row.path))})


@router.get("/conversations/{cid}/export.zip")
def export_zip(mode: str = Query("full", pattern="^(full|changed)$"),
               message_id: Optional[int] = None,
               conv: Conversation = Depends(own_conversation), db: Session = Depends(get_db)):
    root = conv.root_name or "project"
    if mode == "full":
        files = workspace.latest_files(db, conv.id, upto_message_id=message_id)
        content = {p: r.content for p, r in files.items()}
        deleted: list = []
        name = f"{root}.zip"
    else:
        q = select(WorkspaceFile).where(WorkspaceFile.conversation_id == conv.id,
                                        WorkspaceFile.origin == "generated")
        if message_id is not None:
            q = q.where(WorkspaceFile.message_id == message_id)
        latest: dict = {}
        for r in db.scalars(q.order_by(WorkspaceFile.version, WorkspaceFile.id)):
            latest[r.path] = r
        content = {p: r.content for p, r in latest.items() if not r.deleted}
        deleted = [p for p, r in latest.items() if r.deleted]
        name = f"{root}-changes.zip"
    if not content and not deleted:
        raise HTTPException(404, "No files to export")
    data = build_zip(content, root, deleted)
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": _disposition(name)})
