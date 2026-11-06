from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Conversation, User
from ..security import require_admin
from ..services import ldap_auth, runtime_settings
from ..services.llm_client import llm
from ..services.tokens import counter

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


class LdapIn(BaseModel):
    enabled: bool = False
    server_url: str = ""
    start_tls: bool = False
    verify_cert: bool = True
    ca_cert_path: str = ""
    timeout: int = 10
    bind_dn: str = ""
    bind_password: str = ""
    user_bind_format: str = ""
    clear_bind_password: bool = False
    search_base: str = ""
    user_filter: str = "(&(objectClass=user)(sAMAccountName={username}))"
    display_name_attr: str = "displayName"
    email_attr: str = "mail"
    required_group_dn: str = ""
    admin_group_dn: str = ""
    nested_groups: bool = True


class LdapTestIn(LdapIn):
    test_username: str = ""
    test_password: str = ""


@router.get("/ldap")
def get_ldap(db: Session = Depends(get_db)):
    return ldap_auth.load_config(db)


@router.put("/ldap")
def put_ldap(body: LdapIn, db: Session = Depends(get_db)):
    return ldap_auth.save_config(db, body.model_dump())


@router.post("/ldap/test")
def test_ldap(body: LdapTestIn, db: Session = Depends(get_db)):
    """Tests the settings in the form (unsaved); blank password -> use the stored one."""
    cfg = ldap_auth.load_config(db, with_secret=True)
    form = body.model_dump()
    pw = form.pop("bind_password")
    test_user = form.pop("test_username")
    test_pw = form.pop("test_password")
    clear = form.pop("clear_bind_password", False)
    cfg.update(form)
    if clear:
        cfg["bind_password"] = ""  # test anonymous search even if a password is stored
    elif pw:
        cfg["bind_password"] = pw
    return ldap_auth.test_connection(cfg, test_user.strip(), test_pw)


class LlmSettingsIn(BaseModel):
    thinking: str  # default | on | off


@router.get("/llm")
async def llm_status(db: Session = Depends(get_db)):
    info = await llm.info(force=True)
    return {**info, "exact_tokenizer": counter.exact, **runtime_settings.load(db)}


@router.put("/llm/settings")
def llm_settings(body: LlmSettingsIn, db: Session = Depends(get_db)):
    try:
        return runtime_settings.save(db, body.thinking)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/users")
def users(db: Session = Depends(get_db)):
    counts = dict(db.execute(
        select(Conversation.user_id, func.count(Conversation.id)).group_by(Conversation.user_id)
    ).all())
    rows = db.scalars(select(User).order_by(User.source, User.username))
    return [{
        "id": u.id, "username": u.username, "display_name": u.display_name, "email": u.email,
        "source": u.source, "is_admin": u.is_admin, "conversations": counts.get(u.id, 0),
        "last_login": u.last_login.isoformat() if u.last_login else None,
    } for u in rows]
