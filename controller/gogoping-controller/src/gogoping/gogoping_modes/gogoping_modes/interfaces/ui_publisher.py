"""UI 상태 publish — admin / robot-web 으로 FSM/BT 스냅샷 + 일회성 이벤트 발행.

토픽 (full):
- ``/gogoping/state`` — 1Hz BT snapshot (std_msgs/String JSON)
- ``/gogoping/ui_event`` — 일회성 UI 이벤트 (audio play/stop, announce, countdown_start 등)
   본 클래스는 **상대 path ``"state"`` / ``"ui_event"``** 를 사용하며, 노드 namespace
   가 ``gogoping`` 일 때 자동으로 ``/gogoping/state`` / ``/gogoping/ui_event`` 가 된다.
   ``main.py`` 의 ``rclpy.create_node("gogoping_modes", namespace="gogoping")`` 기반.

구독자:
- state — ``service/control-service`` 가 ROS 구독 → ``/ws/robot-state`` WS → admin-app
- ui_event — robot-web frontend 가 직접 구독 (audio element 재생/정지, 별도 PR)

snapshot 포맷은 ``app/admin-app/widgets/bt_state_inline.py`` 의 docstring 참조.
ui_event 메시지 스키마 — ``{"event": <type>, ...}`` (예: ``lullaby_play`` / ``lullaby_stop`` /
``announce`` / ``countdown_start``). ``docs/bt/behaviors/common.md`` 의 ui_publish / lullaby_audio.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from std_msgs.msg import String

if TYPE_CHECKING:
    import rclpy.node


class UIPublisher:
    """``/gogoping/state`` (1Hz snapshot) + ``/gogoping/ui_event`` (1회성 이벤트) publisher.

    QoS: depth=1 (latched 아님 — 단순 latest). state 의 1Hz 주기는 호출자(main.py) 책임.
    """

    # 상대 path — node namespace ("gogoping") 가 자동으로 prefix.
    # 절대 path 로 박지 않는 이유: 멀티 robot / launch 에서 override 용이.
    TOPIC_STATE = "state"
    TOPIC_EVENT = "ui_event"
    QOS_DEPTH = 1

    def __init__(self, node: "rclpy.node.Node"):
        self.node = node
        self._pub = node.create_publisher(String, self.TOPIC_STATE, self.QOS_DEPTH)
        self._event_pub = node.create_publisher(
            String, self.TOPIC_EVENT, self.QOS_DEPTH,
        )

    def publish_state(self, snapshot: dict) -> None:
        """1Hz BT snapshot publish — main.py 가 호출.

        한국어 키/값 (예: tree name, child name) 보존을 위해 ``ensure_ascii=False``.
        직렬화 실패 시 (예: 비-JSON 객체 포함) 예외 발생 — 호출자가 처리.
        """
        msg = String()
        msg.data = json.dumps(snapshot, ensure_ascii=False)
        self._pub.publish(msg)

    def publish_event(self, message: dict) -> None:
        """일회성 UI 이벤트 publish — BT 의 ``UIPublish`` / ``LullabyAudio`` 가 호출.

        frontend 가 ``event`` 필드로 분기 처리. 한국어 보존 ``ensure_ascii=False``.
        직렬화 실패 시 (예: 비-JSON 객체 포함) 예외 발생 — 호출자가 처리.
        """
        msg = String()
        msg.data = json.dumps(message, ensure_ascii=False)
        self._event_pub.publish(msg)
