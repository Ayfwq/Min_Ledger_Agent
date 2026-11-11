"""Seed the local backend with demo data for screenshots / manual review."""

from __future__ import annotations

import io
import json
import sys
import time
import urllib.request

import httpx
from PIL import Image, ImageDraw

import os
BASE = os.environ.get("LEDGER_BASE", "http://127.0.0.1:8000/api/v1")
TEXT_1 = "昨天中午和同事在海底捞吃饭花了128.5元；晚上打车回家35元"
TEXT_2 = "上周五在星巴克买了两杯拿铁，一共68元"
TEXT_3 = "昨天吃饭花了点钱"


def wait(client: httpx.Client, input_id: str, timeout: float = 180) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(f"/inputs/{input_id}").json()
        if data["status"] not in ("pending", "processing"):
            return data
        time.sleep(2)
    raise SystemExit(f"timeout waiting for {input_id}")


def create_text(client: httpx.Client, text: str) -> dict:
    resp = client.post("/inputs", json={"text": text})
    resp.raise_for_status()
    return wait(client, resp.json()["id"])


def receipt_png() -> bytes:
    img = Image.new("RGB", (620, 780), "white")
    draw = ImageDraw.Draw(img)
    draw.text((40, 40), "LUCKIN COFFEE", fill="black")
    draw.text((40, 120), "Order #20261111-88", fill="black")
    draw.text((40, 220), "Americano  x1      19.90", fill="black")
    draw.text((40, 300), "TOTAL  CNY         19.90", fill="black")
    draw.text((40, 380), "2026-11-09 08:41", fill="black")
    draw.text((40, 460), "Store: Jing'an Temple", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def main() -> None:
    with httpx.Client(base_url=BASE, timeout=240, trust_env=False) as client:
        a = create_text(client, TEXT_1)
        print("A", a["status"], [d["status"] for d in a["drafts"]])
        if a["drafts"]:
            r = client.post(f"/drafts/{a['drafts'][0]['id']}/confirm")
            print("  confirm A0:", r.status_code)

        b = create_text(client, TEXT_2)
        print("B", b["status"], [d["status"] for d in b["drafts"]])
        if b["drafts"]:
            r = client.post(f"/drafts/{b['drafts'][0]['id']}/confirm")
            print("  confirm B0:", r.status_code)

        c = create_text(client, TEXT_2)
        print("C", c["status"], [d["status"] for d in c["drafts"]])
        if c["drafts"]:
            print("  duplicates:", len(c["drafts"][0]["duplicate_candidates"]))

        d = create_text(client, TEXT_3)
        print("D", d["status"], [x["question"] for x in d["clarifications"] if x["status"] == "open"])

        resp = client.post(
            "/inputs/upload",
            files={"file": ("luckin.png", receipt_png(), "image/png")},
        )
        resp.raise_for_status()
        e = wait(client, resp.json()["id"])
        print("E", e["status"], [(x["amount"], x["merchant"]) for x in e["drafts"]])

        stats = client.get("/stats").json()
        print("stats:", json.dumps(stats, ensure_ascii=False))
        print("ids:", a["id"], b["id"], c["id"], d["id"], e["id"])


if __name__ == "__main__":
    sys.exit(main())
