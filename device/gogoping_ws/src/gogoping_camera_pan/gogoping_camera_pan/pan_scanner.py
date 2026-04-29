"""High-level left/right scan generator for hide-and-seek patrol.

Activated by /start_scan service, sweeps angle around center_deg with
configured amplitude and period, publishes to servo_bridge cmd_angle topic.
"""

import rclpy
from rclpy.node import Node
from std_srvs.srv import SetBool
from std_msgs.msg import Float32


class PanScanner(Node):
    def __init__(self) -> None:
        super().__init__('pan_scanner')

        self.declare_parameter('center_deg', 90.0)
        self.declare_parameter('amplitude_deg', 45.0)
        self.declare_parameter('period_s', 4.0)
        self.declare_parameter('update_hz', 20.0)
        self.declare_parameter('cmd_topic', '/servo_bridge/cmd_angle')

        self.cmd_pub = self.create_publisher(
            Float32, self.get_parameter('cmd_topic').value, 10
        )
        self.scan_srv = self.create_service(
            SetBool, '~/set_scan', self._on_set_scan
        )

        self._active = False
        # TODO: timer-driven sin/triangle sweep when _active, return to center on stop.

    def _on_set_scan(self, request: SetBool.Request, response: SetBool.Response):
        self._active = request.data
        response.success = True
        response.message = 'scanning' if self._active else 'stopped'
        return response


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
