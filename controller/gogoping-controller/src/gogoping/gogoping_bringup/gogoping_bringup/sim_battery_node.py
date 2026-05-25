"""[디버그 전용] sim 배터리 시뮬레이터.

운영(실물 Pi) 환경에서는 진짜 배터리 드라이버가 ``/gogoping/battery`` 를 publish
한다. 본 노드는 sim 환경 전용 — ``sim.launch.py`` 또는 ``device-gogoping-sim.sh``
가 띄운다.

토픽 / 서비스 (namespace=`gogoping` 이라 절대 경로는 ``/gogoping/...``):

- pub  ``battery``                     ``sensor_msgs/BatteryState``  (1 Hz)
- srv  ``sim/set_battery_level``       ``gogoping_msgs/srv/SetBatteryLevel``

내부 상태는 ``self._level`` (0.0 ~ 100.0). srv 호출 시 clamp 후 즉시 다음 publish
tick 부터 새 값 반영. BatterySubscriber 가 받아 blackboard.BATTERY_LEVEL 갱신 →
battery_low_monitor 가 50% 진입 시 ``battery_low`` trigger 발화 → RETURNING /
LOW_BATTERY_RETURNING escalation 검증 가능.
"""

from __future__ import annotations

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import BatteryState

from gogoping_msgs.srv import SetBatteryLevel


_PUBLISH_HZ = 1.0
_INITIAL_LEVEL = 100.0


class SimBatteryNode(Node):
    """1Hz BatteryState publisher + SetBatteryLevel.srv server."""

    def __init__(self) -> None:
        super().__init__("sim_battery_node")
        self._level = _INITIAL_LEVEL  # 0.0 ~ 100.0 (%)

        self._pub = self.create_publisher(BatteryState, "battery", 10)
        self._srv = self.create_service(
            SetBatteryLevel,
            "sim/set_battery_level",
            self._on_set_battery_level,
        )
        self.create_timer(1.0 / _PUBLISH_HZ, self._tick)

        self.get_logger().info(
            f"sim_battery_node ready — pub /gogoping/battery @ {_PUBLISH_HZ}Hz, "
            f"srv /gogoping/sim/set_battery_level, init level={self._level}%"
        )

    def _tick(self) -> None:
        msg = BatteryState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.percentage = self._level / 100.0  # BatteryState.percentage 는 0.0~1.0
        msg.present = True
        msg.power_supply_status = BatteryState.POWER_SUPPLY_STATUS_DISCHARGING
        msg.power_supply_health = BatteryState.POWER_SUPPLY_HEALTH_GOOD
        msg.power_supply_technology = BatteryState.POWER_SUPPLY_TECHNOLOGY_LION
        self._pub.publish(msg)

    def _on_set_battery_level(
        self,
        request: SetBatteryLevel.Request,
        response: SetBatteryLevel.Response,
    ) -> SetBatteryLevel.Response:
        raw = float(request.level)
        if raw < 0.0:
            self._level = 0.0
            response.reason = "clamped_to_0"
        elif raw > 100.0:
            self._level = 100.0
            response.reason = "clamped_to_100"
        else:
            self._level = raw
            response.reason = ""
        response.accepted = True
        self.get_logger().info(f"battery level set to {self._level}% (req={raw}%)")
        return response


def main() -> None:
    rclpy.init()
    node = SimBatteryNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
