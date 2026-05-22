"""gogoping_camera_pan 토픽 publish 래퍼.

``servo_bridge`` 노드의 ``/servo_bridge/cmd_pan`` (std_msgs/Float32 deg) 로 setpoint
publish. servo_bridge 가 clamp + rate_limit 후 시리얼로 Arduino 에 전달.

namespace: 절대 path 라 gogoping_modes 의 ``namespace="gogoping"`` 와 무관 —
admin-app 의 CameraPanCard / control-service 의 camera_pan/ros_bridge.py 와 같은
토픽 공유.

PanCameraSweep behavior 가 본 client 를 통해 90 → 좌 → 우 → 90 시퀀스를 publish.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import rclpy.node


# servo_bridge 의 ~/cmd_pan — 절대 path. params.yaml 의 pan_topic 과 일치.
TOPIC_CMD_PAN = "/servo_bridge/cmd_pan"

# 펌웨어/노드 양쪽 clamp 범위 (gogoping_camera_pan/CLAUDE.md 참조)
PAN_MIN_DEG = 5.0
PAN_MAX_DEG = 175.0
PAN_CENTER_DEG = 90.0


class CameraPanClient:
    """카메라 pan 서보 setpoint publisher.

    생성 시 publisher 1개 생성. ``publish_pan(deg)`` 호출 시 clamp 후 publish.

    servo_bridge 가 펌웨어 watchdog (1000ms) 대응으로 20Hz 재송신 — 본 client 는
    1회 publish 만으로 충분. 즉 PanCameraSweep 의 각 step 진입 시 1회만 호출.
    """

    def __init__(self, node: "rclpy.node.Node"):
        from std_msgs.msg import Float32
        self.node = node
        self._pub = node.create_publisher(Float32, TOPIC_CMD_PAN, 10)

    def publish_pan(self, deg: float) -> float:
        """pan setpoint publish. clamp 적용 후 실제 publish 된 deg 반환."""
        from std_msgs.msg import Float32
        clamped = max(PAN_MIN_DEG, min(PAN_MAX_DEG, float(deg)))
        msg = Float32()
        msg.data = clamped
        self._pub.publish(msg)
        return clamped

    def center(self) -> float:
        """90° 복귀 — terminate/cleanup 시 호출."""
        return self.publish_pan(PAN_CENTER_DEG)
