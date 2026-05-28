"""Recovery — graph candidate + hint mapping + PAN slow-move.

순수함수 모듈 — rclpy 없음. follow_node 가 호출.

Candidate: robot 의 nearest_vertex 의 인접 vertex 들. 각 vertex 의
robot-frame yaw → PAN 각도 변환. PAN 범위 / max_dist 필터링 후 PAN center
proximity 로 정렬.

Hint: "left"|"right"|"front"|"back" → (pan_target, base_rotate, dwell)
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class RecoveryCandidate:
    vertex_name: str
    pan_deg: float       # 카메라 PAN 명령 (0~180, center=90)
    distance_m: float


@dataclass(frozen=True)
class HintAction:
    pan_target_deg: float
    base_rotate_rad: float  # 0 이면 base 회전 없음
    dwell_s: float


def compute_candidates(
    robot_xy: tuple[float, float],
    robot_yaw: float,
    adjacent_vertices: list[tuple[str, float, float]],
    max_dist: float,
    pan_min: float,
    pan_max: float,
) -> list[RecoveryCandidate]:
    """현재 nearest vertex 의 인접 vertex 들로부터 RECOVERY 후보 list.

    adjacent_vertices: [(name, vx, vy), ...] (map frame, robot frame 변환은 본 함수가 처리)
    return: PAN center(90°) 가까운 순으로 정렬된 list. 비어있으면 candidates 없음.
    """
    rx, ry = robot_xy
    out: list[RecoveryCandidate] = []
    for v_name, vx, vy in adjacent_vertices:
        dx, dy = vx - rx, vy - ry
        dist = math.hypot(dx, dy)
        if dist > max_dist:
            continue
        # base_link frame yaw = map frame bearing - robot yaw
        yaw_base = math.atan2(dy, dx) - robot_yaw
        # normalize to [-π, π]
        while yaw_base > math.pi:
            yaw_base -= 2 * math.pi
        while yaw_base < -math.pi:
            yaw_base += 2 * math.pi
        pan_deg = 90.0 + math.degrees(yaw_base)
        if pan_deg < pan_min or pan_deg > pan_max:
            continue
        out.append(RecoveryCandidate(
            vertex_name=v_name, pan_deg=pan_deg, distance_m=dist,
        ))
    # PAN center(90°) 가까운 순
    out.sort(key=lambda c: abs(c.pan_deg - 90.0))
    return out


def hint_to_action(
    hint: str,
    pan_left: float,
    pan_right: float,
    pan_front: float,
    back_turn_rate_rad_s: float,  # noqa: ARG001 — back 회전 속도, follow_node 가 사용
    dwell: float,
) -> HintAction | None:
    """hint string → (PAN target, base 사전회전, dwell) 매핑. unknown 은 None."""
    if hint == "right":
        return HintAction(pan_target_deg=pan_right, base_rotate_rad=0.0, dwell_s=dwell)
    if hint == "left":
        return HintAction(pan_target_deg=pan_left, base_rotate_rad=0.0, dwell_s=dwell)
    if hint == "front":
        return HintAction(pan_target_deg=pan_front, base_rotate_rad=0.0, dwell_s=dwell)
    if hint == "back":
        return HintAction(pan_target_deg=pan_front, base_rotate_rad=math.pi, dwell_s=dwell)
    return None


def compute_pan_step(current: float, target: float, rate: float, dt: float) -> float:
    """한 tick 동안 PAN 이 진행할 step (deg). 부호: target > current 면 양수."""
    diff = target - current
    if diff == 0.0:
        return 0.0
    max_step = rate * dt
    if abs(diff) <= max_step:
        return diff  # 남은 거리만
    return max_step if diff > 0 else -max_step
