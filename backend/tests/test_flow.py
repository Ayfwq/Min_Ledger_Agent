from __future__ import annotations

import uuid

import pytest

from app.services.pipeline import PipelineError, process_input


async def _create(client, text: str) -> dict:
    resp = await client.post("/api/v1/inputs", json={"text": text})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _run(session, input_id: str):
    await process_input(session, uuid.UUID(input_id))


async def _detail(client, input_id: str) -> dict:
    resp = await client.get(f"/api/v1/inputs/{input_id}")
    assert resp.status_code == 200
    return resp.json()


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["database"] == "ok"
    assert body["version"]


@pytest.mark.asyncio
async def test_multi_transaction_extraction(client, session, fake_llm):
    fake_llm["transactions"] = [
        {
            "amount": 128.5,
            "date": "2026-11-01",
            "merchant": "海底捞",
            "description": "聚餐",
            "category": "餐饮",
            "confidence": {"amount": 0.98, "date": 0.9, "merchant": 0.9},
        },
        {
            "amount": 35,
            "date": "2026-11-01",
            "merchant": None,
            "description": "打车",
            "category": "交通",
            "confidence": {"amount": 0.95, "date": 0.8},
        },
    ]
    created = await _create(client, "昨晚聚餐128.5，打车35")
    await _run(session, created["id"])
    detail = await _detail(client, created["id"])

    assert detail["status"] == "ready_for_review"
    assert len(detail["drafts"]) == 2
    first, second = detail["drafts"]
    assert float(first["amount"]) == 128.5
    assert first["field_sources"]["amount"] == "text"
    assert float(second["amount"]) == 35.0
    assert second["merchant"] is None
    # missing optional field -> warning, but still reviewable
    assert any(w["code"] == "missing_optional" for w in second["warnings"])
    # non-blocking clarification for the missing merchant
    open_clarifications = [c for c in detail["clarifications"] if c["status"] == "open"]
    assert open_clarifications and open_clarifications[0]["blocking"] is False
    assert any(t["step"] == "extract" and t["status"] == "ok" for t in detail["trace_events"])


@pytest.mark.asyncio
async def test_missing_amount_blocks_confirmation(client, session, fake_llm):
    fake_llm["transactions"] = [
        {"amount": None, "date": "2026-11-01", "merchant": "星巴克", "category": "餐饮"}
    ]
    created = await _create(client, "昨天喝咖啡花了点钱")
    await _run(session, created["id"])
    detail = await _detail(client, created["id"])

    assert detail["status"] == "needs_clarification"
    draft = detail["drafts"][0]
    assert draft["amount"] is None
    assert any(w["code"] == "missing_critical" for w in draft["warnings"])
    blocking = [c for c in detail["clarifications"] if c["blocking"] and c["status"] == "open"]
    assert blocking and blocking[0]["field"] == "amount"

    resp = await client.post(f"/api/v1/drafts/{draft['id']}/confirm")
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "missing_critical"


@pytest.mark.asyncio
async def test_answer_clarification_then_confirm_is_idempotent(client, session, fake_llm):
    fake_llm["transactions"] = [
        {"amount": None, "date": "2026-11-01", "merchant": "星巴克", "category": "餐饮"}
    ]
    created = await _create(client, "昨天喝咖啡花了点钱")
    await _run(session, created["id"])
    detail = await _detail(client, created["id"])
    clarification = next(c for c in detail["clarifications"] if c["status"] == "open")
    draft_id = detail["drafts"][0]["id"]

    resp = await client.post(
        f"/api/v1/clarifications/{clarification['id']}/answer",
        json={"action": "answer", "value": "38.5"},
    )
    assert resp.status_code == 200
    detail = await _detail(client, created["id"])
    assert detail["drafts"][0]["amount"] == "38.50"
    assert detail["drafts"][0]["field_sources"]["amount"] == "user"
    assert detail["status"] == "ready_for_review"

    first = await client.post(f"/api/v1/drafts/{draft_id}/confirm")
    assert first.status_code == 200
    bill_id = first.json()["bill"]["id"]
    assert first.json()["idempotent"] is False

    second = await client.post(f"/api/v1/drafts/{draft_id}/confirm")
    assert second.status_code == 200
    assert second.json()["bill"]["id"] == bill_id
    assert second.json()["idempotent"] is True

    bills = (await client.get("/api/v1/bills")).json()
    assert len([b for b in bills if b["draft_id"] == draft_id]) == 1


