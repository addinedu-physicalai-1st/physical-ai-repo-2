"""Close-Follow lost-prevention — doorway 근처에서 추종 거리 일시 단축.

순수함수 모듈 — rclpy 없음. follow_node 가 호출.

Doorway 정의: waypoints.yaml 의 vertex name 에 "입구" 또는 "출입구" 포함.
Hysteresis: TRIGGER_DIST 미만 → ON, RELEASE_DIST 초과 + angle 안정 → OFF.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


def is_doorway_vertex(name: str) -> bool:
    """vertex name 이 doorway 인지 판정."""
    return "입구" in name or "출입구" in name


@dataclass
class CloseFollowState:
    """follow_node 가 보관하는 close-follow 상태."""
    active: bool = False
    angle_stable_since: float | None = None  # 안정 구간 시작 시각 (None = 안정 아님)


def nearest_doorway_distance(
    rx: float, ry: float, doorway_vertices: list[tuple[str, float, float]]
) -> float | None:
    """robot (rx, ry) 에서 가장 가까운 doorway vertex 까지 거리. doorway 없으면 None."""
    if not doorway_vertices:
        return None
    return min(math.hypot(vx - rx, vy - ry) for _name, vx, vy in doorway_vertices)


def should_force_nav2_at_doorway(
    doorway_dist: float | None,
    in_nav2: bool,
    trigger_dist: float,
    release_dist: float,
) -> bool:
    """doorway 근처에서 REACTIVE 대신 NAV2(costmap 회피) 를 강제할지.

    hysteresis: 진입은 trigger_dist, 유지는 release_dist (경계 AMCL 지터 flapping 방지).
    doorway_dist None (localization 없음 / doorway 미정의) → False.
    """
    if doorway_dist is None:
        return False
    threshold = release_dist if in_nav2 else trigger_dist
    return doorway_dist < threshold


def evaluate_close_follow(
    prev: CloseFollowState,
    doorway_dist: float | None,
    angle_deg: float,
    now: float,
    trigger_dist: float,
    release_dist: float,
    angle_stable_deg: float,
    angle_stable_s: float,
) -> CloseFollowState:
    """현재 close-follow 활성 여부 결정.

    OFF→ON: doorway_dist < trigger_dist
    ON→OFF: doorway_dist > release_dist AND angle 안정 시간 ≥ angle_stable_s
    그 외: prev 유지 (hysteresis)
    doorway_dist=None (graph 로드 실패) 시 항상 inactive.
    """
    # graph 정보 없음 → 안전 default
    if doorway_dist is None:
        return CloseFollowState(active=False, angle_stable_since=None)

    # OFF → ON
    if not prev.active:
        if doorway_dist < trigger_dist:
            return CloseFollowState(active=True, angle_stable_since=None)
        return CloseFollowState(active=False, angle_stable_since=None)

    # active 유지/해제 판정 — release 영역 + angle 안정
    angle_is_stable = abs(angle_deg) < angle_stable_deg
    in_release_zone = doorway_dist > release_dist

    # angle 안정 시작/유지/리셋
    if angle_is_stable:
        stable_since = prev.angle_stable_since if prev.angle_stable_since is not None else now
    else:
        stable_since = None  # 흔들리면 리셋

    # ON → OFF 조건: release 영역 + angle 안정 충분 시간
    if in_release_zone and stable_since is not None and (now - stable_since) >= angle_stable_s:
        return CloseFollowState(active=False, angle_stable_since=None)

    return CloseFollowState(active=True, angle_stable_since=stable_since)
