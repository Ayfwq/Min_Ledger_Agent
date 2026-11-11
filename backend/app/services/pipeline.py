"""Processing pipeline: extraction → validation → clarification → data sources.

The pipeline is deliberately a deterministic state machine around the LLM:
the model only extracts, while validation / clarification / idempotency are
plain Python so they can be trusted and tested.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Clarification, Draft, Image, Input, TraceEvent
from app.services import datasources
from app.services.llm import ALLOWED_CATEGORIES, ExtractionResult, LLMError
from app.services.llm import client as llm_client
from app.services.parsing import parse_amount, parse_date

logger = logging.getLogger(__name__)

CRITICAL_FIELDS = ("amount", "txn_date")
FIELD_LABELS = {
    "amount": "金额",
    "txn_date": "消费日期",
    "merchant": "商户",
    "category": "类别",
}
FIELD_QUESTIONS = {
    "amount": "这笔消费的金额是多少？（例如：35.5）",
    "txn_date": "这笔消费发生在哪一天？（例如：2026-11-10，也可以说“昨天”）",
    "merchant": "这笔消费的商户或平台是什么？（不确定可以回复“不知道”）",
    "category": "这笔消费属于哪个类别？（餐饮/交通/购物/生活缴费/娱乐/医疗/教育/住房/旅行/通讯/其他）",
}
CATEGORY_SYNONYMS = {
    "吃饭": "餐饮",
    "外卖": "餐饮",
    "餐厅": "餐饮",
    "打车": "交通",
    "地铁": "交通",
    "公交": "交通",
    "超市": "购物",
    "网购": "购物",
    "水电": "生活缴费",
    "电费": "生活缴费",
    "水费": "生活缴费",
    "话费": "通讯",
    "电影": "娱乐",
    "看病": "医疗",
    "药": "医疗",
    "房租": "住房",
}

LOW_CONFIDENCE = 0.6


class PipelineError(RuntimeError):
    def __init__(self, step: str, message: str) -> None:
        super().__init__(message)
        self.step = step


def json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


async def add_trace(
    session: AsyncSession,
    input_id: uuid.UUID,
    step: str,
    status: str,
    message: str | None = None,
    payload: dict | None = None,
    draft_id: uuid.UUID | None = None,
    duration_ms: int | None = None,
) -> None:
    session.add(
        TraceEvent(
            input_id=input_id,
            draft_id=draft_id,
            step=step,
            status=status,
            message=message,
            payload=json_safe(payload) if payload else None,
            duration_ms=duration_ms,
        )
    )


# ------------------------------------------------------------------ extraction


async def _run_extraction(input_item: Input, image: Image | None) -> tuple[ExtractionResult, dict]:
    if input_item.kind in ("image", "mixed"):
        if image is None:
            raise PipelineError("extract", "图片记录缺失，无法识别")
        from pathlib import Path

        path = Path(settings.upload_path) / image.storage_path
        result, raw = await llm_client.extract_image(
            path,
            image.content_type,
            context_text=input_item.raw_text if input_item.kind == "mixed" else None,
        )
    else:
        result, raw = await llm_client.extract_text(input_item.raw_text or "")
    return result, raw


def _load_extraction(input_item: Input) -> ExtractionResult | None:
    if not input_item.extraction:
        return None
    payload = input_item.extraction
    if isinstance(payload, dict) and "result" in payload:
        payload = payload["result"]
    try:
        return ExtractionResult.model_validate(payload)
    except Exception:
        return None


# ------------------------------------------------------------------ drafts


def _is_user_field(draft: Draft, field: str) -> bool:
    return (draft.field_sources or {}).get(field) == "user"


def _set_field(draft: Draft, field: str, value: Any, source: str) -> None:
    setattr(draft, field, value)
    sources = dict(draft.field_sources or {})
    if value is None:
        sources.pop(field, None)
    else:
        sources[field] = source
    draft.field_sources = sources


async def _upsert_draft(
    session: AsyncSession, input_item: Input, seq: int
) -> tuple[Draft, bool]:
    draft = await session.scalar(
        select(Draft).where(Draft.input_id == input_item.id, Draft.seq == seq)
    )
    if draft is not None:
        return draft, False
    draft = Draft(
        input_id=input_item.id,
        seq=seq,
        status="drafting",
        field_sources={},
        confidence={},
        warnings=[],
        suggestions={},
        duplicate_candidates=[],
    )
    session.add(draft)
    await session.flush()
    return draft, True


_AMOUNT_VERB = re.compile(
    r"(?:实际|一共|总共|共|合计|花了|付了|支付了?|消费了?)\s*[^\d]{0,4}(\d+(?:\.\d{1,2})?)"
)
_AMOUNT_UNIT = re.compile(r"(\d+(?:\.\d{1,2})?)\s*(?:元|块|块钱)")
_DATE_ABS = re.compile(r"(20\d{2})[-/年.](\d{1,2})[-/月.](\d{1,2})")
_RELATIVE_DAYS = {"昨天": -1, "昨日": -1, "今天": 0, "今日": 0, "前天": -2, "大前天": -3}


def _flag_text_conflicts(draft: Draft, text: str, today: date) -> None:
    """For mixed inputs, compare numbers/dates in the text with the screenshot.

    The LLM is asked to flag conflicts, but small models often silently prefer
    the screenshot. This deterministic pass guarantees the "35.5 vs 40" case
    becomes an explicit conflict question.
    """
    if not text:
        return
    amounts = [
        Decimal(match.group(1))
        for pattern in (_AMOUNT_VERB, _AMOUNT_UNIT)
        for match in pattern.finditer(text)
    ]
    conflicts = dict(draft.conflict or {})
    if amounts and draft.amount is not None:
        proposed = amounts[-1]
        if abs(proposed - draft.amount) > Decimal("0.009"):
            conflicts.setdefault(
                "amount",
                {"existing": str(draft.amount), "proposed": str(proposed)},
            )

    parsed_date: date | None = None
    match = _DATE_ABS.search(text)
    if match:
        try:
            parsed_date = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            parsed_date = None
    if parsed_date is None:
        for word, delta in _RELATIVE_DAYS.items():
            if word in text:
                parsed_date = today + timedelta(days=delta)
                break
    if parsed_date is not None and draft.txn_date is not None and parsed_date != draft.txn_date:
        conflicts.setdefault(
            "txn_date",
            {"existing": str(draft.txn_date), "proposed": str(parsed_date)},
        )

    if conflicts:
        draft.conflict = conflicts


def _sync_from_extraction(draft: Draft, tx: Any, source: str, today: date) -> None:
    amount = None
    if tx.amount is not None:
        try:
            amount = Decimal(str(tx.amount)).quantize(Decimal("0.01"))
        except Exception:
            amount = None
    if amount is not None and amount >= 0:
        if not _is_user_field(draft, "amount"):
            _set_field(draft, "amount", amount, source)
    elif not _is_user_field(draft, "amount"):
        _set_field(draft, "amount", None, source)

    txn_date = parse_date(tx.date, today) if tx.date else None
    if not _is_user_field(draft, "txn_date"):
        _set_field(draft, "txn_date", txn_date, source)

    if tx.merchant and not _is_user_field(draft, "merchant"):
        _set_field(draft, "merchant", tx.merchant.strip()[:200], source)

    category = (tx.category or "").strip() or None
    if category and category not in ALLOWED_CATEGORIES:
        category = None
    if category and not _is_user_field(draft, "category"):
        _set_field(draft, "category", category, source)

    if tx.description and not draft.note:
        draft.note = tx.description.strip()[:1000]

    confidence = {}
    for key, value in (tx.confidence or {}).items():
        try:
            confidence[key] = round(float(value), 3)
        except (TypeError, ValueError):
            continue
    if not _is_user_field(draft, "amount") and amount is not None:
        confidence.setdefault("amount", 0.9)
    if not _is_user_field(draft, "txn_date") and txn_date is not None:
        confidence.setdefault("date", 0.8)
    draft.confidence = confidence

    ambiguous = [field for field in (tx.ambiguous_fields or []) if field in FIELD_LABELS]
    if ambiguous:
        suggestions = dict(draft.suggestions or {})
        suggestions["ambiguous_fields"] = ambiguous
        draft.suggestions = suggestions


def compute_warnings(draft: Draft) -> list[dict]:
    warnings: list[dict] = []
    for field in CRITICAL_FIELDS:
        if getattr(draft, field) is None:
            warnings.append(
                {
                    "code": "missing_critical",
                    "field": field,
                    "severity": "error",
                    "message": f"缺少关键字段：{FIELD_LABELS[field]}",
                }
            )
    for field in ("merchant", "category"):
        if getattr(draft, field) is None:
            warnings.append(
                {
                    "code": "missing_optional",
                    "field": field,
                    "severity": "warning",
                    "message": f"缺少{FIELD_LABELS[field]}，建议补充（不影响入账）",
                }
            )
    confidence = draft.confidence or {}
    for field, key in (
        ("amount", "amount"),
        ("txn_date", "date"),
        ("merchant", "merchant"),
        ("category", "category"),
    ):
        score = confidence.get(key)
        if getattr(draft, field) is not None and isinstance(score, (int, float)) and score < LOW_CONFIDENCE:
            warnings.append(
                {
                    "code": "low_confidence",
                    "field": field,
                    "severity": "warning",
                    "message": f"{FIELD_LABELS[field]}识别置信度较低（{score:.2f}），请核对",
                }
            )
    duplicates = draft.duplicate_candidates or []
    if duplicates:
        warnings.append(
            {
                "code": "duplicate_suspected",
                "severity": "warning",
                "message": f"发现 {len(duplicates)} 条疑似重复记录，请审核确认",
            }
        )
    errors = (draft.suggestions or {}).get("datasource_errors") or {}
    for source, message in errors.items():
        warnings.append(
            {
                "code": "datasource_failed",
                "field": source,
                "severity": "warning",
                "message": f"数据源 {source} 调用失败：{message}",
            }
        )
    if draft.conflict:
        for field in draft.conflict:
            warnings.append(
                {
                    "code": "conflict_pending",
                    "field": field,
                    "severity": "error",
                    "message": f"{FIELD_LABELS.get(field, field)}存在冲突，需确认后入账",
                }
            )
    return warnings


async def _asked_fields(session: AsyncSession, draft: Draft) -> dict[str, str]:
    rows = (
        await session.scalars(select(Clarification).where(Clarification.draft_id == draft.id))
    ).all()
    asked: dict[str, str] = {}
    for row in rows:
        # Keep the "strongest" status per field.
        if row.status == "open":
            asked[row.field] = "open"
        elif row.status in ("answered", "resolved", "unknown", "cancelled") and row.field not in asked:
            asked[row.field] = row.status
    return asked


async def ensure_clarification(
    session: AsyncSession, input_item: Input, draft: Draft, *, run_sources: bool = True
) -> None:
    if draft.status in ("confirmed", "rejected"):
        return

    asked = await _asked_fields(session, draft)
    has_open_blocking = any(
        status == "open"
        for field, status in asked.items()
        if field in CRITICAL_FIELDS or (draft.conflict and field in draft.conflict)
    )

    # 1) unresolved conflict -> blocking question, one at a time
    if draft.conflict and not has_open_blocking:
        field = next(iter(draft.conflict))
        info = draft.conflict[field]
        question = (
            f"系统识别这笔消费的{FIELD_LABELS.get(field, field)}为「{info.get('existing')}」，"
            f"你补充的是「{info.get('proposed')}」，请确认使用哪一个？"
        )
        session.add(
            Clarification(
                input_id=input_item.id,
                draft_id=draft.id,
                field=field,
                kind="conflict",
                status="open",
                blocking=True,
                question=question,
                reason="用户补充信息与原始识别结果冲突",
                options={
                    "existing": info.get("existing"),
                    "new": info.get("proposed"),
                    "existing_label": f"使用识别值 {info.get('existing')}",
                    "new_label": f"使用我补充的 {info.get('proposed')}",
                },
                round=len([f for f in asked if f == field]) + 1,
            )
        )
        has_open_blocking = True

    # 1.5) model-reported ambiguity (e.g. text contradicts the screenshot)
    if not has_open_blocking and not draft.conflict:
        ambiguous_fields = [
            field
            for field in (draft.suggestions or {}).get("ambiguous_fields", []) or []
            if field in FIELD_LABELS and getattr(draft, field) is not None and field not in asked
        ]
        ambiguous_fields.sort(key=lambda f: 0 if f in CRITICAL_FIELDS else 1)
        if ambiguous_fields:
            field = ambiguous_fields[0]
            value = getattr(draft, field)
            blocking = field in CRITICAL_FIELDS
            session.add(
                Clarification(
                    input_id=input_item.id,
                    draft_id=draft.id,
                    field=field,
                    kind="ambiguous",
                    status="open",
                    blocking=blocking,
                    question=(
                        f"系统识别到{ FIELD_LABELS[field] }为「{value}」，但存在歧义。"
                        "请确认是否正确；如不正确，请直接输入正确值。"
                    ),
                    reason="识别结果存在歧义，需要人工确认",
                    options={"existing": str(value), "confirm_word": "正确"},
                    round=1,
                )
            )
            asked[field] = "open"
            has_open_blocking = has_open_blocking or blocking

    # 2) missing critical fields -> blocking question, one at a time
    if not has_open_blocking and not draft.conflict:
        for field in CRITICAL_FIELDS:
            if getattr(draft, field) is not None:
                continue
            if asked.get(field) == "open":
                has_open_blocking = True
                break
            if asked.get(field) in ("unknown", "cancelled"):
                continue
            session.add(
                Clarification(
                    input_id=input_item.id,
                    draft_id=draft.id,
                    field=field,
                    kind="missing",
                    status="open",
                    blocking=True,
                    question=FIELD_QUESTIONS[field],
                    reason=f"缺少关键字段：{FIELD_LABELS[field]}，无法生成可确认的草稿",
                    round=1,
                )
            )
            has_open_blocking = True
            break

    # 3) non-critical fields -> non-blocking questions (missing or ambiguous)
    if all(getattr(draft, field) is not None for field in CRITICAL_FIELDS):
        for field in ("merchant", "category"):
            value = getattr(draft, field)
            if value is not None:
                if field != "merchant" or field in asked:
                    continue
                score = (draft.confidence or {}).get("merchant")
                source = (draft.field_sources or {}).get("merchant")
                if source == "user" or not isinstance(score, (int, float)) or score >= LOW_CONFIDENCE:
                    continue
                # Ambiguous: the screenshot/text gave a low-confidence merchant.
                session.add(
                    Clarification(
                        input_id=input_item.id,
                        draft_id=draft.id,
                        field="merchant",
                        kind="ambiguous",
                        status="open",
                        blocking=False,
                        question=(
                            f"系统识别到的商户是「{value}」，是否准确？"
                            "如不准确请直接输入正确的商户名称；回复「正确」表示确认。"
                        ),
                        reason=f"商户识别置信度较低（{float(score):.2f}），需要确认",
                        options={"existing": str(value), "confirm_word": "正确"},
                        round=1,
                    )
                )
                break
            if field in asked:
                continue
            session.add(
                Clarification(
                    input_id=input_item.id,
                    draft_id=draft.id,
                    field=field,
                    kind="missing",
                    status="open",
                    blocking=False,
                    question=FIELD_QUESTIONS[field],
                    reason=f"{FIELD_LABELS[field]}缺失，可补充也可跳过",
                    round=1,
                )
            )
            break

    # 4) data sources run as soon as the draft is complete enough
    ready = all(getattr(draft, field) is not None for field in CRITICAL_FIELDS) and not draft.conflict
    if ready and run_sources:
        suggestions = draft.suggestions or {}
        already = "duplicate" in suggestions or "duplicate_check" in (suggestions.get("datasource_errors") or {})
        if not already:
            await datasources.run_all(session, draft, input_item)

    recompute_draft_status(draft, has_blocking=has_open_blocking)
    draft.warnings = compute_warnings(draft)


def recompute_draft_status(draft: Draft, *, has_blocking: bool = False) -> None:
    if draft.status in ("confirmed", "rejected"):
        return
    if draft.conflict:
        draft.status = "needs_clarification"
    elif has_blocking:
        draft.status = "needs_clarification"
    elif any(getattr(draft, field) is None for field in CRITICAL_FIELDS):
        draft.status = "needs_clarification"
    else:
        draft.status = "ready_for_review"


async def recompute_input_status(session: AsyncSession, input_item: Input) -> None:
    drafts = (
        await session.scalars(select(Draft).where(Draft.input_id == input_item.id))
    ).all()
    if not drafts:
        if input_item.status not in ("failed", "processing"):
            input_item.status = "failed"
            input_item.failure_reason = input_item.failure_reason or "没有生成任何草稿"
        return
    statuses = [d.status for d in drafts]
    if any(s == "needs_clarification" for s in statuses):
        input_item.status = "needs_clarification"
    elif all(s == "confirmed" for s in statuses):
        input_item.status = "confirmed"
    elif all(s == "rejected" for s in statuses):
        input_item.status = "rejected"
    else:
        input_item.status = "ready_for_review"


# ------------------------------------------------------------------ main flow


async def build_drafts(session: AsyncSession, input_item: Input) -> list[Draft]:
    extraction = _load_extraction(input_item)
    if extraction is None:
        raise PipelineError("extract", "抽取结果缺失，请重试")
    if not extraction.transactions:
        raise PipelineError("extract", "未能从输入中识别出任何账单，请补充描述或更换更清晰的截图")

    source = "image" if input_item.kind in ("image", "mixed") else "text"
    today = datetime.now().date()
    drafts: list[Draft] = []
    for seq, tx in enumerate(extraction.transactions):
        draft, created = await _upsert_draft(session, input_item, seq)
        if draft.status in ("confirmed", "rejected"):
            drafts.append(draft)
            continue
        _sync_from_extraction(draft, tx, source, today)
        if input_item.kind == "mixed" and input_item.raw_text:
            _flag_text_conflicts(draft, input_item.raw_text, today)
        await session.flush()
        await ensure_clarification(session, input_item, draft)
        drafts.append(draft)
        if created:
            await add_trace(
                session,
                input_item.id,
                "draft.created",
                "ok",
                f"生成第 {seq + 1} 笔草稿",
                {"draft_id": str(draft.id), "status": draft.status},
                draft_id=draft.id,
            )
    return drafts


async def process_input(session: AsyncSession, input_id: uuid.UUID) -> None:
    input_item = await session.get(Input, input_id, with_for_update=True)
    if input_item is None:
        return
    if input_item.status == "confirmed":
        return

    input_item.status = "processing"
    input_item.failure_step = None
    input_item.failure_reason = None
    await session.flush()

    image = None
    if input_item.image_id:
        image = await session.get(Image, input_item.image_id)

    # ---- step 1: extraction (skipped when resuming a failed run)
    if input_item.extraction is None:
        started = time.perf_counter()
        try:
            result, raw = await _run_extraction(input_item, image)
        except LLMError as exc:
            input_item.status = "failed"
            input_item.failure_step = "extract"
            input_item.failure_reason = str(exc)
            await add_trace(
                session,
                input_item.id,
                "extract",
                "failed",
                str(exc),
                {"detail": exc.detail},
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            await session.commit()
            raise PipelineError("extract", str(exc)) from exc
        except PipelineError as exc:
            input_item.status = "failed"
            input_item.failure_step = exc.step
            input_item.failure_reason = str(exc)
            await add_trace(session, input_item.id, "extract", "failed", str(exc))
            await session.commit()
            raise

        input_item.extraction = {
            "result": result.model_dump(),
            "warnings": result.warnings,
            "raw": raw,
            "model": settings.llm_vision_model
            if input_item.kind == "image"
            else settings.llm_text_model,
        }
        input_item.extracted_at = datetime.now(UTC)
        await add_trace(
            session,
            input_item.id,
            "extract",
            "ok",
            f"识别到 {len(result.transactions)} 笔消费",
            {
                "transaction_count": len(result.transactions),
                "warnings": result.warnings,
                "model": input_item.extraction["model"],
            },
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        await session.flush()
    else:
        await add_trace(session, input_item.id, "extract", "ok", "复用已完成的识别结果")

    # ---- step 2: drafts + clarification + data sources
    started = time.perf_counter()
    try:
        drafts = await build_drafts(session, input_item)
    except PipelineError as exc:
        input_item.status = "failed"
        input_item.failure_step = exc.step
        input_item.failure_reason = str(exc)
        await add_trace(session, input_item.id, "build_drafts", "failed", str(exc))
        await session.commit()
        raise
    await add_trace(
        session,
        input_item.id,
        "build_drafts",
        "ok",
        f"生成/更新 {len(drafts)} 笔草稿",
        {"drafts": [{"id": str(d.id), "status": d.status, "seq": d.seq} for d in drafts]},
        duration_ms=int((time.perf_counter() - started) * 1000),
    )

    await recompute_input_status(session, input_item)
    await add_trace(
        session,
        input_item.id,
        "pipeline.done",
        "ok",
        f"处理完成，状态：{input_item.status}",
        {"status": input_item.status},
    )
    await session.commit()


# ------------------------------------------------------------------ clarification


def parse_field_value(field: str, raw: str | None) -> Any:
    if raw is None or not raw.strip():
        raise ValueError("回答内容不能为空")
    if field == "amount":
        value = parse_amount(raw)
        if value is None:
            raise ValueError("无法识别金额，请输入数字，例如 35.5")
        return value
    if field == "txn_date":
        value = parse_date(raw)
        if value is None:
            raise ValueError("无法识别日期，请输入如 2026-11-10 或“昨天”")
        return value
    if field == "category":
        text = raw.strip()
        if text in ALLOWED_CATEGORIES:
            return text
        if text in CATEGORY_SYNONYMS:
            return CATEGORY_SYNONYMS[text]
        raise ValueError(f"类别需为：{'、'.join(ALLOWED_CATEGORIES)}")
    if field == "merchant":
        return raw.strip()[:200]
    raise ValueError(f"不支持澄清字段: {field}")


def apply_field_value(draft: Draft, field: str, value: Any, source: str = "user") -> None:
    _set_field(draft, field, value, source)
    confidence = dict(draft.confidence or {})
    if field == "txn_date":
        confidence["date"] = 1.0
    else:
        confidence[field] = 1.0
    draft.confidence = confidence
    draft.warnings = compute_warnings(draft)


def _values_differ(field: str, existing: Any, proposed: Any) -> bool:
    if existing is None:
        return False
    if field == "txn_date":
        return str(existing) != str(proposed)
    if field == "amount":
        try:
            return Decimal(str(existing)) != Decimal(str(proposed))
        except Exception:
            return True
    return str(existing).strip() != str(proposed).strip()


async def answer_clarification(
    session: AsyncSession,
    clarification: Clarification,
    *,
    action: str,
    value: str | None,
    choice: str | None,
) -> Clarification:
    if clarification.status != "open":
        raise ValueError("该澄清已处理，不能重复回答")

    draft = await session.get(Draft, clarification.draft_id, with_for_update=True)
    input_item = await session.get(Input, clarification.input_id, with_for_update=True)
    if draft is None or input_item is None:
        raise ValueError("关联的草稿不存在")

    now = datetime.now(UTC)
    started = time.perf_counter()
    confirm_words = {"正确", "是", "对", "准确", "确认", "没错", "是的", "确认正确"}

    if (
        clarification.kind == "ambiguous"
        and action == "answer"
        and value is not None
        and value.strip() in confirm_words
    ):
        confidence = dict(draft.confidence or {})
        confidence["date" if clarification.field == "txn_date" else clarification.field] = 1.0
        draft.confidence = confidence
        clarification.status = "resolved"
        clarification.answer = {
            "action": "confirm",
            "value": str(getattr(draft, clarification.field)),
        }
        clarification.answered_at = now
        await add_trace(
            session,
            input_item.id,
            "clarification.confirmed",
            "ok",
            f"用户确认{FIELD_LABELS.get(clarification.field, clarification.field)}识别正确",
            {"field": clarification.field, "value": str(getattr(draft, clarification.field))},
            draft_id=draft.id,
        )
    elif action == "unknown":
        clarification.status = "unknown"
        clarification.answer = {"action": "unknown"}
        clarification.answered_at = now
        await add_trace(
            session,
            input_item.id,
            "clarification.unknown",
            "ok",
            f"用户暂不提供{FIELD_LABELS.get(clarification.field, clarification.field)}",
            {"field": clarification.field},
            draft_id=draft.id,
        )
    elif clarification.kind == "conflict" and action == "choose":
        info = clarification.options or {}
        chosen = choice or "new"
        raw_value = info.get("new") if chosen == "new" else info.get("existing")
        value_typed = parse_field_value(clarification.field, str(raw_value))
        apply_field_value(draft, clarification.field, value_typed, "user" if chosen == "new" else "text")
        draft.conflict = None
        clarification.status = "resolved"
        clarification.answer = {"action": "choose", "choice": chosen, "value": str(raw_value)}
        clarification.answered_at = now
        await add_trace(
            session,
            input_item.id,
            "clarification.conflict_resolved",
            "ok",
            f"冲突已解决：{FIELD_LABELS.get(clarification.field, clarification.field)}使用 {raw_value}",
            {"field": clarification.field, "choice": chosen, "value": str(raw_value)},
            draft_id=draft.id,
        )
    else:
        if action == "choose":
            raise ValueError("该澄清不是冲突确认，无法使用 choose")
        parsed = parse_field_value(clarification.field, value)
        existing = getattr(draft, clarification.field)
        source = (draft.field_sources or {}).get(clarification.field)
        if _values_differ(clarification.field, existing, parsed) and source != "user":
            draft.conflict = {
                clarification.field: {
                    "existing": str(existing),
                    "proposed": str(parsed),
                }
            }
            clarification.status = "answered"
            clarification.answer = {"action": "answer", "value": str(parsed), "conflict": True}
            clarification.answered_at = now
            await add_trace(
                session,
                input_item.id,
                "clarification.conflict_raised",
                "ok",
                "用户补充与识别结果冲突，等待确认",
                {"field": clarification.field, "existing": str(existing), "proposed": str(parsed)},
                draft_id=draft.id,
            )
        else:
            apply_field_value(draft, clarification.field, parsed, "user")
            clarification.status = "answered"
            clarification.answer = {"action": "answer", "value": str(parsed)}
            clarification.answered_at = now
            await add_trace(
                session,
                input_item.id,
                "clarification.answered",
                "ok",
                f"用户补充{FIELD_LABELS.get(clarification.field, clarification.field)}：{parsed}",
                {"field": clarification.field, "value": str(parsed)},
                draft_id=draft.id,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )

    await session.flush()
    await ensure_clarification(session, input_item, draft)
    await recompute_input_status(session, input_item)
    await session.commit()
    return clarification


async def cancel_clarification(
    session: AsyncSession, clarification: Clarification, reason: str | None = None
) -> Clarification:
    if clarification.status != "open":
        raise ValueError("该澄清已处理")
    clarification.status = "cancelled"
    clarification.answer = {"action": "cancel", "reason": reason}
    clarification.answered_at = datetime.now(UTC)
    draft = await session.get(Draft, clarification.draft_id) if clarification.draft_id else None
    input_item = await session.get(Input, clarification.input_id)
    if input_item:
        await add_trace(
            session,
            input_item.id,
            "clarification.cancelled",
            "ok",
            "澄清已取消",
            {"field": clarification.field, "reason": reason},
            draft_id=draft.id if draft else None,
        )
    if draft and input_item:
        recompute_draft_status(draft)
        draft.warnings = compute_warnings(draft)
        await recompute_input_status(session, input_item)
    await session.commit()
    return clarification
