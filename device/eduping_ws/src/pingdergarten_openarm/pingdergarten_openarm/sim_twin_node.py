"""sim_twin_node — kinematic-forward only fake controller.

OpenArm 실물 (openarm_bringup) 이 안 떠있을 때 routines_player 가 publish 한
JointTrajectory 를 받아 시간축을 진행하며 `/joint_states` 를 합성. three.js
OpenarmViewer 가 이걸 그대로 그려서 "녹화/재생 검수" 용도로 사용.

동작:
  - 입력 : trajectory_msgs/JointTrajectory  on  /eduping/joint_trajectory
  - 출력 : sensor_msgs/JointState           on  /joint_states  (50Hz, 마지막 frame hold)

interpolation: 인접 두 트래젝토리 포인트 사이 선형. 8 joint 가정이라 단순 선형이면 충분.
실 controller 의 cubic 보간과는 다르지만 시각 검수 목적엔 OK.

ROS 파라미터:
  - input_topic  (str, default '/eduping/joint_trajectory')
  - output_topic (str, default '/joint_states')
  - publish_hz   (float, default 50.0)

이 노드는 실물 모드에서는 띄우지 않는다 (`ros2_control` 의 joint_state_broadcaster 가
동일 토픽을 publish 해서 충돌).
"""
from __future__ import annotations

from dataclasses import dataclass

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSHistoryPolicy, QoSProfile, QoSReliabilityPolicy
from sensor_msgs.msg import JointState
from trajectory_msgs.msg import JointTrajectory

from .joint_names import OPENARM_JOINT_NAMES


@dataclass
class _ActiveTrajectory:
    joint_names: list[str]
    times: list[float]   # time_from_start in seconds, monotonic
    positions: list[list[float]]
    start_clock_s: float


class SimTwinNode(Node):
    def __init__(self) -> None:
        super().__init__("sim_twin_node")

        self.declare_parameter("input_topic", "/eduping/joint_trajectory")
        self.declare_parameter("output_topic", "/joint_states")
        self.declare_parameter("publish_hz", 50.0)

        in_topic: str = self.get_parameter("input_topic").get_parameter_value().string_value
        out_topic: str = self.get_parameter("output_topic").get_parameter_value().string_value
        publish_hz: float = self.get_parameter("publish_hz").get_parameter_value().double_value
        if publish_hz <= 0.0:
            publish_hz = 50.0

        # latched-ish: 새 구독자가 와도 마지막 상태 받게 transient_local
        out_qos = QoSProfile(
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.VOLATILE,
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=10,
        )

        self._active: _ActiveTrajectory | None = None
        # 첫 trajectory 도착 전에도 viewer 가 "0 자세" 라도 받게 — 8 joint zeros
        self._last_state: list[float] = [0.0] * len(OPENARM_JOINT_NAMES)
        self._last_names: list[str] = list(OPENARM_JOINT_NAMES)

        self._sub = self.create_subscription(JointTrajectory, in_topic, self._on_trajectory, 10)
        self._pub = self.create_publisher(JointState, out_topic, out_qos)
        self._timer = self.create_timer(1.0 / publish_hz, self._tick)

        self.get_logger().info(
            f"sim_twin: in={in_topic} out={out_topic} hz={publish_hz}"
        )

    # ----------------------------------------------------------------------
    def _on_trajectory(self, msg: JointTrajectory) -> None:
        if not msg.points:
            self.get_logger().warning("trajectory with no points; ignoring")
            return
        names = list(msg.joint_names) if msg.joint_names else list(OPENARM_JOINT_NAMES)
        times: list[float] = []
        positions: list[list[float]] = []
        for p in msg.points:
            t = float(p.time_from_start.sec) + float(p.time_from_start.nanosec) * 1e-9
            times.append(t)
            positions.append([float(x) for x in p.positions])
        # time_from_start 단조증가 보정 (안전)
        for i in range(1, len(times)):
            if times[i] < times[i - 1]:
                times[i] = times[i - 1]
        self._active = _ActiveTrajectory(
            joint_names=names,
            times=times,
            positions=positions,
            start_clock_s=self._now_s(),
        )
        self.get_logger().info(
            f"new trajectory: {len(times)} pts, duration={times[-1]:.2f}s, names={names[:3]}..."
        )

    # ----------------------------------------------------------------------
    def _tick(self) -> None:
        names: list[str]
        pos: list[float]
        if self._active is None:
            names = self._last_names
            pos = self._last_state
        else:
            now = self._now_s() - self._active.start_clock_s
            pos = _sample(self._active, now)
            names = self._active.joint_names
            self._last_names = names
            self._last_state = pos
        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.name = names
        msg.position = pos
        self._pub.publish(msg)

    # ----------------------------------------------------------------------
    def _now_s(self) -> float:
        t = self.get_clock().now().nanoseconds * 1e-9
        return float(t)


def _sample(traj: _ActiveTrajectory, t: float) -> list[float]:
    """선형 보간. t < first → first hold. t > last → last hold."""
    times = traj.times
    positions = traj.positions
    if t <= times[0]:
        return list(positions[0])
    if t >= times[-1]:
        return list(positions[-1])
    # binary search 가능하나 키프레임 ~수백개이고 50Hz 라 선형 충분
    for i in range(1, len(times)):
        if t <= times[i]:
            t0, t1 = times[i - 1], times[i]
            p0, p1 = positions[i - 1], positions[i]
            span = t1 - t0
            if span <= 0:
                return list(p1)
            alpha = (t - t0) / span
            return [a + (b - a) * alpha for a, b in zip(p0, p1)]
    return list(positions[-1])  # unreachable


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = SimTwinNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
