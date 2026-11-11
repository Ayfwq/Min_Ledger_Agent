from datetime import date

from app.services.parsing import merchant_similarity, normalize_merchant, parse_amount, parse_date


def test_parse_amount():
    assert str(parse_amount("128.5元")) == "128.50"
    assert str(parse_amount("￥35.5")) == "35.50"
    assert str(parse_amount("花了 1,200.00 元")) == "1200.00"
    assert parse_amount("花了点钱") is None


def test_parse_date_iso_and_relative():
    today = date(2026, 11, 11)
    assert parse_date("2026-11-01", today) == date(2026, 11, 1)
    assert parse_date("11月1日", today) == date(2026, 11, 1)
    assert parse_date("昨天", today) == date(2026, 11, 10)
    assert parse_date("11/1", today) == date(2026, 11, 1)
    assert parse_date("不知道", today) is None


def test_merchant_normalization_and_similarity():
    assert normalize_merchant("星巴克（上海）有限公司") == "星巴克上海"
    assert merchant_similarity("STARBUCKS COFFEE", "starbucks") >= 0.9
    assert merchant_similarity("星巴克", "瑞幸咖啡") < 0.4
