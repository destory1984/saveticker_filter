"""주간 일정 뉴스 읽기의 시험 (모델·네트워크 안 씀). `python -m pytest tests -q` 로 돌린다."""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import weekly_schedule as ws   # noqa: E402

NOW = datetime(2026, 10, 4, 10, 0, tzinfo=ws.KST)   # 일요일 아침


def item(date, time, title, kind="지표", ticker="", session="", dup=""):
    return {"date": date, "time": time, "title": title, "kind": kind, "ticker": ticker, "session": session, "dup": dup}


def test_is_weekly_needs_title_and_author():
    assert ws.is_weekly({"title": "📌2026년 10월 2주 차 주요 일정", "source": "오선"})
    assert ws.is_weekly({"title": "[SAVE PICK] 📌2026년 11월 1주차 주요일정", "source": "오선"})
    assert not ws.is_weekly({"title": "📌2026년 10월 2주 차 주요 일정", "source": "reuters"})
    assert not ws.is_weekly({"title": "[경제 캘린더] 11월 26일까지의 주요 경제 이벤트", "source": "오선"})


def test_parse_items_drops_bad_shapes():
    out = """설명 [{"date": "2026-10-05", "time": "22:45", "title": "9월 S&P글로벌  서비스업 PMI", "kind": "지표"},
      {"date": "2026-10-08", "time": "새벽", "title": "어플라이드 디지털", "kind": "실적", "ticker": "$apld", "session": "장후"},
      {"date": "2026-10-06", "title": ""}, "글", {"title": "날짜 없음"}]"""
    a, b = ws.parse_items(out)
    assert a == item("2026-10-05", "22:45", "9월 S&P글로벌 서비스업 PMI")
    assert (b["time"], b["ticker"], b["session"]) == ("", "APLD", "장후")
    assert ws.parse_items("JSON 이 아님") == []


def test_plan_times_and_reminders():
    adds, skipped = ws.plan([
        item("2026-10-05", "22:45", "9월 S&P글로벌 서비스업 PMI"),
        item("2026-10-08", "05:10", "리바이스", "실적", "LEVI", "장후"),
        item("2026-10-06", "", "RPM", "실적", "RPM", "장전"),
    ], [], NOW)
    assert not skipped
    pmi, levi, rpm = adds
    assert (pmi["when"].isoformat(), pmi["remind_at"], pmi["allday"]) == ("2026-10-05T22:45:00+09:00", None, False)
    # 새벽 일정은 전날 밤 10시에 알린다
    assert levi["title"] == "리바이스(LEVI) 실적 발표 (장 마감 뒤)"
    assert levi["remind_at"].isoformat() == "2026-10-07T22:00:00+09:00"
    # 시각을 모르면 날짜만 적고 그날 아침 8시에 알린다
    assert rpm["title"] == "RPM(RPM) 실적 발표 (장 전)" and rpm["allday"]
    assert rpm["remind_at"].isoformat() == "2026-10-06T08:00:00+09:00"


def test_plan_skips_past_dup_and_far():
    existing = [{"when": "2026-10-08T19:00+09:00", "title": "펩시(PEP) 실적 발표 (장 전)"}]
    adds, skipped = ws.plan([
        item("2026-10-03", "21:30", "9월 고용보고서"),                          # 지난 일
        item("2026-10-08", "", "pepsico", "실적", "PEP", "장전"),               # 티커가 이미 있다
        item("2026-10-08", "03:00", "FOMC 의사록", dup="미국 FOMC 의사록"),      # 모델이 같은 일이라 했다
        item("2026-10-07", "23:30", "EIA 원유 재고"),
        item("2026-10-07", "23:30", "EIA 원유재고"),                            # 두 장에 나온 같은 일
        item("2026-12-01", "09:00", "먼 일정"),
        item("10월 9일", "", "날짜 꼴이 다름"),
    ], existing, NOW)
    assert [a["title"] for a in adds] == ["EIA 원유 재고"]
    assert [why for _, why in skipped] == ["지난 일", "이미 있음", "이미 있음", "이미 있음", "두 주 넘게 남음", "날짜를 모름"]


def test_todo_skips_done_and_failed():
    rows = [{"id": "a", "title": "10월 2주 차 주요 일정", "source": "오선"},
            {"id": "b", "title": "10월 1주 차 주요 일정", "source": "오선"},
            {"id": "c", "title": "10월 3주 차 주요 일정", "source": "오선"},
            {"id": "c", "title": "10월 3주 차 주요 일정", "source": "오선"},
            {"id": "d", "title": "속보", "source": "오선"}]
    done = {"a": {"at": "2026-10-04T10:00:00+09:00", "added": 43}, "b": {"fail": 3}}
    assert [r["id"] for r in ws.todo(rows, done)] == ["c"]
