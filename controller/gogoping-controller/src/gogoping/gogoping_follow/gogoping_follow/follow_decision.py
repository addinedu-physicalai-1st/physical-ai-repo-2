"""Follow control state machine — distance-based mode with hysteresis + RECOVERY.

Pure Python — no rclpy. Imported by `follow_node` and unit tests.

Modes:
- IDLE: 아직 첫 sample 없음 / target 없음
- STOP: distance < stop_max (충돌 회피)
- REACTIVE: stop_max ≤ distance ≤ reactive_max — moca 식 cmd_vel P-control
- NAV2: distance > nav2_min — Nav2 NavigateToPose
- RECOVERY: not_tracking 이 recovery_lost_timeout_s 이상 지속 — graph PAN 스캔
- WAITING_HINT: RECOVERY 도 실패 — 음성 hint 무한 대기 (follow_node 가 따로 set)

REACTIVE ↔ NAV2 hysteresis: nav2_min~reactive_max 구간은 현재 mode 유지.
RECOVERY 진입은 active mode (REACTIVE/NAV2/STOP) 에서 NaN distance 가 지속될 때.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class DecisionMode(Enum):
    IDLE = "idle"
    STOP = "stop"
    REACTIVE = "reactive"
    NAV2 = "nav2"
    RECOVERY = "recovery"
    WAITING_HINT = "waiting_hint"
    VOICE_SEARCH = "voice_search"
    VOICE_FOUND = "voice_found"
    VOICE_RESUME = "voice_resume"


# Voice-guided mode 는 외부 hint / 내부 _tick 으로만 전이 — distance 무관.
_VOICE_MODES = frozenset({
    DecisionMode.VOICE_SEARCH,
    DecisionMode.VOICE_FOUND,
    DecisionMode.VOICE_RESUME,
})


@dataclass(frozen=True)
class Decision:
    mode: DecisionMode


def decide_follow_action(
    distance_m: float,
    prev_mode: DecisionMode,
    stop_max: float,
    reactive_max: float,
    nav2_min: float,
    initial_threshold: float,
    lost_duration_s: float = 0.0,
    recovery_lost_timeout_s: float = 2.0,
) -> Decision:
    """Distance + prev_mode + lost_duration → next mode.

    NaN distance + active mode + lost_duration ≥ timeout → RECOVERY 진입.
    NaN distance + IDLE/RECOVERY/WAITING_HINT → prev_mode 유지.
    그 외 NaN distance → prev_mode 유지.

    Active 거리 기반 분기 (기존 hybrid 로직):
    - distance < stop_max → STOP
    - prev=REACTIVE: distance > reactive_max → NAV2, else REACTIVE
    - prev=NAV2:     distance < nav2_min → REACTIVE, else NAV2
    - prev=IDLE/STOP/etc: distance < initial_threshold → REACTIVE, else NAV2
    """
    # Voice-guided mode 는 distance 와 무관하게 prev 유지 (전이는 _on_hint / _tick).
    if prev_mode in _VOICE_MODES:
        return Decision(mode=prev_mode)

    if math.isnan(distance_m):
        # NaN distance — tracking 없음.
        # active mode 였고 lost 가 임계 초과 → RECOVERY
        active_modes = {DecisionMode.STOP, DecisionMode.REACTIVE, DecisionMode.NAV2}
        if prev_mode in active_modes and lost_duration_s >= recovery_lost_timeout_s:
            return Decision(mode=DecisionMode.RECOVERY)
        # 그 외 (IDLE/RECOVERY/WAITING_HINT/짧은 lost) → prev 유지
        return Decision(mode=prev_mode)

    # 1) STOP 영역은 mode 무관 즉시
    if distance_m < stop_max:
        return Decision(mode=DecisionMode.STOP)

    # 2) hysteresis — 현 mode 따라 다른 임계
    if prev_mode == DecisionMode.REACTIVE:
        if distance_m > reactive_max:
            return Decision(mode=DecisionMode.NAV2)
        return Decision(mode=DecisionMode.REACTIVE)

    if prev_mode == DecisionMode.NAV2:
        if distance_m < nav2_min:
            return Decision(mode=DecisionMode.REACTIVE)
        return Decision(mode=DecisionMode.NAV2)

    # 3) IDLE/STOP/RECOVERY/WAITING_HINT 에서 ACTIVE 진입 (distance 정상 회복) — 중앙값으로 결정
    if distance_m < initial_threshold:
        return Decision(mode=DecisionMode.REACTIVE)
    return Decision(mode=DecisionMode.NAV2)
