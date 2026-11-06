from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Conversation, User
from ..security import get_current_user


def own_conversation(cid: int, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)) -> Conversation:
    conv = db.get(Conversation, cid)
    if not conv or conv.user_id != user.id:
        raise HTTPException(404, "Conversation not found")
    return conv
