"""Keyboard teleop for the 2-axis camera pan/tilt.

Reads stdin in raw mode (termios + select, non-blocking) and publishes
Float32 angle setpoints to servo_bridge.

Keys:
    a / d         pan  -/+ step
    w / s         tilt +/- step   (w = look up)
    space         return to center
    [ / ]         step_deg --/++
    q  or  Ctrl-C exit

The bridge re-sends the current setpoint at state_pub_hz, so we only
publish on keypress.
"""

from __future__ import annotations

import select
import sys
import termios
import tty
from contextlib import contextmanager

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32

from .protocol import clamp


@contextmanager
def raw_stdin():
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        yield fd
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _read_key(timeout_s: float) -> str | None:
    ready, _, _ = select.select([sys.stdin], [], [], timeout_s)
    if not ready:
        return None
    return sys.stdin.read(1)


HELP = (
    "camera_pan keyboard teleop — a/d=pan, w/s=tilt, space=center, "
    "[/]=step, q=quit"
)


class KeyboardTeleop(Node):
    def __init__(self) -> None:
        super().__init__('keyboard_teleop')

        self.declare_parameter('step_deg', 5.0)
        self.declare_parameter('pan.min_deg', 5.0)
        self.declare_parameter('pan.max_deg', 175.0)
        self.declare_parameter('pan.center_deg', 90.0)
        self.declare_parameter('tilt.min_deg', 30.0)
        self.declare_parameter('tilt.max_deg', 150.0)
        self.declare_parameter('tilt.center_deg', 90.0)
        self.declare_parameter('pan_topic', '/servo_bridge/cmd_pan')
        self.declare_parameter('tilt_topic', '/servo_bridge/cmd_tilt')

        self.step = float(self.get_parameter('step_deg').value)
        self.pan_min = float(self.get_parameter('pan.min_deg').value)
        self.pan_max = float(self.get_parameter('pan.max_deg').value)
        self.pan_center = float(self.get_parameter('pan.center_deg').value)
        self.tilt_min = float(self.get_parameter('tilt.min_deg').value)
        self.tilt_max = float(self.get_parameter('tilt.max_deg').value)
        self.tilt_center = float(self.get_parameter('tilt.center_deg').value)

        self.pan = self.pan_center
        self.tilt = self.tilt_center

        self.pan_pub = self.create_publisher(
            Float32, self.get_parameter('pan_topic').value, 10
        )
        self.tilt_pub = self.create_publisher(
            Float32, self.get_parameter('tilt_topic').value, 10
        )

        self.get_logger().info(HELP)
        # Publish initial center once so the bridge starts at a known setpoint.
        self._publish_pan()
        self._publish_tilt()

    # ── publishers ───────────────────────────────────────────────────────────
    def _publish_pan(self) -> None:
        self.pan_pub.publish(Float32(data=float(self.pan)))

    def _publish_tilt(self) -> None:
        self.tilt_pub.publish(Float32(data=float(self.tilt)))

    # ── key handling ─────────────────────────────────────────────────────────
    def handle_key(self, key: str) -> bool:
        """Return False when the loop should exit."""
        if key == 'q' or key == '\x03':  # q or Ctrl-C
            return False
        if key == 'a':
            self.pan = clamp(self.pan - self.step, self.pan_min, self.pan_max)
            self._publish_pan()
        elif key == 'd':
            self.pan = clamp(self.pan + self.step, self.pan_min, self.pan_max)
            self._publish_pan()
        elif key == 'w':
            self.tilt = clamp(self.tilt + self.step, self.tilt_min, self.tilt_max)
            self._publish_tilt()
        elif key == 's':
            self.tilt = clamp(self.tilt - self.step, self.tilt_min, self.tilt_max)
            self._publish_tilt()
        elif key == ' ':
            self.pan = self.pan_center
            self.tilt = self.tilt_center
            self._publish_pan()
            self._publish_tilt()
        elif key == '[':
            self.step = max(0.5, self.step - 0.5)
        elif key == ']':
            self.step = min(45.0, self.step + 0.5)
        else:
            return True
        self.get_logger().info(
            f'pan={self.pan:.1f} tilt={self.tilt:.1f} step={self.step:.1f}'
        )
        return True


def main(args=None) -> None:
    rclpy.init(args=args)
    node = KeyboardTeleop()
    try:
        with raw_stdin():
            while rclpy.ok():
                rclpy.spin_once(node, timeout_sec=0.0)
                key = _read_key(timeout_s=0.05)
                if key is None:
                    continue
                if not node.handle_key(key):
                    break
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
