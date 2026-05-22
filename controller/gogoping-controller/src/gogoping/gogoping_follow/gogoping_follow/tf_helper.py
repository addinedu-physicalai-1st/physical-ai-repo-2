"""tf2 wrapper — base_link 좌표를 map frame 으로 변환."""
from __future__ import annotations

import math

from geometry_msgs.msg import Pose, PoseStamped, Quaternion
from rclpy.duration import Duration
from rclpy.time import Time
from tf2_ros import Buffer, TransformException

from gogoping_follow.config import BASE_FRAME, MAP_FRAME


def yaw_to_quat(yaw: float) -> Quaternion:
    q = Quaternion()
    q.z = math.sin(yaw / 2.0)
    q.w = math.cos(yaw / 2.0)
    return q


def transform_pose_base_to_map(
    tf_buffer: Buffer,
    base_pose: Pose,
    *,
    timeout_s: float = 0.1,
) -> Pose | None:
    """base_link frame Pose → map frame Pose. tf 없으면 None."""
    ps = PoseStamped()
    ps.header.frame_id = BASE_FRAME
    ps.header.stamp = Time().to_msg()  # latest
    ps.pose = base_pose
    try:
        out = tf_buffer.transform(
            ps, MAP_FRAME,
            timeout=Duration(seconds=timeout_s),
        )
    except TransformException:
        return None
    return out.pose
