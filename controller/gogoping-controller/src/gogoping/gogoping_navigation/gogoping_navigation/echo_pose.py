"""RViz '2D Pose Estimate' 화살표를 한 줄로 출력.

quaternion → yaw 변환하여 ``x=<...>  y=<...>  yaw=<rad> (<deg>)`` 형식으로 찍는다.
waypoint 좌표 측정용.

사용:
    ros2 run gogoping_navigation echo_pose
    # RViz 에서 '2D Pose Estimate' 클릭+드래그 → 한 줄 출력
"""
from __future__ import annotations

import math

import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped
from rclpy.node import Node


class EchoPose(Node):
    def __init__(self) -> None:
        super().__init__('echo_pose')
        self.create_subscription(
            PoseWithCovarianceStamped, '/initialpose', self._on_pose, 10)
        self.get_logger().info(
            "listening on /initialpose — RViz '2D Pose Estimate' 로 화살표를 그리세요")

    def _on_pose(self, msg: PoseWithCovarianceStamped) -> None:
        p = msg.pose.pose.position
        q = msg.pose.pose.orientation
        # 평면 회전 (x=y=0 가정): yaw = 2 * atan2(z, w)
        yaw = 2.0 * math.atan2(q.z, q.w)
        deg = math.degrees(yaw)
        print(f'x={p.x:.4f}  y={p.y:.4f}  yaw={yaw:.4f} rad ({deg:+.1f}°)',
              flush=True)


def main() -> None:
    rclpy.init()
    node = EchoPose()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
