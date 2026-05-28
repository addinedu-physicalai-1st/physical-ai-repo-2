"""bbox bearing + LiDAR 거리 → target world pose → target 의 1.5m 뒤 goal 추정.

흐름:
1. tracking_state.angle_deg (perception) → bearing_rad
2. LiDAR 같은 bearing 의 평균 거리 → distance_m
3. base_link frame 의 target (x, y) 계산
4. tf2 base_link → map 변환
5. robot 의 현재 map pose 와 target 사이 벡터 → target 의 1.5m 뒤 goal
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from geometry_msgs.msg import Pose
from sensor_msgs.msg import LaserScan
from tf2_ros import Buffer

from gogoping_follow.config import (
    FOLLOW_DISTANCE_M,
    LIDAR_BEARING_WINDOW_DEG,
    LIDAR_MAX_M,
    LIDAR_YAW_OFFSET_RAD,
)
from gogoping_follow.lidar_bearing import distance_at_bearing
from gogoping_follow.tf_helper import transform_pose_base_to_map, yaw_to_quat


@dataclass
class GoalEstimate:
    goal: Pose                # map frame
    target_map: Pose          # map frame, 디버그 용
    distance_m: float         # LiDAR 거리 (base → target)
    bearing_rad: float        # base frame 방위


def estimate_follow_goal(
    angle_deg: float,
    scan: LaserScan | None,
    tf_buffer: Buffer,
    robot_map_pose: Pose | None,
) -> GoalEstimate | None:
    """현재 frame 의 추정. 측정 부족이면 None."""
    if scan is None or robot_map_pose is None:
        return None
    if not math.isfinite(angle_deg):
        return None

    bearing_rad = math.radians(angle_deg)
    # LiDAR 가 180° 회전 장착 (laser_yaw=π) → scan 0° = 물리 후면. 카메라 bearing
    # (base_link, 0=정면) 으로 빔을 찾으려면 offset 더해서 실제 scan 각도로 조회.
    lidar_bearing = bearing_rad + LIDAR_YAW_OFFSET_RAD
    distance_m = distance_at_bearing(
        scan.ranges,
        angle_min=scan.angle_min,
        angle_increment=scan.angle_increment,
        bearing_rad=lidar_bearing,
        window_rad=math.radians(LIDAR_BEARING_WINDOW_DEG),
        max_m=LIDAR_MAX_M,
    )
    if distance_m is None:
        return None

    # base_link frame 의 target 위치 — 거리는 LiDAR, 방향은 카메라 bearing(물리 정면 기준).
    target_base = Pose()
    target_base.position.x = distance_m * math.cos(bearing_rad)
    target_base.position.y = distance_m * math.sin(bearing_rad)
    target_base.orientation = yaw_to_quat(0.0)

    target_map = transform_pose_base_to_map(tf_buffer, target_base)
    if target_map is None:
        return None

    # robot → target 벡터의 reverse 1.5m 지점
    dx = target_map.position.x - robot_map_pose.position.x
    dy = target_map.position.y - robot_map_pose.position.y
    dist_robot_target = math.hypot(dx, dy)
    if dist_robot_target < FOLLOW_DISTANCE_M:
        # 이미 충분히 가까움 — goal 보내지 않음 (Nav2 reissue 회피)
        return None
    goal = Pose()
    scale = FOLLOW_DISTANCE_M / dist_robot_target
    goal.position.x = target_map.position.x - scale * dx
    goal.position.y = target_map.position.y - scale * dy
    goal.orientation = yaw_to_quat(math.atan2(dy, dx))

    return GoalEstimate(
        goal=goal,
        target_map=target_map,
        distance_m=distance_m,
        bearing_rad=bearing_rad,
    )
