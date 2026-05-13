"""`generate_report` 보조 — 만 나이 계산."""

from server.ai.llm import _man_age_years_on


def test_man_age_before_birthday_in_report_year() -> None:
    assert _man_age_years_on("2021-06-15", "2026-05-13") == 4


def test_man_age_after_birthday_in_report_year() -> None:
    assert _man_age_years_on("2021-03-01", "2026-05-13") == 5


def test_man_age_invalid_iso_returns_none() -> None:
    assert _man_age_years_on("not-a-date", "2026-05-13") is None
