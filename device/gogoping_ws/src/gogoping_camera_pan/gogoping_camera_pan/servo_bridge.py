"""Serial bridge between ROS2 and Arduino Uno running servo_bridge.ino.

Subscribes to a target angle topic, sends "A:<deg>\\n" over serial,
and publishes the current angle as JointState.

Protocol (Arduino):
    host → uno : "A:<deg>\\n"           (target angle, float deg)
    uno  → host: "OK:<deg>\\n"          (echoed actual angle after Servo.write)

Topics:
    sub  ~/cmd_angle  std_msgs/Float32
    pub  ~/state      sensor_msgs/JointState  (position in radians)
"""
from __future__ import annotations

import math
import threading
import time

import rclpy
import serial
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import Float32


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
        self.declare_parameter('write_hz', 50.0)
        self.declare_parameter('reconnect_period_s', 2.0)

        self._port = str(self.get_parameter('serial_port').value)
        self._baud = int(self.get_parameter('baud').value)
        self._min_deg = float(self.get_parameter('min_deg').value)
        self._max_deg = float(self.get_parameter('max_deg').value)
        self._center_deg = float(self.get_parameter('center_deg').value)
        self._rate_limit = float(self.get_parameter('rate_limit_deg_per_s').value)
        self._joint_name = str(self.get_parameter('joint_name').value)
        state_hz = float(self.get_parameter('state_pub_hz').value)
        write_hz = float(self.get_parameter('write_hz').value)
        self._reconnect_period_s = float(self.get_parameter('reconnect_period_s').value)

        self._target_deg: float = self._center_deg
        self._current_deg: float = self._center_deg
        self._last_step_time = time.monotonic()
        self._last_reconnect_attempt = 0.0

        self._serial_lock = threading.Lock()
        self._ser: serial.Serial | None = None

        self.cmd_sub = self.create_subscription(
            Float32, '~/cmd_angle', self._on_cmd, 10
        )
        self.state_pub = self.create_publisher(JointState, '~/state', 10)

        self._open_serial()

        self.create_timer(1.0 / write_hz, self._tick_write)
        self.create_timer(1.0 / state_hz, self._publish_state)

    def _open_serial(self) -> bool:
        now = time.monotonic()
        if now - self._last_reconnect_attempt < self._reconnect_period_s:
            return False
        self._last_reconnect_attempt = now
        try:
            self._ser = serial.Serial(self._port, self._baud, timeout=0.05)
            self.get_logger().info(f'Opened serial {self._port} @ {self._baud}')
            time.sleep(2.0)  # Arduino auto-reset 대기
            self._write_serial(self._center_deg)
            return True
        except serial.SerialException as e:
            self.get_logger().warning(f'Failed to open {self._port}: {e}')
            self._ser = None
            return False

    def _on_cmd(self, msg: Float32) -> None:
        clamped = max(self._min_deg, min(self._max_deg, float(msg.data)))
        self._target_deg = clamped

    def _tick_write(self) -> None:
        if self._ser is None:
            self._open_serial()
            return

        now = time.monotonic()
        dt = max(now - self._last_step_time, 1e-3)
        self._last_step_time = now

        if abs(self._target_deg - self._current_deg) < 1e-3:
            return

        max_step = self._rate_limit * dt
        diff = self._target_deg - self._current_deg
        step = max(-max_step, min(max_step, diff))
        new_deg = self._current_deg + step

        if self._write_serial(new_deg):
            self._current_deg = new_deg
            self._read_ack_nonblocking()

    def _write_serial(self, deg: float) -> bool:
        if self._ser is None:
            return False
        line = f'A:{deg:.1f}\n'.encode('ascii')
        try:
            with self._serial_lock:
                self._ser.write(line)
                self._ser.flush()
            return True
        except (serial.SerialException, OSError) as e:
            self.get_logger().warning(f'Serial write failed: {e}; will reconnect')
            self._close_serial()
            return False

    def _read_ack_nonblocking(self) -> None:
        if self._ser is None:
            return
        try:
            with self._serial_lock:
                if self._ser.in_waiting <= 0:
                    return
                raw = self._ser.readline()
        except (serial.SerialException, OSError) as e:
            self.get_logger().warning(f'Serial read failed: {e}')
            self._close_serial()
            return

        line = raw.decode('ascii', errors='ignore').strip()
        if line.startswith('OK:'):
            try:
                self._current_deg = float(line[3:])
            except ValueError:
                pass

    def _close_serial(self) -> None:
        with self._serial_lock:
            if self._ser is not None:
                try:
                    self._ser.close()
                except Exception:
                    pass
                self._ser = None

    def _publish_state(self) -> None:
        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.name = [self._joint_name]
        msg.position = [math.radians(self._current_deg)]
        self.state_pub.publish(msg)

    def destroy_node(self) -> bool:
        self._close_serial()
        return super().destroy_node()


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
