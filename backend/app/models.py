"""Database models.

Portable types are used on purpose (JSON instead of JSONB, Uuid instead of a
Postgres-only UUID column) so the same schema can run on PostgreSQL in
production and SQLite in unit tests.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

JSONType = JSON().with_variant(JSONB, "postgresql")


def utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class Image(Base):
    __tablename__ = "images"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class Input(Base, TimestampMixin):
    __tablename__ = "inputs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # text | image
    raw_text: Mapped[str | None] = mapped_column(Text)
    image_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("images.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)

    # Raw LLM extraction kept for traceability and for resuming after failures.
    extraction: Mapped[dict | None] = mapped_column(JSONType)
    extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_step: Mapped[str | None] = mapped_column(String(32))
    failure_reason: Mapped[str | None] = mapped_column(Text)

    image: Mapped[Image | None] = relationship(lazy="select")
    drafts: Mapped[list[Draft]] = relationship(
        back_populates="input_item",
        cascade="all, delete-orphan",
        order_by="Draft.seq",
    )


class Draft(Base, TimestampMixin):
    __tablename__ = "drafts"
    __table_args__ = (
        UniqueConstraint("input_id", "seq", name="uq_drafts_input_seq"),
        Index("ix_drafts_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    input_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inputs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # drafting | needs_clarification | ready_for_review | confirmed | rejected | failed
    status: Mapped[str] = mapped_column(String(32), default="drafting", nullable=False)

    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(8), default="CNY", nullable=False)
    txn_date: Mapped[date | None] = mapped_column(Date)
    merchant: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(Text)

    # {"amount": "text", "txn_date": "image", "merchant": "user", ...}
    field_sources: Mapped[dict] = mapped_column(JSONType, default=dict)
    # {"amount": 0.95, "merchant": 0.4, ...}
    confidence: Mapped[dict] = mapped_column(JSONType, default=dict)
    warnings: Mapped[list] = mapped_column(JSONType, default=list)
    suggestions: Mapped[dict] = mapped_column(JSONType, default=dict)
    duplicate_candidates: Mapped[list] = mapped_column(JSONType, default=list)
    conflict: Mapped[dict | None] = mapped_column(JSONType)

    input_item: Mapped[Input] = relationship(back_populates="drafts")
    bill: Mapped[Bill | None] = relationship(back_populates="draft", uselist=False)


class Clarification(Base):
    __tablename__ = "clarifications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    input_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inputs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    draft_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("drafts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    field: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="missing", nullable=False)
    # open | answered | unknown | cancelled | resolved
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False)
    blocking: Mapped[bool] = mapped_column(default=True, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    options: Mapped[dict | None] = mapped_column(JSONType)
    answer: Mapped[dict | None] = mapped_column(JSONType)
    round: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Bill(Base):
    __tablename__ = "bills"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    draft_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("drafts.id", ondelete="RESTRICT"), nullable=False, unique=True, index=True
    )
    input_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inputs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="CNY", nullable=False)
    txn_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    merchant: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    draft: Mapped[Draft] = relationship(back_populates="bill")


class TraceEvent(Base):
    __tablename__ = "trace_events"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    input_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inputs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    draft_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("drafts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    step: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # started|ok|failed|retried
    message: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSONType)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )


class DataSourceCall(Base):
    __tablename__ = "datasource_calls"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    input_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inputs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    draft_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("drafts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)  # duplicate_check|merchant_catalog
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # ok|failed
    request: Mapped[dict | None] = mapped_column(JSONType)
    result: Mapped[dict | None] = mapped_column(JSONType)
    error: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )


class Merchant(Base):
    __tablename__ = "merchants"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    normalized: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    # comma separated aliases, e.g. "星巴克,starbucks,星巴克咖啡"
    aliases: Mapped[str] = mapped_column(Text, default="", nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("0.900"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_status_run_after", "status", "run_after"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    input_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inputs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), default="process_input", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    scope: Mapped[str] = mapped_column(String(48), nullable=False)
    response: Mapped[dict | None] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
