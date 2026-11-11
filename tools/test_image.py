"""Upload a synthetic receipt screenshot and exercise the vision + conflict flow."""

from __future__ import annotations

import io
import json
import sys
import time

import httpx
from PIL import Image, ImageDraw

BASE = "http://127.0.0.1:8000/api/v1"


def make_receipt() -> bytes:
    img = Image.new("RGB", (600, 800), "white")
    draw = ImageDraw.Draw(img)
    lines = [
        ("STARBUCKS COFFEE", 40),
        ("Order #A1024", 120),
        ("Latte  x2        35.50", 200),
        ("TOTAL   CNY     35.50", 280),
        ("2026-11-10 09:32", 360),
        ("Store:  Shanghai Xintiandi", 440),
    ]
    for text, y in lines:
        draw.text((40, y), text, fill="black")
    draw.line((40, 330, 560, 330), fill="black", width=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def main() -> None:
    with httpx.Client(base_url=BASE, timeout=180, trust_env=False) as client:
        data = make_receipt()
        resp = client.post(
            "/inputs/upload",
            files={"file": ("receipt.png", data, "image/png")},
        )
        print("upload ->", resp.status_code)
        created = resp.json()
        input_id = created["id"]
        print("image url:", created["image"]["url"])

        deadline = time.time() + 180
        detail = created
        while time.time() < deadline:
            detail = client.get(f"/inputs/{input_id}").json()
            if detail["status"] not in ("pending", "processing"):
                break
            time.sleep(3)

        print("status:", detail["status"], detail.get("failure_reason"))
        for d in detail["drafts"]:
            print("draft", d["seq"], d["status"], d["amount"], d["txn_date"], d["merchant"], d["category"])
            for w in d["warnings"]:
                print("  warn:", w["code"], w["message"])
        for c in detail["clarifications"]:
            print("clarify:", c["field"], c["kind"], c["status"], c["question"])

        # If the model could not read the amount, provide it manually first.
        for c in detail["clarifications"]:
            if c["status"] == "open" and c["field"] == "amount" and c["kind"] == "missing":
                r = client.post(f"/clarifications/{c['id']}/answer", json={"action": "answer", "value": "35.5"})
                print("answer amount 35.5 ->", r.status_code)
                detail = client.get(f"/inputs/{input_id}").json()
                break

        drafts = [d for d in detail["drafts"]]
        if drafts:
            d = drafts[0]
            r = client.patch(f"/drafts/{d['id']}", json={"amount": "40"})
            print("patch 40 ->", r.status_code, r.json().get("detail"))
            r = client.patch(f"/drafts/{d['id']}", json={"amount": "40", "force": True})
            print("patch force ->", r.status_code, r.json().get("amount"))
        detail = client.get(f"/inputs/{input_id}").json()
        print("final:", [(d["seq"], d["status"], d["amount"], d["merchant"]) for d in detail["drafts"]])
        print("trace:", [f"{t['step']}:{t['status']}" for t in detail["trace_events"]])

if __name__ == "__main__":
    sys.exit(main())
