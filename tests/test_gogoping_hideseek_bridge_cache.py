"""GogopingRosBridge — hideseek caught_ids 누적 캐시 동작.

SetBlackboard.srv 자체 호출은 mock — 본 테스트는 캐시 누적 / reset / 중복 호출
처리만 검증.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "service" / "control-service"))

from control_service.gogoping.ros_bridge import (
    BB_KEY_HIDESEEK_CAUGHT_IDS,
    BB_KEY_HIDESEEK_REGISTERED_IDS,
    GogopingRosBridge,
)


@pytest.fixture
def bridge_with_stub_call():
    """``_call_set_blackboard_sync`` 만 stub 한 bridge — 캐시 동작 검증용."""
    b = GogopingRosBridge()
    calls: list[tuple[str, object]] = []

    def _stub(key, value):
        calls.append((key, value))
        return True, ""

    # bound method monkeypatch
    b._call_set_blackboard_sync = _stub  # type: ignore[assignment]
    return b, calls


def test_recruit_complete_writes_registered_ids(bridge_with_stub_call):
    bridge, calls = bridge_with_stub_call
    ok, reason = bridge.write_hideseek_registered_ids([1, 3, 7])
    assert ok is True
    assert reason == ""
    assert calls == [(BB_KEY_HIDESEEK_REGISTERED_IDS, [1, 3, 7])]


def test_caught_accumulates_across_calls(bridge_with_stub_call):
    """여러 caught 호출 시 sorted 누적 list 가 전달된다."""
    bridge, calls = bridge_with_stub_call
    bridge.append_hideseek_caught_id(5)
    bridge.append_hideseek_caught_id(2)
    bridge.append_hideseek_caught_id(8)
    keys_values = [(k, v) for k, v in calls]
    assert keys_values == [
        (BB_KEY_HIDESEEK_CAUGHT_IDS, [5]),
        (BB_KEY_HIDESEEK_CAUGHT_IDS, [2, 5]),
        (BB_KEY_HIDESEEK_CAUGHT_IDS, [2, 5, 8]),
    ]


def test_caught_duplicate_id_is_harmless(bridge_with_stub_call):
    """같은 child_id 중복 호출 시 list 가 커지지 않는다 — set conversion."""
    bridge, calls = bridge_with_stub_call
    bridge.append_hideseek_caught_id(5)
    bridge.append_hideseek_caught_id(5)
    bridge.append_hideseek_caught_id(5)
    # 세 번 모두 [5] — sorted set 한 명만 반영
    for _, value in calls:
        assert value == [5]
    assert len(calls) == 3


def test_recruit_complete_resets_caught_cache(bridge_with_stub_call):
    """recruit-complete 호출 시 누적 캐시가 리셋되어 다음 caught 는 새 round 부터 시작."""
    bridge, calls = bridge_with_stub_call
    bridge.append_hideseek_caught_id(5)
    bridge.append_hideseek_caught_id(2)
    # 새 round 시작
    bridge.write_hideseek_registered_ids([10, 20])
    # caught 다시 시작 — 이전 round 의 5, 2 는 사라져야 한다
    bridge.append_hideseek_caught_id(10)

    # call 순서: caught 5 → caught 2 → recruit → caught 10
    assert calls[0] == (BB_KEY_HIDESEEK_CAUGHT_IDS, [5])
    assert calls[1] == (BB_KEY_HIDESEEK_CAUGHT_IDS, [2, 5])
    assert calls[2] == (BB_KEY_HIDESEEK_REGISTERED_IDS, [10, 20])
    assert calls[3] == (BB_KEY_HIDESEEK_CAUGHT_IDS, [10])  # 누적 캐시 reset 확인


def test_call_set_blackboard_returns_bridge_not_started():
    """start() 안 한 bridge 는 즉시 service_unavailable 반환."""
    bridge = GogopingRosBridge()
    # _set_blackboard_cli 는 None, _ros_ok 는 False
    ok, reason = bridge._call_set_blackboard_sync("hideseek_registered_ids", [1])
    assert ok is False
    assert reason == "bridge_not_started"
