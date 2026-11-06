"""Token counting: exact via vLLM /tokenize when available, otherwise a char-based estimate."""
import asyncio
import hashlib
import logging
import time
from collections import OrderedDict

import httpx

from ..config import settings

log = logging.getLogger("codingapp.tokens")

CHARS_PER_TOKEN = 3.2


def estimate(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 1 if text else 0


class TokenCounter:
    def __init__(self, base_url: str, api_key: str):
        root = base_url.rstrip("/")
        if root.endswith("/v1"):
            root = root[:-3]
        self.url = root + "/tokenize"
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._cache: OrderedDict = OrderedDict()
        self._sem = asyncio.Semaphore(16)
        self._remote_down_until = 0.0
        self.exact = None  # None = unknown, True/False after first attempt

    def _get(self, key):
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def _put(self, key, val):
        self._cache[key] = val
        if len(self._cache) > 50000:
            self._cache.popitem(last=False)

    async def count(self, text: str, model: str) -> int:
        if not text:
            return 0
        if len(text) < 256 or time.time() < self._remote_down_until:
            return estimate(text)
        key = hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()
        cached = self._get(key)
        if cached is not None:
            return cached
        try:
            async with self._sem:
                async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=5)) as client:
                    r = await client.post(
                        self.url, json={"model": model, "prompt": text}, headers=self.headers
                    )
            r.raise_for_status()
            n = int(r.json()["count"])
            self.exact = True
        except Exception as e:  # endpoint missing / not vLLM -> estimate for 5 minutes
            if self.exact is not False:
                log.info("Exact tokenization unavailable (%s); using estimates", e)
            self.exact = False
            self._remote_down_until = time.time() + 300
            return estimate(text)
        self._put(key, n)
        return n

    async def count_many(self, texts: list, model: str) -> list:
        return list(await asyncio.gather(*(self.count(t, model) for t in texts)))


counter = TokenCounter(settings.llm_base_url, settings.llm_api_key)
