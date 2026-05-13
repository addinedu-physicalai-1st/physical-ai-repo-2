"""GogoPing 가제보 시뮬레이션 활성 신호 publisher.

sim.launch.py 가 namespace='gogoping' 으로 띄우므로 상대 토픽 'sim_active' 는
절대 토픽 /gogoping/sim_active 가 된다. Control Server 의 RosBridge 가
구독해 sim/real 모드 판정에 사용한다.
"""

from __future__ import annotations

import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool


class SimStatusPublisher(Node):
    """1Hz 로 Bool(True) 를 sim_active 에 publish."""

    def __init__(self) -> None:
        super().__init__("sim_status_publisher")
        self.pub = self.create_publisher(Bool, "sim_active", 10)
        self.create_timer(1.0, self._tick)

    def _tick(self) -> None:
        self.pub.publish(Bool(data=True))


def main() -> None:
    rclpy.init()
    node = SimStatusPublisher()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
