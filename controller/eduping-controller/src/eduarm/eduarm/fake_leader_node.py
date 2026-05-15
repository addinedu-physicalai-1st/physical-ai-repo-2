"""fake_leader_node — 실물 mini leader 없을 때 합성 joint_states 발행 (양팔 16 joint).

`/eduping/leader/joint_states` (sensor_msgs/JointState) 를 50Hz 로 발행. 각 joint
는 위상이 다른 사인파로 천천히 움직여서 routine_recorder/three.js 가 시각적으로
"무언가 들어오고 있다" 를 검증할 수 있게 함.

왼팔은 부호 반대로 — 양팔이 서로 다르게 움직이는 게 시각적으로 보이도록.

ROS 파라미터:
  - topic        (str,   default '/eduping/leader/joint_states')
  - rate_hz      (float, default 50.0)
  - amplitude    (float, default 0.5)   각 joint 의 진폭 (rad)
  - period_s     (float, default 4.0)   기본 주기

후속 PR 에서 실물 feetech_leader_node 가 동일 토픽으로 publish 하면 이 노드는
띄우지 않으면 됨.
"""
from __future__ import annotations

import math

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState

from .joint_names import OPENARM_JOINT_NAMES, NUM_JOINTS


class FakeLeaderNode(Node):
    def __init__(self) -> None:
        super().__init__("fake_leader_node")

        self.declare_parameter("topic", "/eduping/leader/joint_states")
        self.declare_parameter("rate_hz", 50.0)
        self.declare_parameter("amplitude", 0.5)
        self.declare_parameter("period_s", 4.0)

        topic: str = self.get_parameter("topic").get_parameter_value().string_value
        rate_hz: float = self.get_parameter("rate_hz").get_parameter_value().double_value
        if rate_hz <= 0:
            rate_hz = 50.0

        self._amplitude: float = float(
            self.get_parameter("amplitude").get_parameter_value().double_value
        )
        period: float = float(
            self.get_parameter("period_s").get_parameter_value().double_value
        )
        self._omega: float = 2.0 * math.pi / max(period, 0.1)
        # joint 별 위상 — 0, 2π/16, 4π/16, ... 골고루 분산
        self._phases: list[float] = [
            (i / NUM_JOINTS) * 2.0 * math.pi for i in range(NUM_JOINTS)
        ]

        self._pub = self.create_publisher(JointState, topic, 10)
        self._timer = self.create_timer(1.0 / rate_hz, self._tick)
        self._t0_s: float = self._now_s()

        self.get_logger().info(
            f"fake_leader (bimanual): topic={topic} rate={rate_hz}Hz amp={self._amplitude} "
            f"period={period}s joints={NUM_JOINTS}"
        )

    def _tick(self) -> None:
        t = self._now_s() - self._t0_s
        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.name = list(OPENARM_JOINT_NAMES)
        pos: list[float] = []
        for i, name in enumerate(OPENARM_JOINT_NAMES):
            phase = self._phases[i]
            sign = -1.0 if name.startswith("left_") else 1.0
            if name.endswith("gripper"):
                # gripper 는 0 ~ 0.5 사이 (음수 의미 없음)
                pos.append(0.25 + 0.25 * math.sin(self._omega * t + phase))
            else:
                pos.append(sign * self._amplitude * math.sin(self._omega * t + phase))
        msg.position = pos
        self._pub.publish(msg)

    def _now_s(self) -> float:
        return float(self.get_clock().now().nanoseconds * 1e-9)


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = FakeLeaderNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
