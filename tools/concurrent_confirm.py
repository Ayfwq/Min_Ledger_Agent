"""Fire concurrent confirm requests at a running instance and verify idempotency."""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

BASE = os.environ.get("LEDGER_BASE", "http://127.0.0.1:18080/api/v1")
PASSWORD = os.environ.get("LEDGER_PASSWORD", "")
HEADERS = {"X-App-Password": PASSWORD} if PASSWORD else {}


def main() -> None:
    with httpx.Client(base_url=BASE, timeout=180, headers=HEADERS, trust_env=False) as client:
        resp = client.post("/inputs", json={"text": "2026-11-05 在肯德基花了 25 元"})
        resp.raise_for_status()
        input_id = resp.json()["id"]

        deadline = time.time() + 180
        detail = {}
        while time.time() < deadline:
            detail = client.get(f"/inputs/{input_id}").json()
            if detail["status"] not in ("pending", "processing"):
                break
            time.sleep(2)

        if not detail.get("drafts"):
            raise SystemExit(f"no draft: {json.dumps(detail, ensure_ascii=False)[:500]}")
        draft = detail["drafts"][0]
        if draft["status"] == "needs_clarification":
            for c in detail["clarifications"]:
                if c["status"] != "open":
                    continue
                value = "2026-11-05" if c["field"] == "txn_date" else "25" if c["field"] == "amount" else "肯德基"
                client.post(f"/clarifications/{c['id']}/answer", json={"action": "answer", "value": value})
            detail = client.get(f"/inputs/{input_id}").json()
            draft = detail["drafts"][0]

        draft_id = draft["id"]
        print("draft:", draft_id, draft["status"], draft["amount"], draft["txn_date"])

        def confirm(i: int):
            headers = {"Idempotency-Key": f"concurrent-test-{draft_id}"} if i % 2 == 0 else {}
            r = client.post(f"/drafts/{draft_id}/confirm", headers=headers)
            body = r.json()
            return r.status_code, body.get("bill", {}).get("id"), body.get("idempotent")

        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(confirm, range(10)))

        statuses = {code for code, _, _ in results}
        bill_ids = {bill for _, bill, _ in results if bill}
        print("statuses:", statuses)
        print("distinct bill ids:", bill_ids)

        bills = client.get("/bills").json()
        same_draft = [b for b in bills if b["draft_id"] == draft_id]
        print("bills for draft:", len(same_draft))
        assert statuses <= {200}, statuses
        assert len(bill_ids) == 1, bill_ids
        assert len(same_draft) == 1, same_draft
        print("OK: concurrent confirm produced exactly one bill")


if __name__ == "__main__":
    main()
