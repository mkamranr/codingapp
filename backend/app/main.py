import asyncio
import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import Base, engine
from .routers import admin, auth, chat, conversations, downloads
from .services.llm_client import llm

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("codingapp")

Base.metadata.create_all(engine)

app = FastAPI(title="CodingApp", docs_url="/api/docs", openapi_url="/api/openapi.json")

UPLOAD_LIMIT = settings.max_upload_mb * 1024 * 1024 + 1024 * 1024  # + multipart overhead


@app.middleware("http")
async def limit_body(request: Request, call_next):
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > UPLOAD_LIMIT:
        return JSONResponse({"detail": f"Upload exceeds {settings.max_upload_mb} MB"}, 413)
    return await call_next(request)


for r in (auth.router, admin.router, conversations.router, chat.router, downloads.router):
    app.include_router(r)


@app.get("/api/health")
async def health():
    try:  # never let a slow/unreachable LLM make the container look unhealthy
        info = await asyncio.wait_for(llm.info(), timeout=3)
    except asyncio.TimeoutError:
        info = llm.last_info()
    return {"ok": True, "version": os.environ.get("APP_VERSION", "dev"), "llm": info["ok"], "model": info["model"],
            "context_tokens": info["context_tokens"], "max_upload_mb": settings.max_upload_mb}


@app.on_event("startup")
async def startup():
    if not settings.admin_password:
        log.warning("ADMIN_PASSWORD is empty: the built-in admin account is disabled")
    async def probe():
        info = await llm.info()
        log.info("LLM %s model=%s context=%s (%s)", "OK" if info["ok"] else "UNAVAILABLE",
                 info["model"], info["context_tokens"], info["context_source"])
    asyncio.get_running_loop().create_task(probe())  # don't block startup on the LLM


# ---- Serve the built frontend (single-image deployment) ----
static = Path(settings.static_dir) if settings.static_dir else None
if static and (static / "index.html").exists():
    if (static / "assets").exists():
        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, 404)
        candidate = (static / full_path).resolve()
        if full_path and candidate.is_file() and static.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(static / "index.html", headers={"Cache-Control": "no-cache"})
