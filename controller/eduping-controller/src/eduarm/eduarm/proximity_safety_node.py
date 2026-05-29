"""근접 안전정지 감지 — D435 depth 로 사람이 너무 가까운지 판정해 publish.

device-local: 카메라와 같은 머신(eduping 노트북)에서 depth(/d435/depth/image_rect_raw)를
구독, 0.6m 이내(히스테리시스 해제 0.65m)면 `/eduping/proximity_block`(Bool true)을 송출.
control bridge 가 이를 받아 팔을 정지/재개하고, robot-web 이 (율동/무궁화) 음악을 정지/재개.

판정은 eduarm.proximity.decide_block (순수 로직 — tests/test_proximity.py).
latched(transient_local) QoS — 늦게 붙는 구독자(bridge)도 마지막 상태를 즉시 받음.
"""
from __future__ import annotations

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSProfile, QoSReliabilityPolicy
from sensor_msgs.msg import Image
from std_msgs.msg import Bool

from eduarm.proximity import (
    CLEAR_MM_DEFAULT,
    MIN_PIXELS_DEFAULT,
    NEAR_MM_DEFAULT,
    decide_block,
)

DEPTH_TOPIC = "/d435/depth/image_rect_raw"
BLOCK_TOPIC = "/eduping/proximity_block"


class ProximitySafety(Node):
    def __init__(self) -> None:
        super().__init__("proximity_safety")
        self.declare_parameter("depth_topic", DEPTH_TOPIC)
        self.declare_parameter("near_mm", NEAR_MM_DEFAULT)
        self.declare_parameter("clear_mm", CLEAR_MM_DEFAULT)
        self.declare_parameter("min_pixels", MIN_PIXELS_DEFAULT)

        gp = self.get_parameter
        depth_topic = gp("depth_topic").get_parameter_value().string_value
        self._near = int(gp("near_mm").get_parameter_value().integer_value)
        self._clear = int(gp("clear_mm").get_parameter_value().integer_value)
        self._min_px = int(gp("min_pixels").get_parameter_value().integer_value)
        self._blocked = False

        # latched — bridge 가 나중에 붙어도 마지막 block 상태를 즉시 받음.
        latched = QoSProfile(
            depth=1,
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
        )
        self._pub = self.create_publisher(Bool, BLOCK_TOPIC, latched)
        self._pub.publish(Bool(data=False))  # 초기 상태 명시 송출
        self.create_subscription(Image, depth_topic, self._on_depth, 1)
        self.get_logger().info(
            f"proximity_safety up — {depth_topic} near<{self._near}mm clear>{self._clear}mm"
        )

    def _on_depth(self, msg: Image) -> None:
        # 16UC1 little-endian (RealSense). msg.data → uint16 ndarray.
        try:
            depth = np.frombuffer(msg.data, dtype=np.uint16).reshape(msg.height, msg.width)
        except Exception as exc:  # noqa: BLE001
            self.get_logger().warn(f"depth decode 실패: {exc}")
            return
        blocked = decide_block(
            depth, self._blocked,
            near_mm=self._near, clear_mm=self._clear, min_pixels=self._min_px,
        )
        if blocked != self._blocked:
            self._blocked = blocked
            self._pub.publish(Bool(data=blocked))
            self.get_logger().info(f"proximity_block = {blocked}")


def main() -> None:
    rclpy.init()
    node = ProximitySafety()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
