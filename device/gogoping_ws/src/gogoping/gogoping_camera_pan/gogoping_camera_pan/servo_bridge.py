"""Serial bridge between ROS2 and Arduino Uno running servo_bridge.ino.

Subscribes to a target angle topic, sends "A:<deg>\\n" over serial,
and publishes the current angle as JointState.
"""

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32
from sensor_msgs.msg import JointState


class ServoBridge(Node):
    def __init__(self) -> None:
        super().__init__('servo_bridge')

        self.declare_parameter('serial_port', '/dev/ttyACM0')
        self.declare_parameter('baud', 115200)
        self.declare_parameter('min_deg', 0.0)
        self.declare_parameter('max_deg', 180.0)
        self.declare_parameter('center_deg', 90.0)
        self.declare_parameter('rate_limit_deg_per_s', 180.0)
        self.declare_parameter('joint_name', 'camera_pan_joint')
        self.declare_parameter('state_pub_hz', 20.0)

        self.cmd_sub = self.create_subscription(
            Float32, '~/cmd_angle', self._on_cmd, 10
        )
        self.state_pub = self.create_publisher(JointState, '~/state', 10)

        # TODO: open serial, implement rate limiter, parse "OK:<deg>\n" replies,
        #       publish JointState on a timer, watchdog for serial reconnect.

    def _on_cmd(self, msg: Float32) -> None:
        # TODO: clamp to [min_deg, max_deg], apply rate limit, write "A:{deg}\n"
        del msg


def main(args=None) -> None:
    rclpy.init(args=args)
    node = ServoBridge()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
