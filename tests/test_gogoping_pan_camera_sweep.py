"""PanCameraSweep behavior 단위 테스트 — rate(°/s) 기반 pan + step별 hold + tilt 브래킷.

시간 mock (``now_fn``) 으로 흐름 제어 — 실제 sleep 없이 검증.

숨바꼭질 탐색 1회(지점당):
  tilt → 130° 설정
  pan 90→10 (4초) → 5초 hold
  pan 10→170 (8초) → 5초 hold
  pan 170→90 (4초)  ← hold 없음
  tilt → 원래 각도(90°) 복원

검증 항목:
- 이동(move) 은 일정 속도 보간: 80°→4초, 160°→8초
- step별 hold (예: 0,5,5,0 — 좌·우만 5초, 중앙은 0)
- 전체 시퀀스 종료 시 SUCCESS
- tilt_deg 지정 시 initialise 에서 설정 / terminate 에서 rest 로 복원
- tilt_deg 미지정 시 tilt 토픽 미사용
- terminate(INVALID): pan center() 호출, terminate(SUCCESS/FAILURE): 미호출
- 잘못된 steps_deg / speed / hold 길이 거부
- 커스텀 steps / reinit / publish 예외 무시
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
    DEFAULT_HOLD_SECS,
    DEFAULT_PAN_SPEED_DEG_PER_S,
    DEFAULT_STEPS_DEG,
    PanCameraSweep,
)


class FakeClock:
    """주입형 시간 — ``t`` 를 직접 세팅하거나 advance() 로 진행."""
    def __init__(self, start: float = 0.0) -> None:
        self.t = start

    def now(self) -> float:
        return self.t

    def advance(self, sec: float) -> None:
        self.t += sec


def _ctx_with_mock_camera_pan():
    ctx = MagicMock()
    ctx.camera_pan = MagicMock()
    return ctx


def _make(steps=(90.0, 10.0, 170.0, 90.0), speed=20.0, holds=(0.0, 5.0, 5.0, 0.0),
          tilt_deg=None, rest_tilt=90.0):
    clock = FakeClock(0.0)
    ctx = _ctx_with_mock_camera_pan()
    b = PanCameraSweep(
        "sweep", ctx,
        steps_deg=steps,
        pan_speed_deg_per_s=speed,
        hold_secs=holds,
        tilt_deg=tilt_deg,
        rest_tilt_deg=rest_tilt,
        now_fn=clock.now,
    )
    return b, ctx, clock


def _last_pan(ctx) -> float:
    return ctx.camera_pan.publish_pan.call_args_list[-1].args[0]


# ---------- rate 기반 pan 이동 ----------

def test_center_to_side_interpolates_over_4s():
    """90→10 (80°) 은 20°/s 로 4초 — 2초째 50° 부근."""
    b, ctx, clk = _make((90.0, 10.0), holds=(0.0, 5.0))
    b.initialise()
    clk.t = 0.0
    assert b.update() == Status.RUNNING        # step0(hold0) 즉시 통과 → step1
    clk.t = 2.0
    b.update()
    assert abs(_last_pan(ctx) - 50.0) < 1e-6    # 90 + (10-90)*0.5


def test_side_to_side_move_lasts_8s():
    """10→170 (160°) 은 20°/s 로 8초 — 4초째 90°, 8초째 도달."""
    b, ctx, clk = _make((10.0, 170.0), holds=(0.0, 5.0))
    b.initialise()
    clk.t = 0.0
    b.update()                                  # → step1 (started 0)
    clk.t = 4.0
    b.update()
    assert abs(_last_pan(ctx) - 90.0) < 1e-6    # 10 + (170-10)*0.5
    clk.t = 7.9
    b.update()
    assert _last_pan(ctx) < 170.0               # 아직 이동 중
    clk.t = 8.0
    b.update()
    assert abs(_last_pan(ctx) - 170.0) < 1e-6   # 이동 완료


# ---------- step별 hold ----------

def test_step0_no_hold_and_sides_hold():
    """holds=(0,5,5,0): step0(정면) 즉시 통과, 좌(10)에서 5초 hold."""
    b, ctx, clk = _make()
    b.initialise()
    clk.t = 0.0
    b.update()                                  # step0 hold0 → step1
    clk.t = 4.0
    b.update()                                  # step1 이동 완료 (10)
    assert abs(_last_pan(ctx) - 10.0) < 1e-6
    clk.t = 8.9
    assert b.update() == Status.RUNNING         # 아직 hold 중 (4~9초)
    assert abs(_last_pan(ctx) - 10.0) < 1e-6


def test_full_sweep_succeeds_at_26s():
    """4+5+8+5+4 = 26초 후 SUCCESS."""
    b, _, clk = _make()
    b.initialise()
    clk.t = 0.0
    b.update()                                  # → step1
    for t in (9.0, 22.0):                       # step1 끝(9), step2 끝(22)
        clk.t = t
        assert b.update() == Status.RUNNING
    clk.t = 25.9
    assert b.update() == Status.RUNNING         # step3 이동 중
    clk.t = 26.0
    assert b.update() == Status.SUCCESS


# ---------- tilt 브래킷 ----------

def test_sets_tilt_at_start():
    b, ctx, _ = _make(tilt_deg=130.0)
    b.initialise()
    ctx.camera_pan.publish_tilt.assert_called_once_with(130.0)


def test_restores_tilt_on_success():
    b, ctx, _ = _make(tilt_deg=130.0, rest_tilt=90.0)
    b.initialise()
    b.terminate(Status.SUCCESS)
    assert ctx.camera_pan.publish_tilt.call_args_list[-1].args[0] == 90.0


def test_restores_tilt_and_centers_pan_on_cancel():
    b, ctx, _ = _make(tilt_deg=130.0, rest_tilt=90.0)
    b.initialise()
    b.terminate(Status.INVALID)
    ctx.camera_pan.center.assert_called_once_with()
    assert ctx.camera_pan.publish_tilt.call_args_list[-1].args[0] == 90.0


def test_no_tilt_commands_when_tilt_deg_none():
    b, ctx, _ = _make(tilt_deg=None)
    b.initialise()
    b.terminate(Status.SUCCESS)
    ctx.camera_pan.publish_tilt.assert_not_called()


# ---------- terminate (pan center 정책) ----------

def test_terminate_invalid_centers():
    b, ctx, _ = _make()
    b.initialise()
    b.terminate(Status.INVALID)
    ctx.camera_pan.center.assert_called_once_with()


def test_terminate_success_does_not_center():
    b, ctx, _ = _make()
    b.initialise()
    b.terminate(Status.SUCCESS)
    ctx.camera_pan.center.assert_not_called()


def test_terminate_failure_does_not_center():
    b, ctx, _ = _make()
    b.initialise()
    b.terminate(Status.FAILURE)
    ctx.camera_pan.center.assert_not_called()


# ---------- 검증 / 엣지 ----------

def test_invalid_steps_rejected():
    ctx = _ctx_with_mock_camera_pan()
    with pytest.raises(ValueError):
        PanCameraSweep("sweep", ctx, steps_deg=())


def test_invalid_speed_rejected():
    ctx = _ctx_with_mock_camera_pan()
    with pytest.raises(ValueError):
        PanCameraSweep("sweep", ctx, pan_speed_deg_per_s=0.0)
    with pytest.raises(ValueError):
        PanCameraSweep("sweep", ctx, pan_speed_deg_per_s=-1.0)


def test_hold_secs_length_mismatch_rejected():
    ctx = _ctx_with_mock_camera_pan()
    with pytest.raises(ValueError):
        PanCameraSweep("sweep", ctx, steps_deg=(90.0, 10.0), hold_secs=(1.0, 2.0, 3.0))


def test_scalar_hold_broadcasts_to_all_steps():
    """hold_secs 가 단일 float 면 전 step 동일 적용."""
    b, ctx, clk = _make((90.0, 10.0), holds=2.0)   # step0: 0+2, step1: 4+2 → 8초
    b.initialise()
    clk.t = 0.0
    b.update()                                      # step0 hold=2 → 아직 RUNNING
    clk.t = 2.0
    assert b.update() == Status.RUNNING             # step1 진입
    clk.t = 8.0
    assert b.update() == Status.SUCCESS             # 2 + 4 + 2 = 8초


def test_publish_exception_swallowed():
    """publish_pan 이 예외 던져도 죽지 않음 (log only)."""
    b, ctx, clk = _make((90.0, 10.0), holds=(0.0, 5.0))
    ctx.camera_pan.publish_pan.side_effect = RuntimeError("publisher down")
    b.initialise()                                  # 예외 swallow
    clk.t = 2.0
    assert b.update() == Status.RUNNING


def test_default_constants():
    assert DEFAULT_STEPS_DEG == (90.0, 10.0, 170.0, 90.0)
    assert DEFAULT_PAN_SPEED_DEG_PER_S == 20.0
    assert DEFAULT_HOLD_SECS == (0.0, 5.0, 5.0, 0.0)


def test_reinitialise_resets_to_step_0():
    """terminate 후 다시 활성화되면 step 0 부터 재시작."""
    b, ctx, clk = _make((90.0, 10.0), holds=(0.0, 5.0))
    b.initialise()
    clk.t = 0.0
    b.update()                                      # step1
    clk.t = 2.0
    b.update()                                      # 이동 중
    b.terminate(Status.INVALID)
    ctx.camera_pan.publish_pan.reset_mock()
    b.initialise()                                  # 재시작 → step0 = 90
    assert _last_pan(ctx) == 90.0
