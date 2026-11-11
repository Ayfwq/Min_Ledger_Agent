from __future__ import annotations

import os
import uuid
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./.pytest-ledger.db")
os.environ.setdefault("WORKER_ENABLED", "false")
os.environ.setdefault("APP_PASSWORD", "")

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.session import get_session  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Merchant  # noqa: E402

DB_FILE = Path("./.pytest-ledger.db")


@pytest_asyncio.fixture(scope="session")
async def engine():
    if DB_FILE.exists():  # noqa: ASYNC240
        DB_FILE.unlink()  # noqa: ASYNC240
    eng = create_async_engine(f"sqlite+aiosqlite:///{DB_FILE}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()
    if DB_FILE.exists():  # noqa: ASYNC240
        DB_FILE.unlink()  # noqa: ASYNC240


@pytest_asyncio.fixture
async def session(engine):
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s


@pytest_asyncio.fixture
async def client(engine):
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override():
        async with maker() as s:
            yield s

    app.dependency_overrides[get_session] = override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def merchants(session):
    rows = [
        Merchant(
            id=uuid.uuid4(),
            name="星巴克",
            normalized="星巴克",
            aliases="星巴克,starbucks,starbucks coffee",
            category="餐饮",
            confidence="0.950",
        ),
        Merchant(
            id=uuid.uuid4(),
            name="滴滴出行",
            normalized="滴滴出行",
            aliases="滴滴,滴滴出行,didi",
            category="交通",
            confidence="0.950",
        ),
    ]
    session.add_all(rows)
    await session.commit()
    return rows


@pytest.fixture
def fake_llm(monkeypatch):
    """Patch the LLM extraction with a deterministic fake."""

    state = {"transactions": [], "warnings": []}

    async def fake_extract_text(text: str):
        from app.services.llm import ExtractionResult

        return ExtractionResult.model_validate({"transactions": state["transactions"], "warnings": state["warnings"]}), {
            "transactions": state["transactions"]
        }

    async def fake_extract_image(path, content_type, context_text=None):
        state["image_context"] = context_text
        return await fake_extract_text("")

    monkeypatch.setattr("app.services.pipeline.llm_client.extract_text", fake_extract_text)
    monkeypatch.setattr("app.services.pipeline.llm_client.extract_image", fake_extract_image)
    return state
