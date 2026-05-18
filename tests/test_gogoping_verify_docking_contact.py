"""VerifyDockingContact 단위 테스트.

ROS 의존성 없음 — MockFSM 으로 trigger 호출 기록.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "controller" / "gogoping-controller" / "src" / "gogoping" / "gogoping_modes"))

from py_trees.common import Status  # noqa: E402

from gogoping_modes.bt.behaviors.navigation.verify_docking_contact import VerifyDockingContact  # noqa: E402


class _MockFSM:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def trigger(self, name: str, **_kwargs) -> None:
        self.calls.append(name)


class _Ctx:
    def __init__(self) -> None:
        self.fsm = _MockFSM()


def test_fires_docked_trigger_on_first_update():
    """첫 update 호출 시 docked trigger 발사 + SUCCESS."""
    ctx = _Ctx()
    behavior = VerifyDockingContact("vdc", ctx)
    behavior.initialise()
    assert behavior.update() == Status.SUCCESS
    assert ctx.fsm.calls == ["docked"]


def test_no_double_fire():
    """반복 update 호출해도 trigger 는 1회만."""
    ctx = _Ctx()
    behavior = VerifyDockingContact("vdc", ctx)
    behavior.initialise()
    for _ in range(5):
        assert behavior.update() == Status.SUCCESS
    assert ctx.fsm.calls == ["docked"]


def test_initialise_rearms_for_next_returning_cycle():
    """initialise() 재호출 시 _fired 리셋 → 다음 RETURNING 진입에 재발사."""
    ctx = _Ctx()
    behavior = VerifyDockingContact("vdc", ctx)
    behavior.initialise()
    behavior.update()
    assert ctx.fsm.calls == ["docked"]

    behavior.initialise()  # 다음 RETURNING 사이클
    behavior.update()
    assert ctx.fsm.calls == ["docked", "docked"]


def test_trigger_exception_does_not_crash():
    """fsm.trigger 가 예외 던져도 (잘못된 state 등) SUCCESS 반환 + 재시도 X."""
    class _BadFSM:
        def trigger(self, name, **_kwargs):
            raise RuntimeError("invalid trigger from current state")
    ctx = _Ctx()
    ctx.fsm = _BadFSM()
    behavior = VerifyDockingContact("vdc", ctx)
    behavior.initialise()
    assert behavior.update() == Status.SUCCESS
    # 두 번째 update 도 안전
    assert behavior.update() == Status.SUCCESS


def test_terminate_idempotent():
    ctx = _Ctx()
    behavior = VerifyDockingContact("vdc", ctx)
    behavior.terminate(Status.INVALID)
    behavior.terminate(Status.SUCCESS)
