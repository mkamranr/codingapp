"""OpenAI-compatible LLM client (vLLM, Ollama, LM Studio, ...)."""
import logging
import time
from typing import AsyncIterator, Optional

import anyio
import httpx
from openai import AsyncOpenAI

from ..config import settings

log = logging.getLogger("codingapp.llm")
DEFAULT_CONTEXT = 32768


class LLM:
    def __init__(self):
        self.client = AsyncOpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key or "EMPTY",
            timeout=httpx.Timeout(settings.llm_request_timeout, connect=15),
            max_retries=1,
        )
        self._info: Optional[dict] = None
        self._info_at = 0.0

    async def info(self, force: bool = False) -> dict:
        if self._info and not force:
            ttl = 120 if self._info["ok"] else 15  # retry an unreachable server every 15 s
            if time.time() - self._info_at < ttl:
                return self._info
        info = self.default_info()
        try:
            res = await self.client.with_options(timeout=httpx.Timeout(10, connect=4), max_retries=0).models.list()
            models = list(res.data)
            info["models"] = [m.id for m in models]
            chosen = next((m for m in models if m.id == settings.llm_model), None)
            if chosen is None and models and not settings.llm_model:
                chosen = models[0]
            if chosen is None:
                raise RuntimeError(f"Model '{settings.llm_model}' not found on server")
            info["model"] = chosen.id
            extra = getattr(chosen, "model_extra", None) or {}
            mml = getattr(chosen, "max_model_len", None) or extra.get("max_model_len")
            if not settings.llm_context_tokens and mml:
                info["context_tokens"] = int(mml)
                info["context_source"] = "detected"
            info["ok"] = True
        except Exception as e:
            info["error"] = str(e) or e.__class__.__name__
            log.warning("LLM info failed: %s", info["error"])
        self._info, self._info_at = info, time.time()
        return info

    def last_info(self) -> dict:
        return self._info or self.default_info()

    @staticmethod
    def default_info() -> dict:
        return {
            "ok": False, "base_url": settings.llm_base_url, "model": settings.llm_model,
            "context_tokens": settings.llm_context_tokens or DEFAULT_CONTEXT,
            "context_source": "config" if settings.llm_context_tokens else "default",
            "max_output_tokens": settings.llm_max_output_tokens, "models": [], "error": "",
        }

    async def stream(
        self, messages: list, max_tokens: int, model: str, continue_final: bool = False,
        thinking: Optional[bool] = None,
    ) -> AsyncIterator[tuple]:
        """Yields ("content"|"reasoning", text), ("finish", reason), ("usage", obj).
        thinking: None = model default, True/False = chat_template_kwargs.enable_thinking."""
        extra: dict = {}
        if thinking is not None:
            extra["chat_template_kwargs"] = {"enable_thinking": thinking}
        if continue_final:
            extra.update({"continue_final_message": True, "add_generation_prompt": False})
        stream = await self.client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=settings.llm_temperature,
            stream=True,
            stream_options={"include_usage": True},
            extra_body=extra or None,
        )
        try:
            async for chunk in stream:
                if getattr(chunk, "usage", None):
                    yield ("usage", chunk.usage)
                if not chunk.choices:
                    continue
                ch = chunk.choices[0]
                d = ch.delta
                if d is not None:
                    dx = getattr(d, "model_extra", None) or {}
                    rc = getattr(d, "reasoning_content", None) or dx.get("reasoning_content") \
                        or dx.get("reasoning")
                    if rc:
                        yield ("reasoning", rc)
                    if d.content:
                        yield ("content", d.content)
                if ch.finish_reason:
                    yield ("finish", ch.finish_reason)
        finally:
            with anyio.CancelScope(shield=True):
                await stream.close()


llm = LLM()
