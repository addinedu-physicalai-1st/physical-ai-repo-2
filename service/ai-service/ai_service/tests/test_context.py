from datetime import UTC, datetime

from ai_service.capabilities.db_menu import (
    _ida_polite_copula_after,
    parse_menu_query_calendar_day,
)
from ai_service.capabilities.db_attendance import (
    _is_bare_name_attendance_utterance,
    _looks_like_whereabouts_query,
    _whereabouts_name_candidates,
    bare_name_attendance_reply,
    whereabouts_attendance_reply,
)
from ai_service.capabilities.db_report import (
    _looks_like_report_query,
    _report_name_candidates,
)
from ai_service.context import (
    _looks_like_menu_query,
    _looks_like_schedule_query,
    _should_inject_attendance,
    child_call_name,
    try_schedule_first_reply,
)


def test_ida_copula_after_vowel_ending_noun() -> None:
    assert _ida_polite_copula_after("바나나") == ("예요", "였어요")


def test_ida_copula_after_batchim_noun() -> None:
    assert _ida_polite_copula_after("귤") == ("이에요", "이었어요")
    assert _ida_polite_copula_after("쌀밥") == ("이에요", "이었어요")


def test_ida_copula_after_kimchi_jjigae() -> None:
    assert _ida_polite_copula_after("김치찌개") == ("예요", "였어요")


def test_menu_query_detector() -> None:
    assert _looks_like_menu_query("오늘 점심 메뉴 뭐야?") is True
    assert _looks_like_menu_query("급식 알려줘") is True
    assert _looks_like_menu_query("안녕") is False
    assert _looks_like_menu_query("심심해") is False


def test_child_call_name_korean_three_chars() -> None:
    assert child_call_name("김민수") == "민수"


def test_child_call_name_korean_four_chars() -> None:
    assert child_call_name("남궁민수") == "민수"


def test_child_call_name_space_last_token() -> None:
    assert child_call_name("김 민수") == "민수"


def test_child_call_name_two_syllable_unchanged() -> None:
    assert child_call_name("민수") == "민수"


def test_child_call_name_non_hangul_unchanged() -> None:
    assert child_call_name("Minsoo") == "Minsoo"


def test_should_inject_attendance_keywords() -> None:
    assert _should_inject_attendance("오늘 등원했어?") is True
    assert _should_inject_attendance("하원했니") is True


def test_should_inject_attendance_excludes_greeting() -> None:
    assert _should_inject_attendance("안녕") is False
    assert _should_inject_attendance("고마워") is False


def test_bare_name_utterance_excludes_attendance_keywords() -> None:
    assert _is_bare_name_attendance_utterance("등원했어?") is False
    assert _is_bare_name_attendance_utterance("이정우") is True


def test_bare_name_attendance_reply_empty_rows() -> None:
    assert "기록이 아직 없어요" in bare_name_attendance_reply("이정우", [])


def test_bare_name_attendance_reply_no_match() -> None:
    t = datetime(2026, 5, 9, 9, 5, tzinfo=UTC)
    rows = [("김민수", "IN", t)]
    assert "없어요" in bare_name_attendance_reply("이정우", rows)


def test_bare_name_attendance_reply_in_only() -> None:
    t = datetime(2026, 5, 9, 9, 5, tzinfo=UTC)
    rows = [("이정우", "IN", t)]
    r = bare_name_attendance_reply("이정우", rows)
    assert "등원" in r
    assert "입니다" not in r


def test_whereabouts_query_detector() -> None:
    assert _looks_like_whereabouts_query("최민성 어딨어?") is True
    assert _looks_like_whereabouts_query("민성 어디 있어") is True
    assert _looks_like_whereabouts_query("안녕") is False


def test_whereabouts_name_candidates() -> None:
    c = _whereabouts_name_candidates("최민성 어딨어?")
    assert "최민성" in c


def test_whereabouts_reply_in_only() -> None:
    t = datetime(2026, 5, 9, 9, 5, tzinfo=UTC)
    rows = [("최민성", "IN", t)]
    r = whereabouts_attendance_reply("최민성", rows)
    assert "등원" in r
    assert "유치원" in r


def test_whereabouts_reply_in_and_out() -> None:
    t_in = datetime(2026, 5, 9, 9, 5, tzinfo=UTC)
    t_out = datetime(2026, 5, 9, 15, 0, tzinfo=UTC)
    rows = [("최민성", "IN", t_in), ("최민성", "OUT", t_out)]
    r = whereabouts_attendance_reply("최민성", rows)
    assert "하원" in r
    assert "없을" in r or "없어" in r


def test_report_query_detector() -> None:
    assert _looks_like_report_query("최민성 보고서 읽어줘") is True
    assert _looks_like_report_query("알림장 뭐 적혔어") is True
    assert _looks_like_report_query("오늘 일과 어땠어?") is True
    assert _looks_like_report_query("안녕") is False


def test_report_name_candidates() -> None:
    c = _report_name_candidates("최민성 보고서")
    assert "최민성" in c


def test_schedule_query_not_report_query() -> None:
    assert _looks_like_schedule_query("일과표 알려줘") is True
    assert _looks_like_report_query("일과표 알려줘") is False


def test_report_query_still_일과_content() -> None:
    assert _looks_like_report_query("오늘 일과 어땠어?") is True


def test_try_schedule_first_reply_contains_slots() -> None:
    r = try_schedule_first_reply("시간표 알려줘")
    assert r is not None
    assert "일과표" in r or "알려줄게" in r
    assert "등원" in r or "점심" in r


def _kst_may_11_2026() -> datetime:
    """허브와 동일하게 UTC+9 로 쓰는 naive 시각 (테스트 고정일)."""
    return datetime(2026, 5, 11, 12, 0, 0)


def test_parse_menu_korean_two_days_later() -> None:
    now = _kst_may_11_2026()
    day, rel = parse_menu_query_calendar_day("이틀 뒤 메뉴 뭐야?", now)
    assert rel is None
    assert day == 13


def test_parse_menu_korean_two_days_ago() -> None:
    now = _kst_may_11_2026()
    day, rel = parse_menu_query_calendar_day("이틀 전 메뉴 알려줘", now)
    assert rel is None
    assert day == 9


def test_parse_menu_haru_jje() -> None:
    now = _kst_may_11_2026()
    assert parse_menu_query_calendar_day("하루 뒤 급식", now)[0] == 12
    assert parse_menu_query_calendar_day("하루 전 점심", now)[0] == 10


def test_parse_menu_geulppi() -> None:
    now = _kst_may_11_2026()
    assert parse_menu_query_calendar_day("글피 메뉴", now)[0] == 14


def test_parse_menu_numeric_days_after() -> None:
    now = _kst_may_11_2026()
    assert parse_menu_query_calendar_day("3일 뒤 메뉴", now)[0] == 14
