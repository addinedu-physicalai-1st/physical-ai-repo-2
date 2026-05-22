"""PanCameraSweep behavior 단위 테스트.

시간 mock (``now_fn``) 으로 step duration 흐름 제어 — 실제 sleep 없이 검증.

검증 항목:
- initialise: step 0 의 각도 즉시 publish
- update: step_duration 안엔 RUNNING, 초과 시 다음 step publish
- 마지막 step 끝나면 SUCCESS
- terminate(INVALID): center() 1회 호출
- terminate(SUCCESS): center() 호출 안 함 (마지막 step 이 이미 90)
- 잘못된 steps_deg / step_duration 거부
- 커스텀 steps_deg / step_duration 동작
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from py_trees.common import Status

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "controller" / "gogoping-controller" / "src" / "gogoping" / "gogoping_modes"))

from gogoping_modes.bt.behaviors.follow.pan_camera_sweep import (  # noqa: E402
    DEFAULT_STEPS_DEG,
    DEFAULT_STEP_DURATION_SEC,
    PanCameraSweep,
)


class FakeClock:
    """주입형 시간 — 명시적으로 advance() 해서 step 전환 trigger."""
    def __init__(self, start: float = 100.0) -> None:
        self.t = start

    def now(self) -> float:
        return self.t

    def advance(self, sec: float) -> None:
        self.t += sec


def _ctx_with_mock_camera_pan():
    ctx = MagicMock()
    ctx.camera_pan = MagicMock()
    ctx.camera_pan.publish_pan = MagicMock()
    ctx.camera_pan.center = MagicMock()
    return ctx


def test_initialise_publishes_first_step():
    clock = FakeClock()
    ctx = _ctx_with_mock_camera_pan()
    b = PanCameraSweep("sweep", ctx, now_fn=clock.now)
    b.initialise()
    # 첫 step = 90.0 즉시 publish
    ctx.camera_pan.publish_pan.assert_called_once_with(90.0)


def test_update_running_within_step_duration():
    clock = FakeClock()
    ctx = _ctx_with_mock_camera_pan()
    b = PanCameraSweep("sweep", ctx, now_fn=clock.now)
    b.initialise()
    ctx.camera_pan.publish_pan.reset_mock()  # initialise 의 호출 무시
    # step_duration 미만 — RUNNING + publish 추가 없음
    clock.advance(0.5)
    assert b.update() == Status.RUNNING
    clock.advance(0.9)
    assert b.update() == Status.RUNNING
    ctx.camera_pan.publish_pan.assert_not_called()


def test_update_advances_to_next_step_after_duration():
    clock = FakeClock()
    ctx = _ctx_with_mock_camera_pan()
    b = PanCameraSweep("sweep", ctx, now_fn=clock.now)
    b.initialise()
    ctx.camera_pan.publish_pan.reset_mock()
    # 첫 step 이상 흘리면 다음 step (30°) publish
    clock.advance(DEFAULT_STEP_DURATION_SEC + 0.01)
    assert b.update() == Status.RUNNING
    ctx.camera_pan.publish_pan.assert_called_once_with(30.0)


def test_full_sweep_returns_success_after_all_steps():
    clock = FakeClock()
    ctx = _ctx_with_mock_camera_pan()
    b = PanCameraSweep("sweep", ctx, now_fn=clock.now)
    b.initialise()
    # 첫 step publish 외에 다른 publish 들 모두 record
    published = [c.args[0] for c in ctx.camera_pan.publish_pan.call_args_list]
    assert published == [90.0]

    # step 0 → 1 (30)
    clock.advance(DEFAULT_STEP_DURATION_SEC + 0.01)
    assert b.update() == Status.RUNNING
    # step 1 → 2 (150)
    clock.advance(DEFAULT_STEP_DURATION_SEC + 0.01)
    assert b.update() == Status.RUNNING
    # step 2 → 3 (90)
    clock.advance(DEFAULT_STEP_DURATION_SEC + 0.01)
    assert b.update() == Status.RUNNING
    # step 3 끝 → SUCCESS, 추가 publish 없음
    clock.advance(DEFAULT_STEP_DURATION_SEC + 0.01)
    assert b.update() == Status.SUCCESS

    published_all = [c.args[0] for c in ctx.camera_pan.publish_pan.call_args_list]
    # 4개 step 모두 publish (시퀀스 그대로)
    assert published_all == [90.0, 30.0, 150.0, 90.0]


def test_terminate_invalid_centers():
    clock = FakeClock()
    ctx = _ctx_with_mock_camera_pan()
    b = PanCameraSweep("sweep", ctx, now_fn=clock.now)
    b.initialise()
    # 중간에 cancel — terminate(INVALID)
    b.terminate(Status.INVALID)
    ctx.camera_pan.center.assert_called_once_with()


def test_terminate_success_does_not_center():
    clock = FakeClock()
    ctx = _ctx_with_mock_camera_pan()
    b = PanCameraSweep("sweep", ctx, now_fn=clock.now)
    b.initialise()
    b.terminate(Status.SUCCESS)
    ctx.camera_pan.center.assert_not_called()


def test_terminate_failure_does_not_center():
    clock = FakeClock()
    ctx = _ctx_with_mock_camera_pan()
    b = PanCameraSweep("sweep", ctx, now_fn=clock.now)
    b.initialise()
    b.terminate(Status.FAILURE)
    ctx.camera_pan.center.assert_not_called()


def test_publish_exception_swallowed():
    """publish_pan 이 예외 던져도 update 가 죽지 않음 (log only)."""
    clock = FakeClock()
    ctx = _ctx_with_mock_camera_pan()
    ctx.camera_pan.publish_pan.side_effect = RuntimeError("publisher down")
    b = PanCameraSweep("sweep", ctx, now_fn=clock.now)
    b.initialise()  # exception swallowed
    clock.advance(DEFAULT_STEP_DURATION_SEC + 0.01)
    assert b.update() == Status.RUNNING  # 예외 무시 + 다음 step 시도


def test_invalid_steps_rejected():
    ctx = _ctx_with_mock_camera_pan()
    with pytest.raises(ValueError):
        PanCameraSweep("sweep", ctx, steps_deg=())


def test_invalid_duration_rejected():
    ctx = _ctx_with_mock_camera_pan()
    with pytest.raises(ValueError):
        PanCameraSweep("sweep", ctx, step_duration_sec=0.0)
    with pytest.raises(ValueError):
        PanCameraSweep("sweep", ctx, step_duration_sec=-1.0)


def test_custom_steps_and_duration():
    clock = FakeClock()
    ctx = _ctx_with_mock_camera_pan()
    b = PanCameraSweep(
        "sweep", ctx,
        steps_deg=(60.0, 120.0),
        step_duration_sec=0.5,
        now_fn=clock.now,
    )
    b.initialise()
    assert ctx.camera_pan.publish_pan.call_args_list[-1].args[0] == 60.0
    clock.advance(0.6)
    assert b.update() == Status.RUNNING
    assert ctx.camera_pan.publish_pan.call_args_list[-1].args[0] == 120.0
    clock.advance(0.6)
    assert b.update() == Status.SUCCESS


def test_default_constants_match():
    assert DEFAULT_STEPS_DEG == (90.0, 30.0, 150.0, 90.0)
    assert DEFAULT_STEP_DURATION_SEC == 1.5


def test_reinitialise_resets_to_step_0():
    """terminate 후 다시 활성화되면 step 0 부터 재시작."""
    clock = FakeClock()
    ctx = _ctx_with_mock_camera_pan()
    b = PanCameraSweep("sweep", ctx, now_fn=clock.now)
    b.initialise()
    clock.advance(DEFAULT_STEP_DURATION_SEC + 0.01)
    b.update()  # step 1 (30)
    b.terminate(Status.INVALID)
    ctx.camera_pan.publish_pan.reset_mock()

    # 재 initialise — step 0 부터
    b.initialise()
    assert ctx.camera_pan.publish_pan.call_args_list[-1].args[0] == 90.0
