"""routines_player_node — CLI 검증용 standalone YAML 재생기.

사용:
  ros2 run pingdergarten_openarm routines_player_node --ros-args \
    -p file:=$REPO/shared/openarm_greeting/morning.yaml

기본 경로: 첫 trajectory 발행 후 KeyboardInterrupt 까지 대기 (sim_twin 의 /joint_states
hold 동작 확인 용도). `oneshot:=true` (기본) 면 1초 대기 후 종료.

녹화 / API 재생은 FastAPI bridge 가 직접 처리 — 이 노드는 안 거침.
"""
from __future__ import annotations

from pathlib import Path

import rclpy
from builtin_interfaces.msg import Duration
from rclpy.node import Node
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint

from .routines_io import Routine, load_routine


def routine_to_msg(routine: Routine) -> JointTrajectory:
    msg = JointTrajectory()
    msg.joint_names = list(routine.joint_names)
    for kf in routine.keyframes:
        pt = JointTrajectoryPoint()
        pt.positions = [float(x) for x in kf.pos]
        sec = int(kf.t)
        nsec = int((kf.t - sec) * 1e9)
        pt.time_from_start = Duration(sec=sec, nanosec=nsec)
        msg.points.append(pt)
    return msg


class RoutinesPlayerNode(Node):
    def __init__(self) -> None:
        super().__init__("routines_player_node")

        self.declare_parameter("file", "")
        self.declare_parameter("topic", "/eduping/joint_trajectory")
        self.declare_parameter("oneshot", True)

        file_param: str = self.get_parameter("file").get_parameter_value().string_value
        topic: str = self.get_parameter("topic").get_parameter_value().string_value
        oneshot: bool = self.get_parameter("oneshot").get_parameter_value().bool_value

        if not file_param:
            self.get_logger().fatal("require -p file:=<path-to-routine.yaml>")
            raise SystemExit(2)
        path = Path(file_param)
        if not path.exists():
            self.get_logger().fatal(f"file not found: {path}")
            raise SystemExit(2)

        routine = load_routine(path)
        if not routine.keyframes:
            self.get_logger().fatal(f"{path} has no keyframes")
            raise SystemExit(2)

        # latched-ish 한 번에 보내고 끝 — depth 1 + transient_local 가 가장 깔끔
        from rclpy.qos import (
            QoSDurabilityPolicy,
            QoSHistoryPolicy,
            QoSProfile,
            QoSReliabilityPolicy,
        )
        qos = QoSProfile(
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=1,
        )
        self._pub = self.create_publisher(JointTrajectory, topic, qos)

        msg = routine_to_msg(routine)
        # publisher 가 등록될 시간 한 박자
        self._sent = False

        def _send_once() -> None:
            if self._sent:
                return
            self._pub.publish(msg)
            self._sent = True
            self.get_logger().info(
                f"published {len(msg.points)} pts from {path.name} → {topic} (duration {routine.duration_s:.2f}s)"
            )
            if oneshot:
                # publisher discovery 위해 1초 대기 후 shutdown
                self.create_timer(1.0, lambda: rclpy.shutdown())

        # 0.2 초 후 publish — discovery 보장
        self.create_timer(0.2, _send_once)


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = RoutinesPlayerNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        try:
            node.destroy_node()
        except Exception:  # noqa: BLE001
            pass
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
