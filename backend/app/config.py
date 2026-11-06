import logging
import os
import secrets
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger("codingapp")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Built-in administrator (always available, independent of LDAP)
    admin_username: str = "admin"
    admin_password: str = ""

    # Used to sign session tokens and encrypt the LDAP bind password.
    # If empty, a random key is generated and stored in DATA_DIR/secret.key.
    secret_key: str = ""

    data_dir: str = "./data"
    static_dir: str = ""  # optional: serve built frontend from FastAPI (local runs without nginx)

    # OpenAI-compatible LLM endpoint (vLLM, Ollama, ...)
    llm_base_url: str = "http://localhost:8000/v1"
    llm_api_key: str = "EMPTY"
    llm_model: str = ""  # empty -> first model reported by /v1/models
    llm_context_tokens: int = 0  # 0 -> auto-detect from /v1/models (max_model_len)
    llm_max_output_tokens: int = 32768
    llm_temperature: float = 0.2
    llm_enable_thinking: str = ""  # "", "true", "false" -> chat_template_kwargs.enable_thinking
    llm_auto_continue: int = 3  # automatic continuations when the output hits max_tokens
    llm_request_timeout: int = 1800

    # Upload limits
    max_upload_mb: int = 25
    max_extracted_mb: int = 200
    max_files: int = 5000
    max_file_kb: int = 2048

    session_hours: int = 12
    cookie_secure: bool = False

    @field_validator("*", mode="before")
    @classmethod
    def _empty_to_default(cls, v, info):
        if isinstance(v, str) and v.strip() == "":
            return cls.model_fields[info.field_name].default
        return v


settings = Settings()

Path(settings.data_dir).mkdir(parents=True, exist_ok=True)

if not settings.secret_key:
    key_file = Path(settings.data_dir) / "secret.key"
    if key_file.exists():
        settings.secret_key = key_file.read_text().strip()
    else:
        settings.secret_key = secrets.token_urlsafe(48)
        key_file.write_text(settings.secret_key)
        try:
            os.chmod(key_file, 0o600)
        except OSError:
            pass
        log.warning("SECRET_KEY not set; generated one in %s", key_file)
