"""UI 상태 publish — admin / robot-web 으로 FSM/BT 스냅샷 발행.

토픽: ``/gogoping/state`` (std_msgs/String — JSON payload).
구독자: ``service/control-service`` 가 ROS 구독 → ``/ws/robot-state`` WS 로 fan-out →
admin-app 의 ``state_client`` 가 받아 ``topbar.bt_state.update_snapshot()`` 호출.

snapshot 포맷은 ``app/admin-app/widgets/bt_state_inline.py`` 의 docstring 참조.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from std_msgs.msg import String

if TYPE_CHECKING:
    import rclpy.node


class UIPublisher:
    """``/gogoping/state`` 토픽에 BT 상태 snapshot publish.

    QoS: depth=1 (latched 가 아닌 단순 latest). 1Hz 주기는 호출자(main.py) 책임.
    """

    TOPIC = "/gogoping/state"
    QOS_DEPTH = 1

    def __init__(self, node: "rclpy.node.Node"):
        self.node = node
        self._pub = node.create_publisher(String, self.TOPIC, self.QOS_DEPTH)

    def publish_state(self, snapshot: dict) -> None:
        """snapshot 을 JSON 으로 직렬화해서 publish.

        한국어 키/값 (예: tree name, child name) 보존을 위해 ``ensure_ascii=False``.
        직렬화 실패 시 (예: 비-JSON 객체 포함) 예외 발생 — 호출자가 처리.
        """
        msg = String()
        msg.data = json.dumps(snapshot, ensure_ascii=False)
        self._pub.publish(msg)
