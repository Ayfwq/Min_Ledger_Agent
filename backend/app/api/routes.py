from __future__ import annotations

import hashlib
import io
import uuid

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile
from PIL import Image as PILImage
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.session import get_session
from app.models import (
    Bill,
    Clarification,
    DataSourceCall,
    Draft,
    Image,
    Input,
    Merchant,
    TraceEvent,
)
from app.schemas import (
    AuthVerify,
    BillOut,
    ClarificationAnswer,
    ClarificationOut,
    ConfirmResult,
    DataSourceCallOut,
    DraftOut,
    DraftUpdate,
    HealthOut,
    ImageOut,
    InputDetail,
    InputListItem,
    MerchantOut,
    TextInputCreate,
    TraceEventOut,
)
from app.services import ledger
from app.services.ledger import LedgerError
from app.services.pipeline import add_trace, answer_clarification, cancel_clarification
from app.services.worker import enqueue_job

router = APIRouter()

ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}


# ------------------------------------------------------------------ helpers


def _image_out(image: Image | None) -> ImageOut | None:
    if image is None:
        return None
    return ImageOut(
        id=image.id,
        filename=image.filename,
        content_type=image.content_type,
        size_bytes=image.size_bytes,
        width=image.width,
        height=image.height,
        url=f"/uploads/{image.storage_path}",
    )


def _draft_out(draft: Draft, *, bill_id: uuid.UUID | None = None, input_item: Input | None = None) -> DraftOut:
    out = DraftOut.model_validate(draft)
    return out.model_copy(
        update={
            "bill_id": bill_id,
            "input_kind": input_item.kind if input_item else None,
            "input_text": input_item.raw_text if input_item else None,
        }
    )


