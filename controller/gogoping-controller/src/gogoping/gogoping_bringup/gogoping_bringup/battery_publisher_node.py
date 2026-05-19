"""Pi 운영용 진짜 battery publisher.

운영(실물 Pi) 환경에서 ``/gogoping/battery`` (sensor_msgs/BatteryState) 를 1Hz publish.
``pi.launch.py`` 의 ``PushRosNamespace("gogoping")`` GroupAction 안에 등록 — 상대 토픽
``battery`` 가 자동으로 ``/gogoping/battery`` 로 prefix.

sim 전용 ``sim_battery_node`` 와의 차이:
- 본 노드: 운영 ONLY. SetBatteryLevel.srv 미호스팅 (admin UI 슬라이더는 sim 에서만).
- sim_battery_node: sim ONLY. 100% 고정 + 디버그 srv.

## 하드웨어 소스 (ROS param `source`)

| source 값             | 동작                                                                                              |
|----------------------|--------------------------------------------------------------------------------------------------|
| ``voltage_topic``    | ROS topic ``voltage_topic`` (default ``battery_voltage``, Float32 V) 구독 → ``voltage_min`` / ``voltage_max`` 로 0~100% 선형 변환. **실 Pi 운영 권장**. vic_pinky_bringup 이 ZLAC register 0x20A0 에서 1Hz 발행. |
| ``sysfs``            | ROS param ``sysfs_path`` (예: ``/sys/class/power_supply/BAT0/capacity``) 의 정수 % 읽음.            |
| ``static`` (기본)     | ROS param ``level`` (기본 100.0) 그대로 publish. 디버그 / fallback 용.                              |

## 절대 토픽 박지 말 것

토픽 이름은 반드시 **상대 경로 ``battery``** 사용 — namespace 가 자동 prefix 함.
``/gogoping/battery`` 처럼 절대 경로로 박으면 multi-robot launch / sim override 시
망가짐. ``sim_battery_node`` 도 같은 규약.
"""

from __future__ import annotations

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import BatteryState
from std_msgs.msg import Float32


_PUBLISH_HZ = 1.0


class BatteryPublisherNode(Node):
    """1Hz BatteryState publisher — Pi 운영용."""

    def __init__(self) -> None:
        super().__init__("battery_publisher_node")

        # ROS params
        self.declare_parameter("source", "static")
        self.declare_parameter("level", 100.0)
        self.declare_parameter("sysfs_path", "/sys/class/power_supply/BAT0/capacity")
        # voltage_topic source 용 — 24V 시스템 가정. 다른 배터리는 launch arg override.
        self.declare_parameter("voltage_topic", "battery_voltage")
        self.declare_parameter("voltage_min", 22.0)   # 0% 기준 (cutoff)
        self.declare_parameter("voltage_max", 27.0)   # 100% 기준 (full)

        self._pub = self.create_publisher(BatteryState, "battery", 10)
        self.create_timer(1.0 / _PUBLISH_HZ, self._tick)

        self._latest_voltage: float | None = None
        source = self.get_parameter("source").get_parameter_value().string_value
        if source == "voltage_topic":
            topic = self.get_parameter("voltage_topic").get_parameter_value().string_value
            self.create_subscription(Float32, topic, self._on_voltage, 10)

        self.get_logger().info(
            f"battery_publisher_node ready — pub /gogoping/battery @ {_PUBLISH_HZ}Hz, "
            f"source={source!r}"
        )

    def _on_voltage(self, msg: Float32) -> None:
        self._latest_voltage = float(msg.data)

    def _tick(self) -> None:
        level = self._read_level()
        msg = BatteryState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.percentage = level / 100.0  # BatteryState.percentage 는 0.0~1.0
        if self._latest_voltage is not None:
            msg.voltage = float(self._latest_voltage)
        msg.present = True
        msg.power_supply_status = BatteryState.POWER_SUPPLY_STATUS_DISCHARGING
        msg.power_supply_health = BatteryState.POWER_SUPPLY_HEALTH_GOOD
        msg.power_supply_technology = BatteryState.POWER_SUPPLY_TECHNOLOGY_LION
        self._pub.publish(msg)

    def _read_level(self) -> float:
        """source param 에 따라 배터리 % 반환. 실패 시 마지막 정상 값 (또는 0.0)."""
        source = self.get_parameter("source").get_parameter_value().string_value
        if source == "voltage_topic":
            return self._read_voltage_topic()
        if source == "sysfs":
            return self._read_sysfs()
        return self._read_static()

    def _read_static(self) -> float:
        return float(self.get_parameter("level").get_parameter_value().double_value)

    def _read_sysfs(self) -> float:
        path = self.get_parameter("sysfs_path").get_parameter_value().string_value
        try:
            with open(path) as f:
                return max(0.0, min(100.0, float(f.read().strip())))
        except (OSError, ValueError) as e:
            self.get_logger().warn(
                f"sysfs read 실패 ({path}): {e} — static 값으로 fallback", once=True
            )
            return self._read_static()

    def _read_voltage_topic(self) -> float:
        """battery_voltage 토픽의 마지막 voltage 를 voltage_min/max 로 0~100% 선형 변환."""
        if self._latest_voltage is None:
            self.get_logger().warn(
                "voltage_topic 메시지 미수신 — static 값으로 fallback", once=True
            )
            return self._read_static()
        v_min = self.get_parameter("voltage_min").get_parameter_value().double_value
        v_max = self.get_parameter("voltage_max").get_parameter_value().double_value
        if v_max <= v_min:
            return self._read_static()
        pct = (self._latest_voltage - v_min) / (v_max - v_min) * 100.0
        return max(0.0, min(100.0, pct))


def main() -> None:
    rclpy.init()
    node = BatteryPublisherNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
