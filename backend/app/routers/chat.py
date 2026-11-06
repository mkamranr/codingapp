import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from openai import APIError, BadRequestError
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal, get_db
from ..models import Conversation, Message, WorkspaceFile, utcnow
from ..services import runtime_settings, workspace
from ..services.code_parser import parse_files
from ..services.context_builder import ContextTooSmall, CtxFile, HistMsg, build_messages
from ..services.llm_client import llm
from ..services.tokens import estimate
from .deps import own_conversation

log = logging.getLogger("codingapp.chat")
router = APIRouter(prefix="/api/conversations", tags=["chat"])

CONTINUE_PROMPT = ("Your previous answer was cut off by the output limit. Continue EXACTLY where it "
                   "stopped (mid-line or mid-code-block if needed). Do not repeat anything and do "
                   "not add any preamble.")
_native_continue = {"ok": True}  # flipped off if the server rejects continue_final_message


class SendIn(BaseModel):
    content: str = ""
    continue_last: bool = False


def sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/{cid}/messages")
async def send_message(body: SendIn, conv: Conversation = Depends(own_conversation),
                       db: Session = Depends(get_db)):
    info = await llm.info()
    if not info["ok"]:
        raise HTTPException(503, f"LLM server unavailable: {info['error']}")

    msgs = list(db.scalars(select(Message).where(Message.conversation_id == conv.id)
                           .order_by(Message.id)))
    if body.continue_last:
        if len(msgs) < 2 or msgs[-1].role != "assistant" or msgs[-2].role != "user":
            raise HTTPException(400, "Nothing to continue")
        target, user_msg = msgs[-1], msgs[-2]
        history = msgs[:-2]
        prefix, reasoning = target.content, target.reasoning
    else:
        text = body.content.strip()
        if not text:
            raise HTTPException(400, "Message is empty")
        user_msg = Message(conversation_id=conv.id, role="user", content=text, tokens=estimate(text))
        db.add(user_msg)
        target = Message(conversation_id=conv.id, role="assistant", content="")
        db.add(target)
        if conv.title in ("New chat", "") and not msgs:
            conv.title = text.splitlines()[0][:80]
        conv.updated_at = utcnow()
        db.commit()
        history, prefix, reasoning = msgs, "", ""

    rows = workspace.latest_files(db, conv.id)
    files = [CtxFile(p, r.content, r.tokens or estimate(r.content), r.origin == "generated")
             for p, r in rows.items()]
    hist = [HistMsg(m.role, m.content) for m in history]
    pinned = workspace.get_pinned(conv)
    thinking = runtime_settings.thinking_flag(db)
    cid, target_id, user_text, root = conv.id, target.id, user_msg.content, conv.root_name
    model, ctx_tokens = info["model"], info["context_tokens"]

    def finalize(content: str, reasoning_text: str, finish: str, ctx_info: dict) -> list:
        """Synchronous on purpose: also runs while the request is being cancelled."""
        with SessionLocal() as s:
            m = s.get(Message, target_id)
            m.content, m.reasoning, m.finish_reason = content, reasoning_text, finish
            m.tokens = estimate(content)
            m.context_json = json.dumps(ctx_info)
            s.execute(delete(WorkspaceFile).where(WorkspaceFile.message_id == target_id))
            parsed = parse_files(content)
            created = workspace.save_files(s, cid, [
                {"path": f.path, "content": f.content, "deleted": f.action == "delete",
                 "tokens": estimate(f.content)} for f in parsed
            ], origin="generated", message_id=target_id)
            c = s.get(Conversation, cid)
            c.updated_at = utcnow()
            s.commit()
            return [{"id": r.id, "path": r.path, "action": "delete" if r.deleted else "write"}
                    for r in created]

    async def generate():
        content, reasoning_text = prefix, reasoning
        finish, ctx_info, rounds = "", {}, 0
        yield sse("start", {"message_id": target_id, "user_message_id": user_msg.id,
                            "continue": bool(prefix)})
        try:
            while True:
                try:
                    built = build_messages(
                        files, hist, user_text, pinned=pinned, context_tokens=ctx_tokens,
                        max_output_tokens=settings.llm_max_output_tokens, root_name=root,
                        assistant_prefix=content,
                    )
                except ContextTooSmall as e:
                    ctx_info = {"error": str(e)}
                    finalize(content, reasoning_text, "error", ctx_info)
                    yield sse("error", {"message": str(e)})
                    return
                ctx_info = built.info
                yield sse("context", ctx_info)

                messages = built.messages
                native = bool(content) and _native_continue["ok"]
                if content and not native:
                    messages = messages + [{"role": "user", "content": CONTINUE_PROMPT}]
                got = ""
                try:
                    async for kind, val in llm.stream(messages, built.max_tokens, model, native,
                                                          thinking=thinking):
                        if kind == "content":
                            content += val
                            yield sse("delta", {"t": val})
                        elif kind == "reasoning":
                            reasoning_text += val
                            yield sse("reasoning", {"t": val})
                        elif kind == "finish":
                            got = val
                except BadRequestError as e:
                    if native:
                        log.warning("continue_final_message rejected (%s); using prompt mode", e)
                        _native_continue["ok"] = False
                        continue
                    raise
                finish = got or "stop"
                if finish == "length" and rounds < settings.llm_auto_continue:
                    rounds += 1
                    yield sse("continuing", {"round": rounds})
                    continue
                break
            produced = finalize(content, reasoning_text, finish, ctx_info)
            yield sse("files", {"files": produced})
            yield sse("done", {"finish_reason": finish})
        except (asyncio.CancelledError, GeneratorExit):
            finalize(content, reasoning_text, "stopped", ctx_info)
            raise
        except APIError as e:
            log.exception("LLM error")
            ctx_info = {**ctx_info, "error": str(e)}
            produced = finalize(content, reasoning_text, "error", ctx_info)
            yield sse("files", {"files": produced})
            yield sse("error", {"message": f"LLM error: {e}"})
        except Exception as e:  # pragma: no cover
            log.exception("Chat failure")
            ctx_info = {**ctx_info, "error": str(e)}
            finalize(content, reasoning_text, "error", ctx_info)
            yield sse("error", {"message": f"Server error: {e}"})

    return StreamingResponse(generate(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive",
    })
