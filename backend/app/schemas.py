from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------- requests


class TextInputCreate(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class DraftUpdate(BaseModel):
    amount: Decimal | None = None
    txn_date: date | None = None
    merchant: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=1000)
    # Explicit human confirmation when overwriting a value that came from the
    # model / screenshot (guards against silently dropping the original value).
    force: bool = False

    @field_validator("amount")
    @classmethod
    def _amount_positive(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v < 0:
            raise ValueError("金额不能为负数")
        return v


class ClarificationAnswer(BaseModel):
    action: Literal["answer", "unknown", "choose"] = "answer"
    value: str | None = Field(default=None, max_length=500)
    choice: Literal["new", "existing"] | None = None


class AuthVerify(BaseModel):
    password: str


# ---------------------------------------------------------------- responses


class ImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    width: int | None = None
    height: int | None = None
    url: str


class DraftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    input_id: uuid.UUID
    seq: int
    status: str
    amount: Decimal | None = None
    currency: str = "CNY"
    txn_date: date | None = None
    merchant: str | None = None
    category: str | None = None
    note: str | None = None
    field_sources: dict[str, str] = {}
    confidence: dict[str, float] = {}
    warnings: list[dict[str, Any]] = []
    suggestions: dict[str, Any] = {}
    duplicate_candidates: list[dict[str, Any]] = []
    conflict: dict[str, Any] | None = None
    bill_id: uuid.UUID | None = None
    input_kind: str | None = None
    input_text: str | None = None
    created_at: datetime
    updated_at: datetime


class ClarificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    input_id: uuid.UUID
    draft_id: uuid.UUID | None = None
    field: str
    kind: str
    status: str
    blocking: bool
    question: str
    reason: str | None = None
    options: dict[str, Any] | None = None
    answer: dict[str, Any] | None = None
    round: int = 1
    created_at: datetime
    answered_at: datetime | None = None


class TraceEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    input_id: uuid.UUID
    draft_id: uuid.UUID | None = None
    step: str
    status: str
    message: str | None = None
    payload: dict[str, Any] | None = None
    duration_ms: int | None = None
    created_at: datetime


class DataSourceCallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    input_id: uuid.UUID
    draft_id: uuid.UUID | None = None
    source: str
    status: str
    request: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    latency_ms: int | None = None
    created_at: datetime


class InputListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    kind: str
    raw_text: str | None = None
    status: str
    failure_step: str | None = None
    failure_reason: str | None = None
    image: ImageOut | None = None
    draft_count: int = 0
    open_clarifications: int = 0
    latest_clarification: str | None = None
    created_at: datetime
    updated_at: datetime


class InputDetail(InputListItem):
    drafts: list[DraftOut] = []
    clarifications: list[ClarificationOut] = []
    trace_events: list[TraceEventOut] = []
    datasource_calls: list[DataSourceCallOut] = []


class BillOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    draft_id: uuid.UUID
    input_id: uuid.UUID
    amount: Decimal
    currency: str
    txn_date: date
    merchant: str | None = None
    category: str | None = None
    note: str | None = None
    created_at: datetime


class MerchantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    category: str
    aliases: str = ""
    confidence: float = 0.9


class ConfirmResult(BaseModel):
    bill: BillOut
    idempotent: bool = False


class HealthOut(BaseModel):
    status: str
    version: str = "dev"
    database: str
    llm_configured: bool
    queue: dict[str, int] = {}
