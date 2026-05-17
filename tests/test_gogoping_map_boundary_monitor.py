"""MapBoundaryMonitor 단위 테스트.

ROS 의존성 없음 — MapCache 자체는 ``/map`` 구독이 필요하지만, 본 테스트는 그를 우회해
``is_outside(x, y)`` 만 노출하는 MockMapCache 를 주입한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "controller" / "gogoping-controller" / "src" / "gogoping" / "gogoping_modes"))

import py_trees  # noqa: E402
from py_trees.common import Access, Status  # noqa: E402

from gogoping_modes.bt.blackboard import Keys, init_blackboard  # noqa: E402
from gogoping_modes.bt.behaviors.common.map_boundary_monitor import MapBoundaryMonitor  # noqa: E402


class _MockFSM:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def trigger(self, name: str, **kwargs) -> None:
        self.calls.append((name, kwargs))


class _MockMapCache:
    """is_outside 만 노출하는 mock."""
    def __init__(self, outside_fn):
        self._outside_fn = outside_fn

    def is_outside(self, x: float, y: float):
        return self._outside_fn(x, y)


class _Ctx:
    def __init__(self, outside_fn=None):
        self.fsm = _MockFSM()
        self.map_cache = _MockMapCache(outside_fn or (lambda _x, _y: False))


@pytest.fixture
def bb_writer():
    init_blackboard()
    client = py_trees.blackboard.Client(name="test_writer")
    client.register_key(key=Keys.ROBOT_POSE, access=Access.WRITE)
    return client


def _make(ctx: _Ctx) -> MapBoundaryMonitor:
    mon = MapBoundaryMonitor("mbm", ctx)
    mon.setup()
    mon.initialise()
    return mon


def test_no_fire_when_inside(bb_writer):
    """is_outside=False 면 발화 안 함."""
    ctx = _Ctx(outside_fn=lambda x, y: False)
    bb_writer.set(Keys.ROBOT_POSE, {"x": 1.0, "y": 1.0, "yaw": 0.0})
    mon = _make(ctx)
    mon.update()
    assert ctx.fsm.calls == []


def test_fires_when_outside(bb_writer):
    """is_outside=True 면 fault(reason=out_of_map) 발화."""
    ctx = _Ctx(outside_fn=lambda x, y: True)
    bb_writer.set(Keys.ROBOT_POSE, {"x": 100.0, "y": 100.0, "yaw": 0.0})
    mon = _make(ctx)
    mon.update()
    assert ctx.fsm.calls == [("fault", {"reason": "out_of_map"})]


def test_no_fire_when_map_not_received(bb_writer):
    """is_outside=None (맵 미수신) 이면 발화 안 함 — 보수적 default."""
    ctx = _Ctx(outside_fn=lambda x, y: None)
    bb_writer.set(Keys.ROBOT_POSE, {"x": 100.0, "y": 100.0, "yaw": 0.0})
    mon = _make(ctx)
    mon.update()
    assert ctx.fsm.calls == []


def test_no_double_fire(bb_writer):
    """1회 발화 후 추가 tick 무시 (ERROR terminal)."""
    ctx = _Ctx(outside_fn=lambda x, y: True)
    bb_writer.set(Keys.ROBOT_POSE, {"x": 100.0, "y": 100.0, "yaw": 0.0})
    mon = _make(ctx)
    mon.update()
    mon.update()
    mon.update()
    assert len(ctx.fsm.calls) == 1


def test_writes_error_reason_and_source_to_blackboard(bb_writer):
    """발화 시 blackboard.ERROR_REASON / ERROR_SOURCE 도 세팅."""
    ctx = _Ctx(outside_fn=lambda x, y: True)
    bb_writer.set(Keys.ROBOT_POSE, {"x": 100.0, "y": 100.0, "yaw": 0.0})
    mon = _make(ctx)
    mon.update()

    reader = py_trees.blackboard.Client(name="reader")
    reader.register_key(key=Keys.ERROR_REASON, access=Access.READ)
    reader.register_key(key=Keys.ERROR_SOURCE, access=Access.READ)
    assert reader.get(Keys.ERROR_REASON) == "out_of_map"
    assert reader.get(Keys.ERROR_SOURCE) == "mbm"


def test_initialise_rearms(bb_writer):
    """initialise() 재호출 시 발화 플래그 리셋 — 트리 재진입 시 재발화 가능."""
    ctx = _Ctx(outside_fn=lambda x, y: True)
    bb_writer.set(Keys.ROBOT_POSE, {"x": 100.0, "y": 100.0, "yaw": 0.0})
    mon = _make(ctx)
    mon.update()
    assert len(ctx.fsm.calls) == 1

    mon.initialise()
    mon.update()
    assert len(ctx.fsm.calls) == 2


def test_handles_missing_pose_keys(bb_writer):
    """blackboard.ROBOT_POSE 가 dict 인데 x/y 키 없으면 발화 안 함."""
    ctx = _Ctx(outside_fn=lambda x, y: True)  # 항상 outside 면 fallback 검증
    bb_writer.set(Keys.ROBOT_POSE, {})  # 빈 dict
    mon = _make(ctx)
    mon.update()
    assert ctx.fsm.calls == []  # x/y 누락 → return 안전