@pytest.mark.asyncio
async def test_conflict_requires_force_override(client, session, fake_llm):
    fake_llm["transactions"] = [
        {"amount": 35.5, "date": "2026-11-01", "merchant": "星巴克", "category": "餐饮"}
    ]
    created = await _create(client, "星巴克35.5")
    await _run(session, created["id"])
    detail = await _detail(client, created["id"])
    draft_id = detail["drafts"][0]["id"]

    conflict = await client.patch(f"/api/v1/drafts/{draft_id}", json={"amount": "40"})
    assert conflict.status_code == 409
    body = conflict.json()["detail"]
    assert body["code"] == "value_conflict"
    assert body["conflicts"][0]["existing"] == 35.5

    forced = await client.patch(f"/api/v1/drafts/{draft_id}", json={"amount": "40", "force": True})
    assert forced.status_code == 200
    assert float(forced.json()["amount"]) == 40.0
    assert forced.json()["field_sources"]["amount"] == "user"


@pytest.mark.asyncio
async def test_duplicate_detection_and_retry(client, session, fake_llm):
    fake_llm["transactions"] = [
        {"amount": 50.0, "date": "2026-11-02", "merchant": "星巴克", "category": "餐饮"}
    ]
    first = await _create(client, "星巴克50")
    await _run(session, first["id"])
    first_detail = await _detail(client, first["id"])
    first_draft = first_detail["drafts"][0]
    assert first_draft["status"] == "ready_for_review"
    await client.post(f"/api/v1/drafts/{first_draft['id']}/confirm")

    second = await _create(client, "星巴克50")
    await _run(session, second["id"])
    second_detail = await _detail(client, second["id"])
    draft = second_detail["drafts"][0]
    assert draft["duplicate_candidates"], "should detect the previously confirmed bill"
    assert any(w["code"] == "duplicate_suspected" for w in draft["warnings"])
    assert any(c["source"] == "duplicate_check" for c in second_detail["datasource_calls"])

    retried = await client.post(f"/api/v1/drafts/{draft['id']}/datasources/duplicate_check/retry")
    assert retried.status_code == 200
    detail = await _detail(client, second["id"])
    assert any(t["step"] == "datasource.duplicate_check" for t in detail["trace_events"])


