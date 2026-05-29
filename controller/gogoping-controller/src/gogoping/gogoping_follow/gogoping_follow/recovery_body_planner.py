"""Recovery body-search state machine — pure 함수.

호출자: follow_node 의 _tick_recovery.

State:
    FULL_SWEEP   — PAN 풀 sweep (좌150° ↔ 우30°). 진입 시 현재 PAN 반대 끝으로.
    BODY_TURN    — 본체 25° 회전. 방향 = sweep 종료 PAN 위치 쪽.
                   (PAN 30° → 우회전 yaw_dir=-1, PAN 150° → 좌회전 yaw_dir=+1)
    NARROW_SWEEP — PAN 정면 ±half_deg (45°↔135°). BODY_TURN 후 카메라만 좌우 검사.
    EXHAUSTED   — 본체 누적 회전 ≥ MAX. 호출자가 WAITING_HINT 로 전이.

호출자 책임:
- perception 사람 인식 시 follow 모드로 복귀
- cmd_vel publish (BODY_TURN 동안 angular.z = rate × yaw_dir)
- PAN publish (FULL/NARROW_SWEEP 동안 compute_pan_step 결과)
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import radians


class BodyPhase(Enum):
    FULL_SWEEP = "full_sweep"
    BODY_TURN = "body_turn"
    NARROW_SWEEP = "narrow_sweep"
    EXHAUSTED = "exhausted"


@dataclass
class BodyState:
    phase: BodyPhase
    pan_target_deg: float           # 현재 sweep 목표 PAN
    yaw_dir: int                    # +1 (CCW/좌) / -1 (CW/우) / 0
    body_turn_remaining_rad: float  # BODY_TURN 진행 중 남은 yaw (양수)
    total_body_turn_deg: float      # 누적 본체 회전 (절대값)


def initial_state(
    current_pan_deg: float,
    pan_left_deg: float,
    pan_right_deg: float,
) -> BodyState:
    """진입 시 FULL_SWEEP, 현재 PAN 의 반대 끝으로 (긴 sweep 확보)."""
    mid = (pan_left_deg + pan_right_deg) / 2.0
    target = pan_left_deg if current_pan_deg <= mid else pan_right_deg
    return BodyState(
        phase=BodyPhase.FULL_SWEEP,
        pan_target_deg=target,
        yaw_dir=0,
        body_turn_remaining_rad=0.0,
        total_body_turn_deg=0.0,
    )


def _yaw_dir_from_pan(
    pan_at_end: float, pan_left_deg: float, pan_right_deg: float,
) -> int:
    """sweep 종료 PAN 이 좌측 끝 가까우면 좌회전 (+1), 우측 가까우면 우회전 (-1)."""
    if abs(pan_at_end - pan_left_deg) < abs(pan_at_end - pan_right_deg):
        return +1
    return -1


def on_sweep_complete(
    state: BodyState,
    pan_left_deg: float,
    pan_right_deg: float,
    body_turn_deg: float,
    body_max_total_deg: float,
) -> BodyState:
    """FULL/NARROW_SWEEP 종료 → BODY_TURN, 누적 초과면 EXHAUSTED."""
    if state.phase == BodyPhase.BODY_TURN:
        return state
    next_total = state.total_body_turn_deg + body_turn_deg
    if next_total > body_max_total_deg:
        return BodyState(
            phase=BodyPhase.EXHAUSTED,
            pan_target_deg=state.pan_target_deg,
            yaw_dir=0,
            body_turn_remaining_rad=0.0,
            total_body_turn_deg=state.total_body_turn_deg,
        )
    yaw_dir = _yaw_dir_from_pan(state.pan_target_deg, pan_left_deg, pan_right_deg)
    return BodyState(
        phase=BodyPhase.BODY_TURN,
        pan_target_deg=state.pan_target_deg,  # 회전 중 PAN 유지
        yaw_dir=yaw_dir,
        body_turn_remaining_rad=radians(body_turn_deg),
        total_body_turn_deg=next_total,
    )


def on_body_turn_complete(
    state: BodyState,
    current_pan_deg: float,
    narrow_pan_front_deg: float,
    narrow_pan_half_deg: float,
) -> BodyState:
    """BODY_TURN 종료 → NARROW_SWEEP. 첫 target 은 현재 PAN 의 반대 끝."""
    left = narrow_pan_front_deg + narrow_pan_half_deg
    right = narrow_pan_front_deg - narrow_pan_half_deg
    target = left if current_pan_deg <= narrow_pan_front_deg else right
    return BodyState(
        phase=BodyPhase.NARROW_SWEEP,
        pan_target_deg=target,
        yaw_dir=0,
        body_turn_remaining_rad=0.0,
        total_body_turn_deg=state.total_body_turn_deg,
    )


def on_narrow_sweep_reach_target(
    state: BodyState,
    narrow_pan_front_deg: float,
    narrow_pan_half_deg: float,
) -> BodyState:
    """NARROW_SWEEP 한 끝 도달 → 반대 끝으로 전환."""
    left = narrow_pan_front_deg + narrow_pan_half_deg
    right = narrow_pan_front_deg - narrow_pan_half_deg
    new_target = right if abs(state.pan_target_deg - left) < 0.5 else left
    return BodyState(
        phase=BodyPhase.NARROW_SWEEP,
        pan_target_deg=new_target,
        yaw_dir=0,
        body_turn_remaining_rad=0.0,
        total_body_turn_deg=state.total_body_turn_deg,
    )


def compute_pan_step(
    current_deg: float, target_deg: float, rate_deg_s: float, dt: float,
) -> tuple[float, bool]:
    """한 tick 의 PAN 이동 — (next_pan, reached)."""
    diff = target_deg - current_deg
    max_step = rate_deg_s * dt
    if abs(diff) <= max_step:
        return target_deg, True
    step = max_step if diff > 0 else -max_step
    return current_deg + step, False


def consume_body_turn(
    state: BodyState, rate_rad_s: float, dt: float,
) -> tuple[BodyState, bool]:
    """BODY_TURN 한 tick — (next_state, completed). completed=True 면 호출자가 phase 전이."""
    assert state.phase == BodyPhase.BODY_TURN
    step = rate_rad_s * dt
    remaining = state.body_turn_remaining_rad - step
    if remaining <= 0:
        return (
            BodyState(
                phase=BodyPhase.BODY_TURN,
                pan_target_deg=state.pan_target_deg,
                yaw_dir=state.yaw_dir,
                body_turn_remaining_rad=0.0,
                total_body_turn_deg=state.total_body_turn_deg,
            ),
            True,
        )
    return (
        BodyState(
            phase=BodyPhase.BODY_TURN,
            pan_target_deg=state.pan_target_deg,
            yaw_dir=state.yaw_dir,
            body_turn_remaining_rad=remaining,
            total_body_turn_deg=state.total_body_turn_deg,
        ),
        False,
    )
