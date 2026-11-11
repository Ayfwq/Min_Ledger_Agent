"""Review actions: edit, confirm, reject, retry data source, retry input."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Bill, Clarification, Draft, IdempotencyKey, Input, Job
from app.services import datasources
from app.services.pipeline import (
    add_trace,
    compute_warnings,
    ensure_clarification,
    json_safe,
    recompute_input_status,
)


class LedgerError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 409,
        code: str = "conflict",
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.details = details or {}


async def _get_draft(session: AsyncSession, draft_id: uuid.UUID, *, lock: bool = False) -> Draft:
    draft = await session.get(Draft, draft_id, with_for_update=lock)
    if draft is None:
        raise LedgerError("草稿不存在", status_code=404, code="not_found")
    return draft


async def update_draft(
    session: AsyncSession, draft_id: uuid.UUID, changes: dict[str, Any], *, force: bool = False
) -> Draft:
    draft = await _get_draft(session, draft_id, lock=True)
    if draft.status == "confirmed":
        raise LedgerError("已入账的账单不可编辑", status_code=409, code="already_confirmed")

    input_item = await session.get(Input, draft.input_id)

    # Detect silent overrides of model/screenshot values.
    conflicts: dict[str, dict] = {}
    if not force:
        for field, value in changes.items():
            if field == "note":
                continue
            current = getattr(draft, field)
            source = (draft.field_sources or {}).get(field) or "text"
            if current is None or value is None or source == "user":
                continue
            if field == "amount":
                try:
                    same = Decimal(str(current)) == Decimal(str(value))
                except Exception:
                    same = False
            else:
                same = str(current) == str(value)
            if not same:
                conflicts[field] = {
                    "field": field,
                    "existing": json_safe(current),
                    "proposed": json_safe(value),
                    "source": source,
                }
    if conflicts:
        raise LedgerError(
            "修改内容与原始识别结果冲突，请确认是否覆盖",
            code="value_conflict",
            details={"conflicts": list(conflicts.values())},
        )

    before = {k: json_safe(getattr(draft, k)) for k in changes}
    for field, value in changes.items():
        setattr(draft, field, value)
        sources = dict(draft.field_sources or {})
        if value is None:
            sources.pop(field, None)
        else:
            sources[field] = "user"
        draft.field_sources = sources
        if value is not None:
            confidence = dict(draft.confidence or {})
            confidence["date" if field == "txn_date" else field] = 1.0
            draft.confidence = confidence

    await session.flush()
    await add_trace(
        session,
        draft.input_id,
        "draft.edited",
        "ok",
        "人工编辑草稿",
        {"draft_id": str(draft.id), "before": before, "after": {k: json_safe(v) for k, v in changes.items()}},
        draft_id=draft.id,
    )
    if input_item is not None:
        await ensure_clarification(session, input_item, draft)
        await recompute_input_status(session, input_item)
    draft.warnings = compute_warnings(draft)
    await session.commit()
    return draft


async def _close_open_clarifications(session: AsyncSession, draft_id: uuid.UUID, reason: str) -> int:
    rows = (
        await session.scalars(
            select(Clarification).where(
                Clarification.draft_id == draft_id, Clarification.status == "open"
            )
        )
    ).all()
    now = datetime.now(UTC)
    for row in rows:
        row.status = "cancelled"
        row.answer = {"action": "cancelled", "reason": reason}
        row.answered_at = now
    return len(rows)


async def confirm_draft(
    session: AsyncSession, draft_id: uuid.UUID, idempotency_key: str | None = None
) -> tuple[Bill, bool]:
    draft = await _get_draft(session, draft_id, lock=True)

    if idempotency_key:
        record = await session.get(IdempotencyKey, idempotency_key)
        if record is not None and record.scope == f"confirm:{draft_id}":
            existing = await session.scalar(select(Bill).where(Bill.draft_id == draft.id))
            if existing is not None:
                return existing, True

    existing = await session.scalar(select(Bill).where(Bill.draft_id == draft.id))
    if existing is not None:
        return existing, True

    if draft.status == "rejected":
        raise LedgerError("已拒绝的草稿不能入账", code="rejected")
    if draft.conflict:
        raise LedgerError("存在未解决的字段冲突，请先确认冲突值", code="conflict_pending")
    if draft.amount is None or draft.txn_date is None:
        raise LedgerError("关键字段（金额/日期）缺失，不能确认入账", code="missing_critical")
    if draft.amount < 0:
        raise LedgerError("金额不能为负数", code="invalid_amount")

    bill = Bill(
        draft_id=draft.id,
        input_id=draft.input_id,
        amount=draft.amount,
        currency=draft.currency or "CNY",
        txn_date=draft.txn_date,
        merchant=draft.merchant,
        category=draft.category,
        note=draft.note,
    )
    session.add(bill)
    draft.status = "confirmed"
    await _close_open_clarifications(session, draft.id, "草稿已确认入账")

    if idempotency_key:
        session.add(
            IdempotencyKey(
                key=idempotency_key,
                scope=f"confirm:{draft.id}",
                response={"draft_id": str(draft.id)},
            )
        )

    input_item = await session.get(Input, draft.input_id)
    await add_trace(
        session,
        draft.input_id,
        "draft.confirmed",
        "ok",
        f"确认入账：{draft.amount} 元",
        {
            "draft_id": str(draft.id),
            "amount": float(draft.amount),
            "txn_date": draft.txn_date.isoformat(),
            "merchant": draft.merchant,
        },
        draft_id=draft.id,
    )
    try:
        await session.flush()
        if input_item is not None:
            await recompute_input_status(session, input_item)
        await session.commit()
    except IntegrityError:
        # Concurrent confirm: another transaction already produced the bill.
        await session.rollback()
        bill = await session.scalar(select(Bill).where(Bill.draft_id == draft_id))
        if bill is None:
            raise LedgerError(
                "确认入账失败，请重试", status_code=500, code="confirm_failed"
            ) from None
        return bill, True

    await session.refresh(bill)
    return bill, False


async def reject_draft(session: AsyncSession, draft_id: uuid.UUID, reason: str | None = None) -> Draft:
    draft = await _get_draft(session, draft_id, lock=True)
    if draft.status == "confirmed":
        raise LedgerError("已入账的草稿不能拒绝", code="already_confirmed")
    if draft.status == "rejected":
        return draft
    draft.status = "rejected"
    await _close_open_clarifications(session, draft.id, "草稿已被拒绝")
    input_item = await session.get(Input, draft.input_id)
    await add_trace(
        session,
        draft.input_id,
        "draft.rejected",
        "ok",
        "人工拒绝草稿",
        {"draft_id": str(draft.id), "reason": reason},
        draft_id=draft.id,
    )
    if input_item is not None:
        await recompute_input_status(session, input_item)
    await session.commit()
    return draft


async def retry_datasource(
    session: AsyncSession, draft_id: uuid.UUID, source: str
) -> Draft:
    draft = await _get_draft(session, draft_id, lock=True)
    if source not in datasources.DUPLICATE_SOURCES:
        raise LedgerError("未知数据源", status_code=400, code="bad_source")
    input_item = await session.get(Input, draft.input_id)
    if input_item is None:
        raise LedgerError("输入不存在", status_code=404, code="not_found")

    outcome = await datasources.run_source(session, source, draft, input_item)
    draft.warnings = compute_warnings(draft)
    await add_trace(
        session,
        input_item.id,
        f"datasource.{source}",
        "retried" if outcome.status == "ok" else "failed",
        f"重试数据源 {source}：{outcome.status}",
        {
            "status": outcome.status,
            "error": outcome.error,
            "latency_ms": outcome.latency_ms,
            "result": outcome.result,
        },
        draft_id=draft.id,
    )
    await session.commit()
    return draft


async def retry_input(session: AsyncSession, input_id: uuid.UUID) -> Input:
    input_item = await session.get(Input, input_id, with_for_update=True)
    if input_item is None:
        raise LedgerError("输入不存在", status_code=404, code="not_found")
    if input_item.status in ("processing",):
        raise LedgerError("正在处理中，请稍候", code="processing")
    if input_item.status != "failed":
        raise LedgerError("仅失败的输入可以重试", code="not_failed")

    input_item.status = "pending"
    input_item.failure_step = None
    input_item.failure_reason = None
    session.add(Job(input_id=input_item.id, kind="process_input", status="queued"))
    await add_trace(
        session,
        input_item.id,
        "input.retry",
        "retried",
        "用户触发重试，从失败步骤继续",
        {"resume_from": input_item.extraction is not None},
    )
    await session.commit()
    return input_item


async def record_failure(session: AsyncSession, input_id: uuid.UUID, step: str, reason: str) -> None:
    input_item = await session.get(Input, input_id)
    if input_item is None:
        return
    input_item.status = "failed"
    input_item.failure_step = step
    input_item.failure_reason = reason
    input_item.updated_at = datetime.now(UTC)
    await add_trace(session, input_id, step, "failed", reason)
