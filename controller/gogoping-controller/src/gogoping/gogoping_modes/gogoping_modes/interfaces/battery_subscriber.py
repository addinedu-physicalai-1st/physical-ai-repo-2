"""배터리 상태 토픽 구독 → blackboard.BATTERY_LEVEL 갱신.

토픽: ``battery`` (gogoping_modes 의 namespace 가 ``gogoping`` 이므로 절대 경로는
``/gogoping/battery``). 메시지 타입: ``sensor_msgs/BatteryState``.

운영(실물 Pi): 진짜 배터리 드라이버가 publisher. percentage 필드 (0.0~1.0).
sim: ``gogoping_bringup`` 의 ``sim_battery_node`` 가 publisher + 디버그 srv 호스팅.

수신 시 ``percentage * 100`` 을 ``Keys.BATTERY_LEVEL`` 로 W → ``battery_full_monitor``
/ ``battery_low_monitor`` 가 다음 BT tick 에서 R.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import py_trees
from py_trees.common import Access
from sensor_msgs.msg import BatteryState

from ..bt.blackboard import Keys

if TYPE_CHECKING:
    import rclpy.node


class BatterySubscriber:
    """``/gogoping/battery`` 구독 + blackboard.BATTERY_LEVEL W."""

    def __init__(self, node: "rclpy.node.Node"):
        self.node = node
        self._bb = py_trees.blackboard.Client(name="BatterySubscriber")
        self._bb.register_key(key=Keys.BATTERY_LEVEL, access=Access.WRITE)
        self._sub = node.create_subscription(
            BatteryState,
            "battery",
            self._on_battery,
            10,
        )

    def _on_battery(self, msg: BatteryState) -> None:
        # BatteryState.percentage 는 0.0~1.0. blackboard 는 0~100 (%) 스케일.
        # NaN (미보고) 인 경우 직전 값 유지.
        pct = float(msg.percentage)
        if pct != pct:  # NaN check
            return
        self._bb.set(Keys.BATTERY_LEVEL, pct * 100.0)
