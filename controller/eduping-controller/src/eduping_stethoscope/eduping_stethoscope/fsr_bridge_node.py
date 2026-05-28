"""FSR402 stethoscope serial bridge.

Reads "F<raw>\\n" lines from an Arduino on a serial port and republishes the
raw ADC value (0..1023) as std_msgs/Int32 on /eduping/stethoscope/fsr_raw.

fake:=true 면 시리얼 없이 합성값(삼각파)을 publish — 하드웨어/리더암 없이 UI 검증용.
"""
from __future__ import annotations

import math
import threading
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import Int32

from eduping_stethoscope.protocol import parse_line

TOPIC = "/eduping/stethoscope/fsr_raw"


class FsrBridgeNode(Node):
    def __init__(self) -> None:
        super().__init__("fsr_bridge_node")
        self.declare_parameter("serial_port", "/dev/ttyACM0")
        self.declare_parameter("baud", 115200)
        self.declare_parameter("rate_hz", 30.0)
        self.declare_parameter("fake", False)

        self._port = self.get_parameter("serial_port").value
        self._baud = int(self.get_parameter("baud").value)
        self._rate_hz = float(self.get_parameter("rate_hz").value)
        self._fake = bool(self.get_parameter("fake").value)

        self._pub = self.create_publisher(Int32, TOPIC, 10)
        self._stop = threading.Event()

        if self._fake:
            self._t0 = time.time()
            period = 1.0 / max(self._rate_hz, 1.0)
            self._timer = self.create_timer(period, self._publish_fake)
            self.get_logger().info("fsr_bridge_node started in FAKE mode -> %s" % TOPIC)
        else:
            self._reader = threading.Thread(target=self._serial_loop, name="fsr_serial", daemon=True)
            self._reader.start()
            self.get_logger().info(
                "fsr_bridge_node started -- port=%s baud=%d -> %s"
                % (self._port, self._baud, TOPIC)
            )

    def _publish_fake(self) -> None:
        # 0..1023 sine — 누를 때처럼 출렁이게.
        phase = (time.time() - self._t0) * 0.5
        raw = int(512 + 480 * math.sin(phase))
        raw = max(0, min(1023, raw))
        self._pub.publish(Int32(data=raw))

    def _serial_loop(self) -> None:
        import serial  # pyserial — import here so fake mode works without it installed
        while not self._stop.is_set():
            try:
                ser = serial.Serial(self._port, self._baud, timeout=1.0)
            except Exception as e:  # noqa: BLE001
                self.get_logger().warning(
                    "serial open failed (%s): %s -- retry in 2s" % (self._port, e)
                )
                self._stop.wait(2.0)
                continue
            self.get_logger().info("serial open: %s" % self._port)
            try:
                while not self._stop.is_set():
                    line = ser.readline().decode("ascii", errors="ignore")
                    if not line:
                        continue
                    raw = parse_line(line)
                    if raw is None:
                        self.get_logger().debug("skip bad line: %r" % line)
                        continue
                    self._pub.publish(Int32(data=raw))
            except Exception as e:  # noqa: BLE001
                self.get_logger().warning("serial read error: %s -- reopening" % e)
            finally:
                try:
                    ser.close()
                except Exception:  # noqa: BLE001
                    pass

    def destroy_node(self) -> bool:
        self._stop.set()
        return super().destroy_node()


def main() -> None:
    rclpy.init()
    node = FsrBridgeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
