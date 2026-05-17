"""Serial bridge between ROS2 and Arduino Uno running servo_bridge.ino (2-axis).

Subscribes to ~/cmd_pan and ~/cmd_tilt (Float32 degrees), applies clamp +
rate-limit per axis, sends "PT:<pan>,<tilt>\\n" over serial at state_pub_hz,
parses "OK:<pan>,<tilt>\\n" replies, and publishes JointState with both joints.

Continuously re-sends the current setpoint so the Uno's watchdog does not
snap back to center between sparse teleop keypresses.
"""

from __future__ import annotations

import threading
import time

import rclpy
import serial
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import Float32

from .protocol import clamp, encode_cmd, parse_ack, rate_limit


class ServoBridge(Node):
    def __init__(self) -> None:
        super().__init__('servo_bridge')

        self.declare_parameter('serial_port', '/dev/ttyACM0')
        self.declare_parameter('baud', 115200)
        self.declare_parameter('pan.min_deg', 5.0)
        self.declare_parameter('pan.max_deg', 175.0)
        self.declare_parameter('pan.center_deg', 90.0)
        self.declare_parameter('tilt.min_deg', 30.0)
        self.declare_parameter('tilt.max_deg', 150.0)
        self.declare_parameter('tilt.center_deg', 90.0)
        self.declare_parameter('rate_limit_deg_per_s', 180.0)
        self.declare_parameter('pan_joint_name', 'camera_pan_joint')
        self.declare_parameter('tilt_joint_name', 'camera_tilt_joint')
        self.declare_parameter('state_pub_hz', 20.0)

        self._port = self.get_parameter('serial_port').value
        self._baud = int(self.get_parameter('baud').value)
        self._pan_min = float(self.get_parameter('pan.min_deg').value)
        self._pan_max = float(self.get_parameter('pan.max_deg').value)
        self._tilt_min = float(self.get_parameter('tilt.min_deg').value)
        self._tilt_max = float(self.get_parameter('tilt.max_deg').value)
        self._rate_limit = float(self.get_parameter('rate_limit_deg_per_s').value)
        self._pan_joint = self.get_parameter('pan_joint_name').value
        self._tilt_joint = self.get_parameter('tilt_joint_name').value
        self._hz = float(self.get_parameter('state_pub_hz').value)

        # Setpoints (target) and applied (rate-limited) values.
        self._target_pan = float(self.get_parameter('pan.center_deg').value)
        self._target_tilt = float(self.get_parameter('tilt.center_deg').value)
        self._applied_pan = self._target_pan
        self._applied_tilt = self._target_tilt

        # Last reported angles from the Uno (None until first OK).
        self._reported_pan: float | None = None
        self._reported_tilt: float | None = None

        self._ser: serial.Serial | None = None
        self._ser_lock = threading.Lock()
        self._last_open_error: str | None = None  # log throttle: 같은 에러 반복 안 찍기

        self.create_subscription(Float32, '~/cmd_pan', self._on_cmd_pan, 10)
        self.create_subscription(Float32, '~/cmd_tilt', self._on_cmd_tilt, 10)
        self.state_pub = self.create_publisher(JointState, '~/state', 10)

        period = 1.0 / max(self._hz, 1.0)
        self._tick_dt = period
        self.create_timer(period, self._tick)

        self._stop = threading.Event()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    # ── subscriptions ────────────────────────────────────────────────────────
    def _on_cmd_pan(self, msg: Float32) -> None:
        self._target_pan = clamp(float(msg.data), self._pan_min, self._pan_max)

    def _on_cmd_tilt(self, msg: Float32) -> None:
        self._target_tilt = clamp(float(msg.data), self._tilt_min, self._tilt_max)

    # ── serial ───────────────────────────────────────────────────────────────
    def _ensure_serial(self) -> serial.Serial | None:
        if self._ser is not None and self._ser.is_open:
            return self._ser
        try:
            self._ser = serial.Serial(self._port, self._baud, timeout=0.1)
            self.get_logger().info(f'opened serial {self._port} @ {self._baud}')
            self._last_open_error = None
        except (serial.SerialException, OSError) as e:
            # 같은 메시지 반복은 무시 — 새 에러 / 재실패 시에만 1줄.
            msg = str(e)
            if msg != self._last_open_error:
                self.get_logger().warn(f'serial open failed: {msg}')
                self._last_open_error = msg
            self._ser = None
        return self._ser

    def _read_loop(self) -> None:
        while not self._stop.is_set():
            ser = self._ensure_serial()
            if ser is None:
                time.sleep(1.0)
                continue
            try:
                line = ser.readline().decode('ascii', errors='ignore')
            except (serial.SerialException, OSError) as e:
                self.get_logger().warn(f'serial read failed: {e}')
                with self._ser_lock:
                    try:
                        ser.close()
                    finally:
                        self._ser = None
                continue
            if not line:
                continue
            ack = parse_ack(line)
            if ack is None:
                continue
            self._reported_pan = float(ack.pan)
            self._reported_tilt = float(ack.tilt)

    # ── timer ────────────────────────────────────────────────────────────────
    def _tick(self) -> None:
        max_step = self._rate_limit * self._tick_dt
        self._applied_pan = rate_limit(self._applied_pan, self._target_pan, max_step)
        self._applied_tilt = rate_limit(self._applied_tilt, self._target_tilt, max_step)

        payload = encode_cmd(self._applied_pan, self._applied_tilt)
        ser = self._ensure_serial()
        if ser is not None:
            with self._ser_lock:
                try:
                    ser.write(payload)
                except (serial.SerialException, OSError) as e:
                    self.get_logger().warn(f'serial write failed: {e}')
                    try:
                        ser.close()
                    finally:
                        self._ser = None

        self._publish_state()

    def _publish_state(self) -> None:
        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.name = [self._pan_joint, self._tilt_joint]
        pan_val = self._reported_pan if self._reported_pan is not None else self._applied_pan
        tilt_val = self._reported_tilt if self._reported_tilt is not None else self._applied_tilt
        msg.position = [pan_val, tilt_val]
        self.state_pub.publish(msg)

    # ── shutdown ─────────────────────────────────────────────────────────────
    def destroy_node(self) -> bool:
        self._stop.set()
        with self._ser_lock:
            if self._ser is not None:
                try:
                    self._ser.close()
                except Exception:
                    pass
                self._ser = None
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
