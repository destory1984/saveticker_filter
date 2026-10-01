"""목표가 표 규칙의 시험 (모델·네트워크 안 씀). `python -m pytest tests -q` 로 돌린다.

예는 실제로 틀렸던 일에서 왔다 (괄호 안 날짜).
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import targets      # noqa: E402
import targets_db   # noqa: E402


def test_broker_key_merges_korean_and_english_names():
    same = [("JPMorgan", "JP모건"), ("BofA", "뱅크오브아메리카"), ("Citi", "씨티"), ("BNP Paribas", "BNP파리바스"),
            ("Canaccord Genuity", "캔어코드 제뉴이티"), ("Argus Research", "아거스 리서치"), ("DS투자증권", "DS투자證"),
            ("Morningstar", "모닝스타"), ("Bernstein", "Sanford C. Bernstein")]
    for x, y in same:
        assert targets.broker_key(x) == targets.broker_key(y), (x, y)
    assert targets.broker_key("Baird") != targets.broker_key("Bernstein")


def test_parse_fixes_korean_tickers():
    # 모델이 SK하이닉스에 "SKHY" 라는 없는 티커를 붙였다 (10-01)
    recs = [{"id": "a", "title": "씨티, SK하이닉스 목표가 300만원 유지"}, {"id": "b", "title": "t"}]
    text = """{"results": [
      {"i": 1, "items": [{"stock": "SK하이닉스", "ticker": "SKHY", "broker": "씨티", "action": "유지", "old": 3000000, "new": 3000000, "cur": "KRW"}]},
      {"i": 2, "items": [{"stock": "AMD", "ticker": "$amd", "broker": "BofA", "action": "상향", "old": 620, "new": "720", "cur": "usd"},
                         {"stock": "AMD", "ticker": "AMD", "broker": "BofA", "action": "모름"}]}]}"""
    got = targets.parse(text, recs)
    assert got["a"][0]["ticker"] == "000660"
    assert got["b"] == [{"stock": "AMD", "ticker": "AMD", "broker": "BofA", "action": "상향", "rating": "",
                         "pt_old": 620.0, "pt_new": 720.0, "currency": "USD"}]
    assert targets.parse("JSON 아님", recs) == {}


def test_stock_key_matches_both_alerters():
    # stocknews_filter 는 야후 티커(005930.KS), 이쪽은 거래소 코드(005930)
    assert targets.stock_key({"stock": "삼성전자", "ticker": "005930.KS"}) == targets.stock_key({"stock": "Samsung", "ticker": "005930"})
    assert targets.stock_key({"stock": "포르 툼", "ticker": ""}) == targets.stock_key({"stock": "포르툼", "ticker": ""})


def _row(stock, ticker, broker, action, pt, hours_ago):
    at = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc) - timedelta(hours=hours_ago)
    return {"stock": stock, "ticker": ticker, "broker": broker, "action": action, "rating": "", "pt_old": None,
            "pt_new": pt, "currency": "USD" if pt else "", "at": at}


def test_group_merges_across_alerters_and_votes():
    rows = [_row("Micron", "MU", "Baird", "제시", 1520, 0), _row("마이크론", "MU", "베어드", "상향", None, 1),
            _row("Micron", "MU", "Baird", "상향", 1520, 2), _row("Micron", "MU", "UBS", "유지", None, 3)]
    g = targets.group(rows)
    assert [(x["broker"], x["action"], len(x["news"])) for x in g] == [("Baird", "상향", 3), ("UBS", "유지", 1)]


def test_candidate():
    assert targets.is_candidate({"title": "BofA, AMD 목표주가 620달러에서 720달러로 상향"})
    assert not targets.is_candidate({"title": "연준 바 부의장 발언"})


def test_ticker_key():
    assert targets_db.ticker_key("000660.KS") == "000660" and targets_db.ticker_key("$amd") == "AMD"
