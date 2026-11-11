"""Two independent business data sources.

1. duplicate_check   – look for suspicious duplicate bills/drafts.
2. merchant_catalog  – standardize merchant name and suggest a category.

Both are plain database queries (no "return everything" endpoint), and both are
called independently so one failing never blocks the other.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Bill, DataSourceCall, Draft, Input, Merchant
from app.services.parsing import merchant_similarity, normalize_merchant

logger = logging.getLogger(__name__)

DUPLICATE_SOURCES = ("duplicate_check", "merchant_catalog")
WINDOW_DAYS = 3
MIN_CANDIDATE_SCORE = 0.6


@dataclass
class SourceOutcome:
    source: str
    status: str  # ok | failed | skipped
    request: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    latency_ms: int = 0


def _reason(amount_same: bool, days: int, similarity: float) -> str:
    parts = []
    if amount_same:
        parts.append("金额一致")
    if days == 0:
        parts.append("同一天")
    else:
        parts.append(f"日期相差 {days} 天")
    if similarity >= 0.9:
        parts.append("商户高度相似")
    elif similarity >= 0.6:
        parts.append("商户部分相似")
    else:
        parts.append("商户不同")
    return "、".join(parts)


async def check_duplicates(session: AsyncSession, draft: Draft) -> SourceOutcome:
    started = time.perf_counter()
    if draft.amount is None or draft.txn_date is None:
        return SourceOutcome(
            source="duplicate_check",
            status="skipped",
            request={},
            error="金额或日期缺失，暂无法查重",
        )

    request = {
        "amount": float(draft.amount),
        "txn_date": draft.txn_date.isoformat(),
        "merchant": draft.merchant,
        "window_days": WINDOW_DAYS,
    }
    start_date = draft.txn_date - timedelta(days=WINDOW_DAYS)
    end_date = draft.txn_date + timedelta(days=WINDOW_DAYS)
    amount_tolerance = Decimal("0.01")

    try:
        bill_rows = (
            await session.scalars(
                select(Bill).where(
                    func.abs(Bill.amount - draft.amount) <= amount_tolerance,
                    Bill.txn_date.between(start_date, end_date),
                    Bill.input_id != draft.input_id,
                )
            )
        ).all()
        draft_rows = (
            await session.scalars(
                select(Draft).where(
                    func.abs(Draft.amount - draft.amount) <= amount_tolerance,
                    Draft.txn_date.between(start_date, end_date),
                    Draft.id != draft.id,
                    Draft.input_id != draft.input_id,
                    Draft.status.in_(["ready_for_review", "needs_clarification", "confirmed"]),
                )
            )
        ).all()

        candidates: list[dict[str, Any]] = []
        for bill in bill_rows:
            sim = merchant_similarity(draft.merchant, bill.merchant)
            days = abs((bill.txn_date - draft.txn_date).days)
            score = round(0.55 + 0.3 * sim + (0.15 if days == 0 else 0.08), 3)
            if score >= MIN_CANDIDATE_SCORE:
                candidates.append(
                    {
                        "kind": "bill",
                        "id": str(bill.id),
                        "amount": float(bill.amount),
                        "txn_date": bill.txn_date.isoformat(),
                        "merchant": bill.merchant,
                        "score": score,
                        "reason": _reason(True, days, sim),
                    }
                )
        for other in draft_rows:
            if other.txn_date is None:
                continue
            sim = merchant_similarity(draft.merchant, other.merchant)
            days = abs((other.txn_date - draft.txn_date).days)
            score = round(0.5 + 0.3 * sim + (0.15 if days == 0 else 0.08), 3)
            if score >= MIN_CANDIDATE_SCORE:
                candidates.append(
                    {
                        "kind": "draft",
                        "id": str(other.id),
                        "amount": float(other.amount or 0),
                        "txn_date": other.txn_date.isoformat(),
                        "merchant": other.merchant,
                        "score": score,
                        "reason": _reason(True, days, sim),
                    }
                )

        candidates.sort(key=lambda c: c["score"], reverse=True)
        result = {"candidates": candidates[:5], "checked_window_days": WINDOW_DAYS}
        return SourceOutcome(
            source="duplicate_check",
            status="ok",
            request=request,
            result=result,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("duplicate_check failed: %s", exc)
        return SourceOutcome(
            source="duplicate_check",
            status="failed",
            request=request,
            error=f"查重数据源调用失败: {exc}",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


async def lookup_merchant(session: AsyncSession, draft: Draft) -> SourceOutcome:
    started = time.perf_counter()
    if not draft.merchant:
        return SourceOutcome(
            source="merchant_catalog",
            status="skipped",
            request={},
            error="缺少商户名称，暂无法标准化",
        )

    query = normalize_merchant(draft.merchant)
    request = {"merchant": draft.merchant, "normalized": query}
    try:
        rows = (
            await session.scalars(
                select(Merchant)
                .where(
                    or_(
                        Merchant.normalized == query,
                        Merchant.normalized.contains(query),
                        Merchant.aliases.ilike(f"%{query}%"),
                        func.lower(Merchant.name).contains(query),
                    )
                )
                .limit(20)
            )
        ).all()

        # Fallback: widen the candidate set and score with fuzzy matching.
        seen = {m.id for m in rows}
        if len(rows) < 3:
            wider = (await session.scalars(select(Merchant).limit(300))).all()
            for merchant in wider:
                if merchant.id in seen:
                    continue
                aliases = [normalize_merchant(a) for a in (merchant.aliases or "").split(",") if a.strip()]
                best = max(
                    [merchant_similarity(query, merchant.normalized), merchant_similarity(query, merchant.name)]
                    + [merchant_similarity(query, a) for a in aliases]
                )
                if best >= 0.6:
                    rows.append(merchant)

        candidates: list[dict[str, Any]] = []
        for merchant in rows:
            aliases = [normalize_merchant(a) for a in (merchant.aliases or "").split(",") if a.strip()]
            if merchant.normalized == query:
                score = 1.0
            elif query in aliases:
                score = 0.95
            elif query and (query in merchant.normalized or merchant.normalized in query):
                score = 0.85
            else:
                score = merchant_similarity(query, merchant.normalized)
            alias_best = max((merchant_similarity(query, a) for a in aliases), default=0.0)
            score = max(score, min(alias_best, 0.93))
            if score < 0.6:
                continue
            candidates.append(
                {
                    "id": str(merchant.id),
                    "name": merchant.name,
                    "category": merchant.category,
                    "score": round(score, 3),
                    "confidence": round(float(merchant.confidence) * score, 3),
                }
            )
        candidates.sort(key=lambda c: c["score"], reverse=True)
        best = candidates[0] if candidates else None
        result = {
            "matched": best is not None,
            "merchant": best,
            "candidates": candidates[:5],
        }
        return SourceOutcome(
            source="merchant_catalog",
            status="ok",
            request=request,
            result=result,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("merchant_catalog failed: %s", exc)
        return SourceOutcome(
            source="merchant_catalog",
            status="failed",
            request=request,
            error=f"商户目录数据源调用失败: {exc}",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


async def run_source(
    session: AsyncSession, source: str, draft: Draft, input_item: Input
) -> SourceOutcome:
    if source == "duplicate_check":
        outcome = await check_duplicates(session, draft)
    elif source == "merchant_catalog":
        outcome = await lookup_merchant(session, draft)
    else:
        raise ValueError(f"未知数据源: {source}")

    if outcome.status != "skipped":
        call = DataSourceCall(
            input_id=input_item.id,
            draft_id=draft.id,
            source=outcome.source,
            status=outcome.status,
            request=outcome.request,
            result=outcome.result,
            error=outcome.error,
            latency_ms=outcome.latency_ms,
        )
        session.add(call)
    apply_outcome(draft, outcome)
    return outcome


async def run_all(session: AsyncSession, draft: Draft, input_item: Input) -> list[SourceOutcome]:
    outcomes = []
    for source in DUPLICATE_SOURCES:
        outcomes.append(await run_source(session, source, draft, input_item))
    return outcomes


def apply_outcome(draft: Draft, outcome: SourceOutcome) -> None:
    suggestions = dict(draft.suggestions or {})
    errors = dict(suggestions.get("datasource_errors") or {})

    if outcome.source == "duplicate_check":
        if outcome.status == "ok":
            draft.duplicate_candidates = outcome.result.get("candidates", [])
            suggestions["duplicate"] = {
                "count": len(outcome.result.get("candidates", [])),
                "checked_window_days": outcome.result.get("checked_window_days"),
            }
            errors.pop("duplicate_check", None)
        elif outcome.status == "failed":
            errors["duplicate_check"] = outcome.error
    elif outcome.source == "merchant_catalog":
        if outcome.status == "ok":
            suggestions["merchant"] = outcome.result
            errors.pop("merchant_catalog", None)
        elif outcome.status == "failed":
            errors["merchant_catalog"] = outcome.error

    if errors:
        suggestions["datasource_errors"] = errors
    else:
        suggestions.pop("datasource_errors", None)
    draft.suggestions = suggestions
