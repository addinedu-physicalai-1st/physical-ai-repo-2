"""배터리 상태 토픽 구독 → blackboard.battery_level 갱신 (TODO).

# STUB
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import rclpy.node


class BatterySubscriber:
    """추후 sensor_msgs/BatteryState 구독으로 구현.

    수신 시 ``blackboard.BATTERY_LEVEL`` 을 percentage 로 W.
    """

    def __init__(self, node: "rclpy.node.Node"):
        self.node = node
