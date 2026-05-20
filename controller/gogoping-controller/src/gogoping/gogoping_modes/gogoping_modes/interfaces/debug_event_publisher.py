"""Debug event publisher — admin UI 의 NavDebugLogCard 가 SSE 로 받아 표시.

토픽 (full): ``/gogoping/debug/nav_events`` — std_msgs/String, JSON payload.

용도: nav cancel chain (SetGoal → reconcile → FSM → BT swap → NavTo
send/accepted/terminate/race → graph_router cancel forward) 추적용 일회성 디버깅
스트림. ros2 logger 와 별도 — admin UI 카드 화면에 한 줄씩 색상으로 표시.

Payload 구조:
    {
      "ts": 1716180000.123,
      "source": "NavTo" | "FSM" | "BT swap" | "SetGoal" | "reconcile" | "graph_rt",
      "level": "info" | "warn" | "err",
      "msg":   "free-form text"
    }

graph_router_node (gogoping_navigation 패키지) 도 같은 토픽에 publish — namespace
무관하게 absolute path ``/gogoping/debug/nav_events`` 로 합류.
"""
from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from std_msgs.msg import String

if TYPE_CHECKING:
    import rclpy.node


class DebugEventPublisher:
    """``/gogoping/debug/nav_events`` 토픽 publisher.

    QoS: depth=20 — admin UI SSE 가 잠시 지연돼도 burst 보존.
    """

    TOPIC = "debug/nav_events"   # 상대 path — node namespace ("gogoping") 가 자동 prefix
    QOS_DEPTH = 20

    def __init__(self, node: "rclpy.node.Node"):
        self.node = node
        self._pub = node.create_publisher(String, self.TOPIC, self.QOS_DEPTH)

    def event(self, source: str, msg: str, level: str = "info") -> None:
        payload = {
            "ts": time.time(),
            "source": source,
            "level": level,
            "msg": msg,
        }
        out = String()
        out.data = json.dumps(payload, ensure_ascii=False)
        self._pub.publish(out)
