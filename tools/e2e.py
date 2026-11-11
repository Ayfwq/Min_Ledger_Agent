"""Small end-to-end smoke test against a running backend."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/api/v1"
import os
PASSWORD = os.environ.get("E2E_PASSWORD", "")


def call(method: str, path: str, body=None, timeout=120):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json; charset=utf-8", "X-App-Password": PASSWORD},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"null")


def wait(input_id: str, timeout: float = 180):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        code, data = call("GET", f"/inputs/{input_id}")
        if code != 200:
            raise SystemExit(f"get input failed {code} {data}")
        last = data
        if data["status"] not in ("pending", "processing"):
            return data
        time.sleep(2)
    raise SystemExit(f"timeout; last={json.dumps(last, ensure_ascii=False)[:500]}")


def show(data: dict):
    print("status:", data["status"], "| failure:", data.get("failure_step"), data.get("failure_reason"))
    for d in data["drafts"]:
        print(
            f"  draft {d['seq']} [{d['status']}] amount={d['amount']} date={d['txn_date']} "
            f"merchant={d['merchant']} category={d['category']} sources={d['field_sources']}"
        )
        for w in d["warnings"]:
            print("    warn:", w["code"], w["message"])
        if d["duplicate_candidates"]:
            print("    dup:", json.dumps(d["duplicate_candidates"], ensure_ascii=False))
        if d["suggestions"].get("merchant"):
            print("    merchant-suggestion:", json.dumps(d["suggestions"]["merchant"], ensure_ascii=False))
    for c in data["clarifications"]:
        print(f"  clarify [{c['status']}] {c['field']} blocking={c['blocking']}: {c['question']}")
    print("trace:", " | ".join(f"{t['step']}:{t['status']}" for t in data["trace_events"]))
    print("ds calls:", [(c["source"], c["status"], c["latency_ms"]) for c in data["datasource_calls"]])


if __name__ == "__main__":
    text = os.environ.get("E2E_TEXT", "昨天中午和同事在海底捞吃饭花了128.5元；晚上打车回家35元")
    code, created = call("POST", "/inputs", {"text": text})
    print("create ->", code)
    data = wait(created["id"])
    show(data)

    for c in data["clarifications"]:
        if c["status"] == "open" and c["field"] == "amount":
            code, ans = call("POST", f"/clarifications/{c['id']}/answer", {"action": "answer", "value": "40"})
            print("answer ->", code, ans.get("status"))
    data = wait(data["id"])
    show(data)

    for d in data["drafts"]:
        if d["status"] == "ready_for_review":
            code, res = call("POST", f"/drafts/{d['id']}/confirm")
            print("confirm ->", code, json.dumps(res, ensure_ascii=False)[:300])
            code2, res2 = call("POST", f"/drafts/{d['id']}/confirm")
            print("confirm again ->", code2, "idempotent=", res2.get("idempotent"))
            break

    code, bills = call("GET", "/bills")
    print("bills:", len(bills))
