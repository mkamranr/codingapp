"""LLM behaviour settings the administrator can change at runtime (stored in the DB)."""
import json
from typing import Optional

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Setting

KEY = "llm_runtime"
THINKING_MODES = ("default", "on", "off")


def _env_thinking() -> str:
    v = settings.llm_enable_thinking.strip().lower()
    return {"true": "on", "false": "off"}.get(v, "default")


def load(db: Session) -> dict:
    cfg = {"thinking": _env_thinking()}
    row = db.get(Setting, KEY)
    if row:
        try:
            cfg.update(json.loads(row.value))
        except ValueError:
            pass
    if cfg["thinking"] not in THINKING_MODES:
        cfg["thinking"] = "default"
    return cfg


def save(db: Session, thinking: str) -> dict:
    if thinking not in THINKING_MODES:
        raise ValueError(f"thinking must be one of {THINKING_MODES}")
    row = db.get(Setting, KEY) or Setting(key=KEY)
    row.value = json.dumps({"thinking": thinking})
    db.add(row)
    db.commit()
    return load(db)


def thinking_flag(db: Session) -> Optional[bool]:
    """None = leave it to the model's chat template; True/False = force enable_thinking."""
    return {"on": True, "off": False}.get(load(db)["thinking"])