async def _bill_map(session: AsyncSession, draft_ids: list[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
    if not draft_ids:
        return {}
    rows = await session.execute(select(Bill.draft_id, Bill.id).where(Bill.draft_id.in_(draft_ids)))
    return {row[0]: row[1] for row in rows}


async def _load_input(session: AsyncSession, input_id: uuid.UUID) -> Input:
    input_item = await session.scalar(
        select(Input)
        .where(Input.id == input_id)
        .options(selectinload(Input.image), selectinload(Input.drafts))
    )
    if input_item is None:
        raise HTTPException(status_code=404, detail="输入不存在")
    return input_item


async def _input_detail(session: AsyncSession, input_id: uuid.UUID) -> InputDetail:
    input_item = await _load_input(session, input_id)
    drafts = sorted(input_item.drafts, key=lambda d: d.seq)
    bills = await _bill_map(session, [d.id for d in drafts])
    clarifications = (
        await session.scalars(
            select(Clarification)
            .where(Clarification.input_id == input_id)
            .order_by(Clarification.created_at)
        )
    ).all()
    traces = (
        await session.scalars(
            select(TraceEvent)
            .where(TraceEvent.input_id == input_id)
            .order_by(TraceEvent.created_at, TraceEvent.id)
        )
    ).all()
    calls = (
        await session.scalars(
            select(DataSourceCall)
            .where(DataSourceCall.input_id == input_id)
            .order_by(DataSourceCall.created_at.desc())
        )
    ).all()

    return InputDetail(
        id=input_item.id,
        kind=input_item.kind,
        raw_text=input_item.raw_text,
        status=input_item.status,
        failure_step=input_item.failure_step,
        failure_reason=input_item.failure_reason,
        image=_image_out(input_item.image),
        draft_count=len(drafts),
        open_clarifications=sum(1 for c in clarifications if c.status == "open"),
        created_at=input_item.created_at,
        updated_at=input_item.updated_at,
        drafts=[_draft_out(d, bill_id=bills.get(d.id), input_item=input_item) for d in drafts],
        clarifications=[ClarificationOut.model_validate(c) for c in clarifications],
        trace_events=[TraceEventOut.model_validate(t) for t in traces],
        datasource_calls=[DataSourceCallOut.model_validate(c) for c in calls],
    )


async def _input_list_item(session: AsyncSession, input_item: Input) -> InputListItem:
    draft_count = await session.scalar(
        select(func.count()).select_from(Draft).where(Draft.input_id == input_item.id)
    )
    open_count = await session.scalar(
        select(func.count())
        .select_from(Clarification)
        .where(Clarification.input_id == input_item.id, Clarification.status == "open")
    )
    latest_question = await session.scalar(
        select(Clarification.question)
        .where(Clarification.input_id == input_item.id, Clarification.status == "open")
        .order_by(Clarification.blocking.desc(), Clarification.created_at)
        .limit(1)
    )
    return InputListItem(
        id=input_item.id,
        kind=input_item.kind,
        raw_text=input_item.raw_text,
        status=input_item.status,
        failure_step=input_item.failure_step,
        failure_reason=input_item.failure_reason,
        image=_image_out(input_item.image),
        draft_count=draft_count or 0,
        open_clarifications=open_count or 0,
        latest_clarification=latest_question,
        created_at=input_item.created_at,
        updated_at=input_item.updated_at,
    )


def _raise_ledger(exc: LedgerError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"message": str(exc), "code": exc.code, **exc.details},
    )


# ------------------------------------------------------------------ auth


@router.post("/auth/verify")
async def verify_password(body: AuthVerify) -> dict[str, bool]:
    if not settings.app_password or body.password == settings.app_password:
        return {"ok": True}
    raise HTTPException(status_code=401, detail="密码错误")


# ------------------------------------------------------------------ inputs


async def _create_text_input(session: AsyncSession, text: str) -> Input:
    input_item = Input(kind="text", raw_text=text.strip(), status="pending")
    session.add(input_item)
    await session.flush()
    await add_trace(
        session,
        input_item.id,
        "input.created",
        "ok",
        "创建文本输入",
        {"chars": len(text)},
    )
    await enqueue_job(session, input_item.id)
    await session.commit()
    return input_item


@router.post("/inputs", response_model=InputDetail, status_code=201)
async def create_text_input(
    body: TextInputCreate, session: AsyncSession = Depends(get_session)
) -> InputDetail:
    input_item = await _create_text_input(session, body.text)
    return await _input_detail(session, input_item.id)


@router.post("/inputs/upload", response_model=InputDetail, status_code=201)
async def upload_input(
    file: UploadFile | None = File(default=None),
    text: str = Form(default=""),
    session: AsyncSession = Depends(get_session),
) -> InputDetail:
    text = (text or "").strip()
    if len(text) > 4000:
        raise HTTPException(status_code=400, detail="文字描述不能超过 4000 字")

    # Text-only submission through the unified composer.
    if file is None:
        if not text:
            raise HTTPException(status_code=400, detail="请提供文字描述或上传截图")
        input_item = await _create_text_input(session, text)
        return await _input_detail(session, input_item.id)

    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="仅支持 PNG/JPEG/WebP 图片")
    raw = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(raw) > max_bytes:
        raise HTTPException(status_code=400, detail=f"图片不能超过 {settings.max_upload_mb}MB")
    if not raw:
        raise HTTPException(status_code=400, detail="上传文件为空")

    try:
        probe = PILImage.open(io.BytesIO(raw))
        probe.verify()
        probe = PILImage.open(io.BytesIO(raw))
        width, height = probe.size
    except Exception:
        raise HTTPException(status_code=400, detail="图片文件损坏或格式不支持") from None

    digest = hashlib.sha256(raw).hexdigest()
    image = await session.scalar(select(Image).where(Image.sha256 == digest))
    if image is None:
        suffix = {"image/png": ".png", "image/webp": ".webp"}.get(content_type, ".jpg")
        storage_name = f"{digest[:24]}{suffix}"
        target = settings.upload_path / storage_name
        target.write_bytes(raw)
        image = Image(
            filename=file.filename or storage_name,
            content_type=content_type,
            size_bytes=len(raw),
            sha256=digest,
            storage_path=storage_name,
            width=width,
            height=height,
        )
        session.add(image)
        await session.flush()

    kind = "mixed" if text else "image"
    input_item = Input(
        kind=kind,
        image_id=image.id,
        raw_text=text or None,
        status="pending",
    )
    session.add(input_item)
    await session.flush()
    await add_trace(
        session,
        input_item.id,
        "input.created",
        "ok",
        "上传截图并附加文字" if text else "上传截图",
        {
            "filename": image.filename,
            "size_bytes": image.size_bytes,
            "text_chars": len(text),
        },
    )
    await enqueue_job(session, input_item.id)
    await session.commit()
    return await _input_detail(session, input_item.id)


