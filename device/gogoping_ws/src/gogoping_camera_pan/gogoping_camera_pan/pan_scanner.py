"""High-level left/right scan generator for hide-and-seek patrol.

`/pan_scanner/set_scan` (std_srvs/SetBool) 로 활성/비활성 토글:
    true  → center_deg 기준 ±amplitude_deg 로 sin 스윕 시작
    false → 즉시 center_deg 로 복귀

cmd_topic 로 각도 값 발행 (servo_bridge 가 구독).
"""
from __future__ import annotations

import math
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32
from std_srvs.srv import SetBool


class PanScanner(Node):
    def __init__(self) -> None:
        super().__init__('pan_scanner')

        self.declare_parameter('center_deg', 90.0)
        self.declare_parameter('amplitude_deg', 45.0)
        self.declare_parameter('period_s', 4.0)
        self.declare_parameter('update_hz', 20.0)
        self.declare_parameter('cmd_topic', '/servo_bridge/cmd_angle')

        self._center = float(self.get_parameter('center_deg').value)
        self._amp = float(self.get_parameter('amplitude_deg').value)
        self._period = max(float(self.get_parameter('period_s').value), 0.1)
        update_hz = float(self.get_parameter('update_hz').value)
        cmd_topic = str(self.get_parameter('cmd_topic').value)

        self.cmd_pub = self.create_publisher(Float32, cmd_topic, 10)
        self.scan_srv = self.create_service(
            SetBool, '~/set_scan', self._on_set_scan
        )

        self._active = False
        self._t0 = time.monotonic()
        self.create_timer(1.0 / update_hz, self._tick)

    def _on_set_scan(self, request: SetBool.Request, response: SetBool.Response):
        if request.data and not self._active:
            self._t0 = time.monotonic()
            self._active = True
            response.message = 'scanning'
        elif not request.data and self._active:
            self._active = False
            self._publish(self._center)
            response.message = 'stopped, returned to center'
        else:
            response.message = 'no change'
        response.success = True
        self.get_logger().info(response.message)
        return response

    def _tick(self) -> None:
        if not self._active:
            return
        elapsed = time.monotonic() - self._t0
        phase = 2.0 * math.pi * (elapsed / self._period)
        deg = self._center + self._amp * math.sin(phase)
        self._publish(deg)

    def _publish(self, deg: float) -> None:
        msg = Float32()
        msg.data = float(deg)
        self.cmd_pub.publish(msg)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = PanScanner()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
