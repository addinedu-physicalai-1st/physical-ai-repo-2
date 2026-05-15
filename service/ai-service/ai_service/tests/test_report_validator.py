"""보고서 2차 검수 LLM — Ollama 는 mock (단위)."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from ai_service import llm
from ai_service.llm import (
    _merge_report_validator_into_draft,
    _parse_report_validator_payload,
    _truthy_pass,
    _validate_polished_daily_report_json,
)


def test_truthy_pass() -> None:
    assert _truthy_pass(True)
    assert _truthy_pass("true")
    assert not _truthy_pass(False)
    assert not _truthy_pass("false")


def test_parse_report_validator_payload() -> None:
    assert _parse_report_validator_payload('{"pass": true}') == {"pass": True}
    p = _parse_report_validator_payload(
        '{"pass": false, "summary": "x", "events": []}'
    )
    assert p is not None
    assert p["pass"] is False


def test_merge_report_validator_into_draft() -> None:
    draft: dict = {
        "events": [
            {"time": "09:00", "photo_id": None, "text": "old_a"},
            {"time": "10:00", "photo_id": 1, "text": "old_b"},
        ],
        "summary": "s_old",
    }
    rev = {
        "pass": False,
        "events": [
            {"time": "09:00", "photo_id": None, "text": "new_a"},
            {"time": "10:00", "photo_id": 1, "text": "new_b"},
        ],
        "summary": "s_new",
    }
    out = _merge_report_validator_into_draft(draft, rev, valid_photo_ids={1})
    assert out["events"][0]["text"] == "new_a"
    assert out["events"][1]["text"] == "new_b"
    assert out["summary"] == "s_new"


def test_merge_report_validator_summary_only_preserves_events() -> None:
    draft: dict = {
        "events": [{"time": "09:00", "photo_id": None, "text": "unchanged"}],
        "summary": "짧음",
    }
    rev = {"pass": False, "summary": "등원 후 오전을 보내고 점심을 먹은 뒤 낮잠을 잤으며 오후에는 특별 활동을 하였습니다."}
    out = _merge_report_validator_into_draft(draft, rev, valid_photo_ids=set())
    assert out["events"][0]["text"] == "unchanged"
    assert "점심" in out["summary"] and len(out["summary"]) > len("짧음")


def test_validate_polished_pass_true_returns_same(monkeypatch: pytest.MonkeyPatch) -> None:
    polished = json.dumps(
        {
            "events": [{"time": "09:00", "photo_id": None, "text": "등원했습니다."}],
            "summary": "요약입니다.",
        },
        ensure_ascii=False,
    )
    mock = AsyncMock(return_value='{"pass": true}')
    monkeypatch.setattr(llm, "_ollama_chat", mock)

    async def _run() -> str:
        return await _validate_polished_daily_report_json(
            polished,
            address_name="민수",
            registered_full_name=None,
            class_name="햇님반",
            valid_photo_ids=set(),
        )

    out = asyncio.run(_run())
    assert out == polished
    mock.assert_awaited_once()


def test_validate_polished_revision_repolishes(monkeypatch: pytest.MonkeyPatch) -> None:
    polished = json.dumps(
        {
            "events": [{"time": "09:00", "photo_id": None, "text": "노았습니다."}],
            "summary": "x",
        },
        ensure_ascii=False,
    )
    rev_events = [{"time": "09:00", "photo_id": None, "text": "놀았습니다."}]
    monkeypatch.setattr(
        llm,
        "_ollama_chat",
        AsyncMock(
            return_value=json.dumps(
                {"pass": False, "summary": "요약", "events": rev_events},
                ensure_ascii=False,
            )
        ),
    )

    async def _run() -> str:
        return await _validate_polished_daily_report_json(
            polished,
            address_name="민수",
            registered_full_name=None,
            class_name="",
            valid_photo_ids=set(),
        )

    out = asyncio.run(_run())
    data = json.loads(out)
    assert "노았습니다" not in data["events"][0]["text"]
    assert "놀았습니다" in data["events"][0]["text"]


def test_validate_polished_summary_only_expansion(monkeypatch: pytest.MonkeyPatch) -> None:
    polished = json.dumps(
        {
            "events": [{"time": "09:00", "photo_id": None, "text": "등원했습니다."}],
            "summary": "짧음.",
        },
        ensure_ascii=False,
    )
    long_summary = (
        "민수는 등원한 뒤 오전 간식과 놀이 시간을 보냈고, 점심을 먹은 후 낮잠을 잤습니다. "
        "오후에는 교실 활동과 간식을 마친 뒤 하루를 마무리했습니다."
    )
    monkeypatch.setattr(
        llm,
        "_ollama_chat",
        AsyncMock(
            return_value=json.dumps({"pass": False, "summary": long_summary}, ensure_ascii=False)
        ),
    )

    async def _run() -> str:
        return await _validate_polished_daily_report_json(
            polished,
            address_name="민수",
            registered_full_name=None,
            class_name="",
            valid_photo_ids=set(),
        )

    out = asyncio.run(_run())
    data = json.loads(out)
    assert data["events"][0]["text"] == "등원했습니다."
    assert data["summary"] == long_summary
    assert len(data["summary"]) > 10