@router.get("/inputs", response_model=list[InputListItem])
async def list_inputs(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[InputListItem]:
    stmt = select(Input).options(selectinload(Input.image)).order_by(Input.created_at.desc())
    if status:
        stmt = stmt.where(Input.status == status)
    rows = (await session.scalars(stmt.limit(limit).offset(offset))).all()
    return [await _input_list_item(session, row) for row in rows]


@router.get("/inputs/{input_id}", response_model=InputDetail)
async def get_input(input_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> InputDetail:
    return await _input_detail(session, input_id)


@router.post("/inputs/{input_id}/retry", response_model=InputDetail)
async def retry_input(input_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> InputDetail:
    try:
        await ledger.retry_input(session, input_id)
    except LedgerError as exc:
        _raise_ledger(exc)
    return await _input_detail(session, input_id)


# ------------------------------------------------------------------ clarifications


@router.post("/clarifications/{clarification_id}/answer", response_model=ClarificationOut)
async def answer(
    clarification_id: uuid.UUID,
    body: ClarificationAnswer,
    session: AsyncSession = Depends(get_session),
) -> ClarificationOut:
    clarification = await session.get(Clarification, clarification_id)
    if clarification is None:
        raise HTTPException(status_code=404, detail="澄清不存在")
    try:
        await answer_clarification(
            session, clarification, action=body.action, value=body.value, choice=body.choice
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.refresh(clarification)
    return ClarificationOut.model_validate(clarification)


@router.post("/clarifications/{clarification_id}/cancel", response_model=ClarificationOut)
async def cancel(
    clarification_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> ClarificationOut:
    clarification = await session.get(Clarification, clarification_id)
    if clarification is None:
        raise HTTPException(status_code=404, detail="澄清不存在")
    try:
        await cancel_clarification(session, clarification)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.refresh(clarification)
    return ClarificationOut.model_validate(clarification)


# ------------------------------------------------------------------ drafts


@router.get("/drafts", response_model=list[DraftOut])
async def list_drafts(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=300),
    session: AsyncSession = Depends(get_session),
) -> list[DraftOut]:
    stmt = (
        select(Draft)
        .options(selectinload(Draft.input_item).selectinload(Input.image))
        .order_by(Draft.created_at.desc())
        .limit(limit)
    )
    if status:
        stmt = stmt.where(Draft.status == status)
    drafts = (await session.scalars(stmt)).all()
    bills = await _bill_map(session, [d.id for d in drafts])
    return [
        _draft_out(d, bill_id=bills.get(d.id), input_item=d.input_item) for d in drafts
    ]


@router.get("/drafts/{draft_id}", response_model=DraftOut)
async def get_draft(draft_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> DraftOut:
    draft = await session.get(Draft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="草稿不存在")
    input_item = await session.get(Input, draft.input_id)
    bills = await _bill_map(session, [draft.id])
    return _draft_out(draft, bill_id=bills.get(draft.id), input_item=input_item)


@router.patch("/drafts/{draft_id}", response_model=DraftOut)
async def patch_draft(
    draft_id: uuid.UUID, body: DraftUpdate, session: AsyncSession = Depends(get_session)
) -> DraftOut:
    changes = body.model_dump(exclude_unset=True)
    force = bool(changes.pop("force", False))
    if not changes:
        raise HTTPException(status_code=400, detail="没有需要更新的字段")
    try:
        draft = await ledger.update_draft(session, draft_id, changes, force=force)
    except LedgerError as exc:
        _raise_ledger(exc)
    input_item = await session.get(Input, draft.input_id)
    bills = await _bill_map(session, [draft.id])
    return _draft_out(draft, bill_id=bills.get(draft.id), input_item=input_item)


@router.post("/drafts/{draft_id}/confirm", response_model=ConfirmResult)
async def confirm(
    draft_id: uuid.UUID,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_session),
) -> ConfirmResult:
    try:
        bill, idempotent = await ledger.confirm_draft(session, draft_id, idempotency_key)
    except LedgerError as exc:
        _raise_ledger(exc)
    return ConfirmResult(bill=BillOut.model_validate(bill), idempotent=idempotent)


@router.post("/drafts/{draft_id}/reject", response_model=DraftOut)
async def reject(
    draft_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> DraftOut:
    try:
        draft = await ledger.reject_draft(session, draft_id)
    except LedgerError as exc:
        _raise_ledger(exc)
    input_item = await session.get(Input, draft.input_id)
    return _draft_out(draft, input_item=input_item)


@router.post("/drafts/{draft_id}/datasources/{source}/retry", response_model=DraftOut)
async def retry_source(
    draft_id: uuid.UUID, source: str, session: AsyncSession = Depends(get_session)
) -> DraftOut:
    try:
        draft = await ledger.retry_datasource(session, draft_id, source)
    except LedgerError as exc:
        _raise_ledger(exc)
    input_item = await session.get(Input, draft.input_id)
    bills = await _bill_map(session, [draft.id])
    return _draft_out(draft, bill_id=bills.get(draft.id), input_item=input_item)


# ------------------------------------------------------------------ bills & meta


@router.get("/bills", response_model=list[BillOut])
async def list_bills(
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[BillOut]:
    rows = (
        await session.scalars(
            select(Bill).order_by(Bill.txn_date.desc(), Bill.created_at.desc()).limit(limit).offset(offset)
        )
    ).all()
    return [BillOut.model_validate(row) for row in rows]


@router.get("/merchants", response_model=list[MerchantOut])
async def search_merchants(
    q: str = Query(default="", max_length=100),
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> list[MerchantOut]:
    stmt = select(Merchant).order_by(Merchant.name)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            Merchant.name.ilike(like)
            | Merchant.normalized.ilike(like)
            | Merchant.aliases.ilike(like)
        )
    rows = (await session.scalars(stmt.limit(limit))).all()
    return [
        MerchantOut(
            id=m.id, name=m.name, category=m.category, aliases=m.aliases, confidence=float(m.confidence)
        )
        for m in rows
    ]


@router.get("/stats")
async def stats(session: AsyncSession = Depends(get_session)) -> dict:
    total_bills = await session.scalar(select(func.count()).select_from(Bill))
    total_amount = await session.scalar(select(func.coalesce(func.sum(Bill.amount), 0)))
    pending_review = await session.scalar(
        select(func.count()).select_from(Draft).where(Draft.status == "ready_for_review")
    )
    needs_clarification = await session.scalar(
        select(func.count()).select_from(Draft).where(Draft.status == "needs_clarification")
    )
    inputs_total = await session.scalar(select(func.count()).select_from(Input))
    return {
        "bills": total_bills or 0,
        "total_amount": float(total_amount or 0),
        "pending_review": pending_review or 0,
        "needs_clarification": needs_clarification or 0,
        "inputs": inputs_total or 0,
    }


@router.get("/health", response_model=HealthOut)
async def health(session: AsyncSession = Depends(get_session)) -> HealthOut:
    database = "ok"
    try:
        await session.execute(select(1))
    except Exception as exc:  # pragma: no cover
        database = f"error: {exc}"
    from app.models import Job

    queued = await session.scalar(select(func.count()).select_from(Job).where(Job.status == "queued"))
    running = await session.scalar(select(func.count()).select_from(Job).where(Job.status == "running"))
    return HealthOut(
        status="ok" if database == "ok" else "degraded",
        version=settings.app_version,
        database=database,
        llm_configured=bool(settings.siliconflow_api_key),
        queue={"queued": queued or 0, "running": running or 0},
    )
