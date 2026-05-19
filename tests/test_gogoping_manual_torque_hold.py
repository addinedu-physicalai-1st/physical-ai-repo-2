"""ManualTorqueHold 단위 테스트.

ROS 의존성 없음 — fake BaseDriverClient 주입해서 release/enable 호출 시퀀스 검증.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# gogoping_modes 패키지 path 등록
_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "controller" / "gogoping-controller" / "src" / "gogoping" / "gogoping_modes"))

import py_trees  # noqa: E402
from py_trees.common import Status  # noqa: E402

from gogoping_modes.bt.blackboard import Keys, init_blackboard  # noqa: E402
from gogoping_modes.bt.behaviors.manual.manual_torque_hold import ManualTorqueHold  # noqa: E402


class _FakeDriver:
    """`release_torque` / `enable_torque` 호출 기록 + 성공 여부 제어."""

    def __init__(self, release_ok: bool = True, enable_ok: bool = True) -> None:
        self.calls: list[str] = []
        self._release_ok = release_ok
        self._enable_ok = enable_ok

    def release_torque(self) -> bool:
        self.calls.append("release")
        return self._release_ok

    def enable_torque(self) -> bool:
        self.calls.append("enable")
        return self._enable_ok


class _Ctx:
    def __init__(self, driver: _FakeDriver | None = None) -> None:
        self.base_driver = driver


@pytest.fixture(autouse=True)
def _init_bb():
    init_blackboard()


def _bb_read(key: str) -> bool:
    """blackboard 의 단일 키 READ wrapper."""
    bb = py_trees.blackboard.Client(name="test_reader")
    bb.register_key(key=key, access=py_trees.common.Access.READ)
    return bb.get(key)


def _mon(driver: _FakeDriver | None = None) -> tuple[ManualTorqueHold, _FakeDriver]:
    drv = driver if driver is not None else _FakeDriver()
    ctx = _Ctx(drv)
    mon = ManualTorqueHold("manual_torque", ctx)
    return mon, drv


def test_initialise_calls_release_torque():
    """MANUAL 진입 → release_torque() 호출 + blackboard MANUAL_TORQUE_ACTIVE=True."""
    mon, drv = _mon()
    mon.initialise()
    assert drv.calls == ["release"]
    assert _bb_read(Keys.MANUAL_TORQUE_ACTIVE) is True


def test_update_returns_running_without_extra_calls():
    """매 tick RUNNING — driver 추가 호출 없음."""
    mon, drv = _mon()
    mon.initialise()
    drv.calls.clear()
    for _ in range(5):
        assert mon.update() == Status.RUNNING
    assert drv.calls == []


def test_terminate_calls_enable_torque_and_clears_flag():
    """MANUAL 나감 → enable_torque() 호출 + blackboard MANUAL_TORQUE_ACTIVE=False."""
    mon, drv = _mon()
    mon.initialise()
    drv.calls.clear()
    mon.terminate(Status.INVALID)
    assert drv.calls == ["enable"]
    assert _bb_read(Keys.MANUAL_TORQUE_ACTIVE) is False


def test_release_failure_still_marks_blackboard():
    """release_torque 실패해도 사용자 의도는 blackboard 에 반영."""
    mon, drv = _mon(driver=_FakeDriver(release_ok=False))
    mon.initialise()
    assert _bb_read(Keys.MANUAL_TORQUE_ACTIVE) is True


def test_terminate_clears_flag_even_on_enable_failure():
    """enable_torque 실패해도 blackboard flag 는 정리 (BT 상태 일관성 우선)."""
    mon, drv = _mon(driver=_FakeDriver(enable_ok=False))
    mon.initialise()
    mon.terminate(Status.INVALID)
    assert _bb_read(Keys.MANUAL_TORQUE_ACTIVE) is False


def test_missing_driver_does_not_crash():
    """ctx.base_driver=None 이어도 (test 환경 / driver 못 띄운 경우) crash 금지."""
    ctx = _Ctx(driver=None)
    mon = ManualTorqueHold("manual_torque", ctx)
    mon.initialise()              # release skip
    assert mon.update() == Status.RUNNING
    mon.terminate(Status.INVALID) # enable skip
    # blackboard 는 그래도 의도 반영
    assert _bb_read(Keys.MANUAL_TORQUE_ACTIVE) is False
