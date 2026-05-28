"""Unit tests for close_follow — doorway 거리 + hysteresis."""
import pytest

from gogoping_follow.close_follow import (
    CloseFollowState,
    evaluate_close_follow,
    is_doorway_vertex,
    nearest_doorway_distance,
)


# ---------- is_doorway_vertex ----------
def test_doorway_입구_match():
    assert is_doorway_vertex("출입구") is True
    assert is_doorway_vertex("출입구2") is True
    assert is_doorway_vertex("놀이방입구_상") is True
    assert is_doorway_vertex("놀이방입구_하2") is True
    assert is_doorway_vertex("수면실입구") is True
    assert is_doorway_vertex("충전소입구") is True


def test_doorway_non_doorway():
    assert is_doorway_vertex("운동장2") is False
    assert is_doorway_vertex("복도3") is False
    assert is_doorway_vertex("수면실") is False
    assert is_doorway_vertex("") is False


# ---------- nearest_doorway_distance ----------
def test_nearest_doorway_empty_returns_none():
    assert nearest_doorway_distance(0.0, 0.0, []) is None


def test_nearest_doorway_single():
    # 단일 doorway: (3, 4) → 거리 5
    d = nearest_doorway_distance(0.0, 0.0, [("출입구", 3.0, 4.0)])
    assert d == pytest.approx(5.0)


def test_nearest_doorway_min_of_multiple():
    doorways = [
        ("출입구", 10.0, 0.0),       # 거리 10
        ("놀이방입구_상", 1.0, 0.0),   # 거리 1
        ("수면실입구", 5.0, 0.0),     # 거리 5
    ]
    d = nearest_doorway_distance(0.0, 0.0, doorways)
    assert d == pytest.approx(1.0)


# ---------- evaluate_close_follow ----------
P_ARGS = dict(
    trigger_dist=1.5,
    release_dist=2.0,
    angle_stable_deg=15.0,
    angle_stable_s=1.0,
)


def test_close_off_near_doorway_activates():
    state = CloseFollowState(active=False)
    new_state = evaluate_close_follow(
        prev=state, doorway_dist=1.0, angle_deg=5.0, now=10.0, **P_ARGS,
    )
    assert new_state.active is True


def test_close_off_far_doorway_stays_off():
    state = CloseFollowState(active=False)
    new_state = evaluate_close_follow(
        prev=state, doorway_dist=1.8, angle_deg=5.0, now=10.0, **P_ARGS,
    )
    # 1.8 > TRIGGER (1.5) — inactive 유지
    assert new_state.active is False


def test_close_on_hysteresis_zone_stays_on():
    state = CloseFollowState(active=True)
    new_state = evaluate_close_follow(
        prev=state, doorway_dist=1.8, angle_deg=5.0, now=10.0, **P_ARGS,
    )
    # 1.8 < RELEASE (2.0) — active 유지 (hysteresis)
    assert new_state.active is True


def test_close_on_far_but_angle_unstable_stays_on():
    state = CloseFollowState(active=True, angle_stable_since=None)
    new_state = evaluate_close_follow(
        prev=state, doorway_dist=3.0, angle_deg=25.0, now=10.0, **P_ARGS,
    )
    # 3.0 > RELEASE 이지만 angle 25° > STABLE_DEG (15°) — active 유지
    assert new_state.active is True
    assert new_state.angle_stable_since is None  # 안정 구간 시작 안 됨


def test_close_on_far_angle_stable_short_stays_on():
    # angle 안정은 시작했지만 1초 안 됨
    state = CloseFollowState(active=True, angle_stable_since=9.5)
    new_state = evaluate_close_follow(
        prev=state, doorway_dist=3.0, angle_deg=5.0, now=10.0, **P_ARGS,
    )
    # 10.0 - 9.5 = 0.5s < 1.0s — active 유지
    assert new_state.active is True
    assert new_state.angle_stable_since == 9.5  # 안정 시작 보존


def test_close_on_far_angle_stable_enough_releases():
    state = CloseFollowState(active=True, angle_stable_since=9.0)
    new_state = evaluate_close_follow(
        prev=state, doorway_dist=3.0, angle_deg=5.0, now=10.5, **P_ARGS,
    )
    # 10.5 - 9.0 = 1.5s ≥ 1.0s + dist 3.0 > RELEASE — release
    assert new_state.active is False


def test_close_on_no_doorway_releases_immediately():
    state = CloseFollowState(active=True)
    new_state = evaluate_close_follow(
        prev=state, doorway_dist=None, angle_deg=5.0, now=10.0, **P_ARGS,
    )
    # doorway 정보 없음 (graph 로드 실패 등) → 안전 default: inactive
    assert new_state.active is False
