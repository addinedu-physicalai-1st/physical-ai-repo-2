"""IdleTimeoutMonitor 단위 테스트.

ROS 의존성 없음 — py_trees 만 사용. ctx.fsm 은 MockFSM, ctx.node 는 None
(IdleTimeoutMonitor 가 None 이면 default 60s 사용 — 테스트는 _timeout_s 직접 override).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

# gogoping_modes 패키지 path 등록
_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "controller" / "gogoping-controller" / "src" / "gogoping" / "gogoping_modes"))

import py_trees  # noqa: E402
from py_trees.common import Status  # noqa: E402

from gogoping_modes.bt.blackboard import init_blackboard  # noqa: E402
from gogoping_modes.bt.behaviors.common.idle_timeout_monitor import IdleTimeoutMonitor  # noqa: E402


class _MockFSM:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def trigger(self, name: str, **_kwargs) -> None:
        self.calls.append(name)


class _Ctx:
    def __init__(self) -> None:
        self.fsm = _MockFSM()
        self.node = None  # ROS 미사용 — default timeout 으로 fallback


@pytest.fixture(autouse=True)
def _init_bb():
    init_blackboard()


def _mon(timeout_s: float = 0.05) -> tuple[IdleTimeoutMonitor, _Ctx]:
    """timeout_s 짧게 (50ms) 강제한 monitor + ctx 반환."""
    ctx = _Ctx()
    mon = IdleTimeoutMonitor("idle_t", ctx)
    mon._timeout_s = timeout_s
    mon.setup()
    mon.initialise()
    return mon, ctx


def test_no_fire_immediately_after_initialise():
    """진입 직후엔 발화 안 함."""
    mon, ctx = _mon()
    assert mon.update() == Status.RUNNING
    assert ctx.fsm.calls == []


def test_fires_after_timeout():
    """timeout 경과 후 idle_timeout 발화."""
    mon, ctx = _mon(timeout_s=0.05)
    time.sleep(0.06)
    mon.update()
    assert ctx.fsm.calls == ["idle_timeout"]


def test_no_double_fire():
    """1회 발화 후 추가 update 호출은 무시."""
    mon, ctx = _mon(timeout_s=0.05)
    time.sleep(0.06)
    mon.update()
    mon.update()
    mon.update()
    assert ctx.fsm.calls == ["idle_timeout"]


def test_initialise_resets_timer_and_rearms():
    """initialise() 재호출 시 timer 리셋 + 발화 플래그 리셋."""
    mon, ctx = _mon(timeout_s=0.05)
    time.sleep(0.06)
    mon.update()  # 1차 발화
    assert ctx.fsm.calls == ["idle_timeout"]

    mon.initialise()  # IDLE 재진입 가정
    mon.update()       # 막 진입 — 발화 안 됨
    assert ctx.fsm.calls == ["idle_timeout"]

    time.sleep(0.06)
    mon.update()       # 또 timeout — 재발화
    assert ctx.fsm.calls == ["idle_timeout", "idle_timeout"]


def test_default_timeout_when_no_node():
    """ctx.node=None 이면 production 코드의 _DEFAULT_TIMEOUT_S (86400s = 24h) 사용."""
    ctx = _Ctx()
    mon = IdleTimeoutMonitor("idle_default", ctx)
    # _DEFAULT_TIMEOUT_S = 86400.0 (24h) — ROS param 없으면 이 값으로 fallback
    assert mon._timeout_s == 86400.0


def test_terminate_idempotent():
    """terminate(new_status) 가 안전하게 여러 번 호출 가능."""
    mon, _ctx = _mon(timeout_s=0.05)
    mon.terminate(Status.INVALID)
    mon.terminate(Status.SUCCESS)  # 두 번째 호출 — 예외 없어야 함
