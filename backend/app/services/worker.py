"""DB-backed job queue + background worker.

Jobs live in PostgreSQL so a restart never loses pending work. Claiming uses
`FOR UPDATE SKIP LOCKED` on PostgreSQL (single worker fallback on SQLite).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import Input, Job
from app.services.pipeline import add_trace
from app.services.pipeline import process_input as run_pipeline

logger = logging.getLogger(__name__)

STALE_AFTER = timedelta(minutes=10)


async def enqueue_job(session, input_id: uuid.UUID, kind: str = "process_input") -> Job:
    active = await session.scalar(
        select(Job).where(
            Job.input_id == input_id,
            Job.kind == kind,
            Job.status.in_(["queued", "running"]),
        )
    )
    if active is not None:
        return active
    job = Job(input_id=input_id, kind=kind, status="queued", max_attempts=settings.worker_max_attempts)
    session.add(job)
    return job


async def claim_job() -> uuid.UUID | None:
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        stmt = (
            select(Job.id)
            .where(Job.status == "queued", Job.run_after <= now)
            .order_by(Job.created_at)
            .limit(1)
        )
        if session.bind and session.bind.dialect.name == "postgresql":
            stmt = stmt.with_for_update(skip_locked=True)
        job_id = await session.scalar(stmt)
        if job_id is None:
            await session.rollback()
            return None
        job = await session.get(Job, job_id)
        if job is None or job.status != "queued":
            await session.rollback()
            return None
        job.status = "running"
        job.attempts += 1
        job.locked_at = now
        await session.commit()
        return job_id


async def run_job(job_id: uuid.UUID) -> None:
    async with SessionLocal() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return
        input_id = job.input_id
        input_item = await session.get(Input, input_id)
        if input_item is None:
            job.status = "done"
            job.last_error = "input 已删除"
            await session.commit()
            return
        if input_item.status == "confirmed":
            job.status = "done"
            await session.commit()
            return

    try:
        async with SessionLocal() as session:
            await run_pipeline(session, input_id)
    except Exception as exc:  # noqa: BLE001 - failure must be recorded, never silent
        logger.exception("pipeline failed job=%s input=%s", job_id, input_id)
        async with SessionLocal() as session:
            job = await session.get(Job, job_id)
            if job is None:
                return
            job.last_error = str(exc)[:1000]
            if job.attempts >= job.max_attempts:
                job.status = "failed"
                await add_trace(
                    session, input_id, "job", "failed", f"任务重试次数用尽：{exc}"
                )
            else:
                job.status = "queued"
                job.run_after = datetime.now(UTC) + timedelta(seconds=min(30, 2**job.attempts))
                await add_trace(
                    session, input_id, "job", "retried", f"任务失败，将自动重试：{exc}"
                )
            await session.commit()
        return

    async with SessionLocal() as session:
        job = await session.get(Job, job_id)
        if job is not None:
            job.status = "done"
            job.last_error = None
            await session.commit()


async def recover_stale_jobs() -> int:
    cutoff = datetime.now(UTC) - STALE_AFTER
    async with SessionLocal() as session:
        result = await session.execute(
            update(Job)
            .where(Job.status == "running", Job.locked_at < cutoff)
            .values(status="queued", run_after=datetime.now(UTC))
        )
        await session.commit()
        count = result.rowcount or 0
        if count:
            logger.warning("recovered %s stale jobs", count)
        return count


class Worker:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stopping = False

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self._task is not None:
            return
        self._stopping = False
        self._task = asyncio.create_task(self._loop(), name="ledger-worker")
        logger.info("worker started")

    async def stop(self) -> None:
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("worker stopped")

    async def _loop(self) -> None:
        await recover_stale_jobs()
        while not self._stopping:
            try:
                job_id = await claim_job()
                if job_id is None:
                    await asyncio.sleep(settings.worker_poll_interval)
                    continue
                await run_job(job_id)
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover - keep the worker alive
                logger.exception("worker loop error")
                await asyncio.sleep(2)


worker = Worker()
