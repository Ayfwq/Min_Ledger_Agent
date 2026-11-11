from __future__ import annotations

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api.routes import router
from app.core.config import settings
from app.core.logging import setup_logging
from app.db.session import engine
from app.services.worker import worker

logger = logging.getLogger(__name__)

PUBLIC_PATHS = {"/api/v1/auth/verify", "/api/v1/health", "/health"}


async def _wait_for_database(attempts: int = 30) -> None:
    for attempt in range(attempts):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("select 1"))
            logger.info("database ready")
            return
        except Exception as exc:  # pragma: no cover - startup retry
            if attempt == attempts - 1:
                logger.error("database not ready after %s attempts: %s", attempts, exc)
                raise
            await asyncio.sleep(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging("DEBUG" if settings.debug else "INFO")
    await _wait_for_database()
    if settings.worker_enabled:
        worker.start()
    logger.info(
        "app started version=%s env=%s text_model=%s vision_model=%s",
        settings.app_version,
        settings.environment,
        settings.llm_text_model,
        settings.llm_vision_model,
    )
    try:
        yield
    finally:
        if settings.worker_enabled:
            await worker.stop()
        await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="可澄清、可追溯的智能记账助手",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def optional_password(request: Request, call_next):
    if not settings.app_password:
        return await call_next(request)
    path = request.url.path
    if request.method == "OPTIONS" or path in PUBLIC_PATHS or path.startswith("/uploads/"):
        return await call_next(request)
    token = request.headers.get("X-App-Password", "")
    if secrets.compare_digest(token, settings.app_password):
        return await call_next(request)
    return JSONResponse(status_code=401, content={"detail": "需要访问密码", "code": "unauthorized"})


app.include_router(router, prefix=settings.api_prefix)
app.mount("/uploads", StaticFiles(directory=str(settings.upload_path)), name="uploads")


@app.get("/")
async def root() -> dict[str, str]:
    return {"name": settings.app_name, "docs": "/docs", "health": f"{settings.api_prefix}/health"}
