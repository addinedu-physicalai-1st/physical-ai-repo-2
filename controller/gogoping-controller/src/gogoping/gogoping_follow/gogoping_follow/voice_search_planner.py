"""Voice-guided search PAN sweep + resume base 회전 — pure 함수.

호출자: follow_node 의 _tick_voice_search / _tick_voice_resume.

Sweep 시퀀스: home(90°) → 좌측 끝(5°) → 우측 끝(175°) → home(90°) 양방향 1회.
발견 시 즉시 정지는 호출자 (follow_node) 책임.

Resume yaw: 발견된 PAN angle → base_link 회전 yaw.
  PAN < 90° → 우회전 (음수 yaw), PAN > 90° → 좌회전 (양수 yaw).
"""
from __future__ import annotations

import math
from enum import Enum


class SweepPhase(Enum):
    TO_HOME_START = "to_home_start"   # 진입 시 home 으로 가는 단계
    TO_LEFT = "to_left"               # home → 좌측 끝
    TO_RIGHT = "to_right"             # 좌측 끝 → 우측 끝
    TO_HOME_END = "to_home_end"       # 우측 끝 → home (sweep 끝)
    DONE = "done"


_PHASE_NEXT = {
    SweepPhase.TO_HOME_START: SweepPhase.TO_LEFT,
    SweepPhase.TO_LEFT: SweepPhase.TO_RIGHT,
    SweepPhase.TO_RIGHT: SweepPhase.TO_HOME_END,
    SweepPhase.TO_HOME_END: SweepPhase.DONE,
}


def _target_for_phase(
    phase: SweepPhase, pan_home: float, pan_left: float, pan_right: float,
) -> float | None:
    if phase == SweepPhase.TO_HOME_START:
        return pan_home
    if phase == SweepPhase.TO_LEFT:
        return pan_left
    if phase == SweepPhase.TO_RIGHT:
        return pan_right
    if phase == SweepPhase.TO_HOME_END:
        return pan_home
    return None  # DONE


def compute_voice_sweep_step(
    current: float,
    phase: SweepPhase,
    rate: float,
    dt: float,
    pan_home: float,
    pan_left: float,
    pan_right: float,
) -> tuple[float, SweepPhase]:
    """한 tick 의 PAN sweep — (next_pan, next_phase) 반환.

    target 도달 시 next phase 로 전이. DONE 은 그대로 유지.
    """
    if phase == SweepPhase.DONE:
        return current, SweepPhase.DONE
    target = _target_for_phase(phase, pan_home, pan_left, pan_right)
    assert target is not None
    diff = target - current
    max_step = rate * dt
    if abs(diff) <= max_step:
        # 도달 — 다음 phase
        return target, _PHASE_NEXT[phase]
    step = max_step if diff > 0 else -max_step
    return current + step, phase


def compute_voice_resume_yaw(pan_found: float) -> float:
    """발견 시점의 PAN angle → robot base 가 회전해야 할 yaw (rad).

    PAN 좌표계: 5° (왼쪽 끝) — 90° (home/정면) — 175° (오른쪽 끝)
    Yaw: + (CCW, 좌회전) / − (CW, 우회전).
    PAN 30° (우측) → yaw = -60°. PAN 150° (좌측) → yaw = +60°.
    """
    return math.radians(pan_found - 90.0)
