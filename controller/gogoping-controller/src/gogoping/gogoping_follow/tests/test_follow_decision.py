"""Unit tests for follow_decision.decide_follow_action (hybrid mode + hysteresis)."""
import math

from gogoping_follow.follow_decision import DecisionMode, decide_follow_action


# Reusable threshold args matching config.py defaults
THRESHOLDS = dict(
    stop_max=0.35,
    reactive_max=1.2,
    nav2_min=0.8,
    initial_threshold=1.0,
)


def _decide(distance_m, prev_mode):
    return decide_follow_action(distance_m=distance_m, prev_mode=prev_mode, **THRESHOLDS).mode


# ── initial mode (from IDLE / STOP) ─────────────────────────────────────────
def test_initial_stop_when_very_close():
    assert _decide(0.30, DecisionMode.IDLE) == DecisionMode.STOP


def test_initial_reactive_when_under_initial_threshold():
    assert _decide(0.90, DecisionMode.IDLE) == DecisionMode.REACTIVE


def test_initial_nav2_when_over_initial_threshold():
    assert _decide(1.50, DecisionMode.IDLE) == DecisionMode.NAV2


def test_initial_boundary_exactly_at_threshold_picks_nav2():
    # distance == initial_threshold (1.0) -> NAV2 by '>= threshold' rule
    assert _decide(1.00, DecisionMode.IDLE) == DecisionMode.NAV2


# ── STOP transitions ────────────────────────────────────────────────────────
def test_stop_stays_when_still_too_close():
    assert _decide(0.30, DecisionMode.STOP) == DecisionMode.STOP


def test_stop_to_reactive_when_distance_grows():
    assert _decide(0.50, DecisionMode.STOP) == DecisionMode.REACTIVE


def test_stop_to_nav2_when_distance_jumps_far():
    assert _decide(1.50, DecisionMode.STOP) == DecisionMode.NAV2


# ── REACTIVE hysteresis ─────────────────────────────────────────────────────
def test_reactive_stays_just_below_upper_hysteresis():
    # 1.19m < 1.2m → stay REACTIVE
    assert _decide(1.19, DecisionMode.REACTIVE) == DecisionMode.REACTIVE


def test_reactive_to_nav2_above_upper_hysteresis():
    # 1.21m > 1.2m → switch to NAV2
    assert _decide(1.21, DecisionMode.REACTIVE) == DecisionMode.NAV2


def test_reactive_to_stop_below_stop_max():
    assert _decide(0.30, DecisionMode.REACTIVE) == DecisionMode.STOP


def test_reactive_stays_at_settle_distance():
    assert _decide(0.5, DecisionMode.REACTIVE) == DecisionMode.REACTIVE


# ── NAV2 hysteresis ─────────────────────────────────────────────────────────
def test_nav2_stays_just_above_lower_hysteresis():
    # 0.81m > 0.8m → stay NAV2
    assert _decide(0.81, DecisionMode.NAV2) == DecisionMode.NAV2


def test_nav2_to_reactive_below_lower_hysteresis():
    # 0.79m < 0.8m → switch to REACTIVE
    assert _decide(0.79, DecisionMode.NAV2) == DecisionMode.REACTIVE


def test_nav2_to_stop_when_very_close():
    assert _decide(0.30, DecisionMode.NAV2) == DecisionMode.STOP


# ── overlap zone 0.8~1.2m: depends on prev_mode ────────────────────────────
def test_overlap_zone_keeps_reactive():
    assert _decide(1.00, DecisionMode.REACTIVE) == DecisionMode.REACTIVE


def test_overlap_zone_keeps_nav2():
    assert _decide(1.00, DecisionMode.NAV2) == DecisionMode.NAV2


# ── NaN distance preserves prev_mode (depth invalid frame) ─────────────────
def test_nan_keeps_previous_mode_reactive():
    assert _decide(float("nan"), DecisionMode.REACTIVE) == DecisionMode.REACTIVE


def test_nan_keeps_previous_mode_nav2():
    assert _decide(float("nan"), DecisionMode.NAV2) == DecisionMode.NAV2


def test_nan_keeps_idle():
    assert _decide(float("nan"), DecisionMode.IDLE) == DecisionMode.IDLE


# ── Phase E — RECOVERY / WAITING_HINT ──────────────────────────────────────
def test_decision_mode_has_recovery_and_waiting_hint():
    assert DecisionMode.RECOVERY.value == "recovery"
    assert DecisionMode.WAITING_HINT.value == "waiting_hint"


def test_active_mode_to_recovery_on_lost_timeout():
    # active mode (REACTIVE) 에서 NaN distance + lost_duration >= timeout → RECOVERY
    d = decide_follow_action(
        distance_m=float("nan"),
        prev_mode=DecisionMode.REACTIVE,
        stop_max=0.35,
        reactive_max=1.2,
        nav2_min=0.8,
        initial_threshold=1.0,
        lost_duration_s=2.5,
        recovery_lost_timeout_s=2.0,
    )
    assert d.mode == DecisionMode.RECOVERY


def test_lost_duration_below_threshold_stays_in_mode():
    # tracking 잃었지만 1.5s 만 지속 → prev_mode 유지 (NaN distance 정책)
    d = decide_follow_action(
        distance_m=float("nan"),
        prev_mode=DecisionMode.REACTIVE,
        stop_max=0.35,
        reactive_max=1.2,
        nav2_min=0.8,
        initial_threshold=1.0,
        lost_duration_s=1.5,
        recovery_lost_timeout_s=2.0,
    )
    assert d.mode == DecisionMode.REACTIVE


def test_idle_with_lost_timeout_stays_idle():
    # IDLE 에서 lost_duration 무관 — IDLE 그대로 (RECOVERY 진입 X)
    d = decide_follow_action(
        distance_m=float("nan"),
        prev_mode=DecisionMode.IDLE,
        stop_max=0.35,
        reactive_max=1.2,
        nav2_min=0.8,
        initial_threshold=1.0,
        lost_duration_s=5.0,
        recovery_lost_timeout_s=2.0,
    )
    assert d.mode == DecisionMode.IDLE
