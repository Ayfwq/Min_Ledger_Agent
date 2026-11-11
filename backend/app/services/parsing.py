"""Small deterministic parsers used by clarifications and data sources."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

_DATE_PATTERNS = [
    (re.compile(r"(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})日?"), "ymd"),
    (re.compile(r"^(\d{1,2})[-/月](\d{1,2})日?$"), "md"),
]

_RELATIVE_DAYS = {"今天": 0, "今日": 0, "昨天": -1, "昨日": -1, "前天": -2, "大前天": -3, "明天": 1}

_MERCHANT_NOISE = [
    "有限责任公司",
    "股份有限公司",
    "有限公司",
    "旗舰店",
    "专营店",
    "分店",
    "门店",
    "公司",
]


def parse_amount(raw: str | None) -> Decimal | None:
    if raw is None:
        return None
    text = unicodedata.normalize("NFKC", raw).strip()
    match = re.search(r"-?\d+(?:\.\d{1,2})?", text.replace(",", ""))
    if not match:
        return None
    try:
        value = Decimal(match.group(0)).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    if value < 0 or value > Decimal("99999999"):
        return None
    return value


def parse_date(raw: str | None, today: date | None = None) -> date | None:
    if raw is None:
        return None
    today = today or date.today()
    text = unicodedata.normalize("NFKC", raw).strip()

    for word, delta in _RELATIVE_DAYS.items():
        if word in text:
            return today + timedelta(days=delta)
    if "大后天" in text:
        return today + timedelta(days=3)
    if "后天" in text:
        return today + timedelta(days=2)

    for pattern, kind in _DATE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        try:
            if kind == "ymd":
                return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            month, day = int(match.group(1)), int(match.group(2))
            candidate = date(today.year, month, day)
            if candidate > today + timedelta(days=1):
                candidate = date(today.year - 1, month, day)
            return candidate
        except ValueError:
            return None
    return None


def normalize_merchant(name: str | None) -> str:
    if not name:
        return ""
    text = unicodedata.normalize("NFKC", name).lower()
    text = re.sub(r"[\s\-_.,，。·、()（）\[\]【】《》\"'’“”]+", "", text)
    for noise in _MERCHANT_NOISE:
        text = text.replace(noise, "")
    return text


def merchant_similarity(a: str | None, b: str | None) -> float:
    left, right = normalize_merchant(a), normalize_merchant(b)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if left in right or right in left:
        return 0.9
    from difflib import SequenceMatcher

    return round(SequenceMatcher(None, left, right).ratio(), 3)