@pytest.mark.asyncio
async def test_llm_failure_then_retry(client, session, monkeypatch):
    from app.services.llm import LLMError

    async def boom(text: str):
        raise LLMError("模型调用超时")

    monkeypatch.setattr("app.services.pipeline.llm_client.extract_text", boom)
    created = await _create(client, "任意文本")
    with pytest.raises(PipelineError):
        await _run(session, created["id"])

    detail = await _detail(client, created["id"])
    assert detail["status"] == "failed"
    assert detail["failure_step"] == "extract"
    assert "模型调用超时" in detail["failure_reason"]
    assert any(t["status"] == "failed" for t in detail["trace_events"])

    retry = await client.post(f"/api/v1/inputs/{created['id']}/retry")
    assert retry.status_code == 200
    assert retry.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_unknown_answer_keeps_blocking(client, session, fake_llm):
    fake_llm["transactions"] = [{"amount": None, "date": None, "merchant": None}]
    created = await _create(client, "花了点钱")
    await _run(session, created["id"])
    detail = await _detail(client, created["id"])
    clarification = next(c for c in detail["clarifications"] if c["status"] == "open")

    resp = await client.post(
        f"/api/v1/clarifications/{clarification['id']}/answer", json={"action": "unknown"}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "unknown"
    detail = await _detail(client, created["id"])
    assert detail["drafts"][0]["status"] == "needs_clarification"

@pytest.mark.asyncio
async def test_image_upload_is_persisted(client, session, fake_llm, tmp_path=None):
    import io

    from PIL import Image as PILImage

    fake_llm["transactions"] = [
        {"amount": 19.9, "date": "2026-11-09", "merchant": "瑞幸咖啡", "category": "餐饮"}
    ]
    buf = io.BytesIO()
    PILImage.new("RGB", (320, 480), "white").save(buf, format="PNG")
    resp = await client.post(
        "/api/v1/inputs/upload",
        files={"file": ("receipt.png", buf.getvalue(), "image/png")},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["kind"] == "image"
    assert body["image"]["url"].startswith("/uploads/")
    await _run(session, body["id"])
    detail = await _detail(client, body["id"])
    assert detail["drafts"][0]["field_sources"]["amount"] == "image"


@pytest.mark.asyncio
async def test_datasource_failure_does_not_block_draft(client, session, fake_llm, monkeypatch):
    from app.services.datasources import SourceOutcome

    async def broken(session_, draft):
        return SourceOutcome(source="duplicate_check", status="failed", error="查重服务超时")

    monkeypatch.setattr("app.services.datasources.check_duplicates", broken)
    fake_llm["transactions"] = [
        {"amount": 12.0, "date": "2026-11-03", "merchant": "瑞幸咖啡", "category": "餐饮"}
    ]
    created = await _create(client, "瑞幸12元")
    await _run(session, created["id"])
    detail = await _detail(client, created["id"])
    draft = detail["drafts"][0]
    assert draft["status"] == "ready_for_review"
    assert any(w["code"] == "datasource_failed" for w in draft["warnings"])

    async def fixed(session_, draft_):
        return SourceOutcome(
            source="duplicate_check",
            status="ok",
            result={"candidates": [], "checked_window_days": 3},
        )

    monkeypatch.setattr("app.services.datasources.check_duplicates", fixed)
    resp = await client.post(f"/api/v1/drafts/{draft['id']}/datasources/duplicate_check/retry")
    assert resp.status_code == 200
    detail = await _detail(client, created["id"])
    assert not any(w["code"] == "datasource_failed" for w in detail["drafts"][0]["warnings"])

@pytest.mark.asyncio
async def test_low_confidence_merchant_gets_non_blocking_question(client, session, fake_llm):
    fake_llm["transactions"] = [
        {
            "amount": 20.0,
            "date": "2026-11-04",
            "merchant": "星巳克",
            "category": "餐饮",
            "confidence": {"amount": 0.9, "date": 0.9, "merchant": 0.3},
        }
    ]
    created = await _create(client, "2026-11-04 咖啡 20 元")
    await _run(session, created["id"])
    detail = await _detail(client, created["id"])
    draft = detail["drafts"][0]
    assert draft["status"] == "ready_for_review"
    ambiguous = [c for c in detail["clarifications"] if c["kind"] == "ambiguous"]
    assert ambiguous and ambiguous[0]["blocking"] is False
    assert "星巳克" in ambiguous[0]["question"]

    resp = await client.post(
        f"/api/v1/clarifications/{ambiguous[0]['id']}/answer",
        json={"action": "answer", "value": "正确"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "resolved"
    detail = await _detail(client, created["id"])
    assert detail["drafts"][0]["confidence"]["merchant"] == 1.0
    assert not any(w["code"] == "low_confidence" for w in detail["drafts"][0]["warnings"])


@pytest.mark.asyncio
async def test_input_list_exposes_latest_clarification(client, session, fake_llm):
    fake_llm["transactions"] = [{"amount": None, "date": "2026-11-04", "merchant": "星巴克"}]
    created = await _create(client, "2026-11-04 喝咖啡")
    await _run(session, created["id"])
    items = (await client.get("/api/v1/inputs")).json()
    row = next(i for i in items if i["id"] == created["id"])
    assert row["open_clarifications"] == 1
    assert "金额" in (row["latest_clarification"] or "")

@pytest.mark.asyncio
async def test_confirm_closes_optional_clarifications(client, session, fake_llm):
    fake_llm["transactions"] = [
        {"amount": 16.0, "date": "2026-11-06", "merchant": None, "category": "餐饮"}
    ]
    created = await _create(client, "2026-11-06 午饭 16 元")
    await _run(session, created["id"])
    detail = await _detail(client, created["id"])
    draft = detail["drafts"][0]
    assert draft["status"] == "ready_for_review"
    open_before = [c for c in detail["clarifications"] if c["status"] == "open"]
    assert open_before and open_before[0]["blocking"] is False

    resp = await client.post(f"/api/v1/drafts/{draft['id']}/confirm")
    assert resp.status_code == 200
    detail = await _detail(client, created["id"])
    assert not [c for c in detail["clarifications"] if c["status"] == "open"]
    assert all(c["status"] == "cancelled" for c in detail["clarifications"])

    items = (await client.get("/api/v1/inputs")).json()
    row = next(i for i in items if i["id"] == created["id"])
    assert row["open_clarifications"] == 0
    assert row["latest_clarification"] is None

@pytest.mark.asyncio
async def test_merchant_catalog_falls_back_to_description(client, session, fake_llm, merchants):
    fake_llm["transactions"] = [
        {
            "amount": 33.0,
            "date": "2026-11-07",
            "merchant": None,
            "description": "星巴克拿铁",
            "category": None,
            "confidence": {"amount": 0.9, "date": 0.9},
        }
    ]
    created = await _create(client, "2026-11-07 星巴克拿铁 33 元")
    await _run(session, created["id"])
    detail = await _detail(client, created["id"])
    suggestion = detail["drafts"][0]["suggestions"].get("merchant") or {}
    assert suggestion.get("matched") is True
    assert suggestion["merchant"]["name"] == "星巴克"
