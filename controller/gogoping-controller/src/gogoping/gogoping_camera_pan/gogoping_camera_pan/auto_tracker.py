"""ROS node — camera pan/tilt 정면 고정 + voice mode 점유 회피.

Subscribes:
- /gogoping/follow_state (String) — follow_node 의 mode. voice_* 일 때 publish inhibit.

Publishes:
- /servo_bridge/cmd_pan  (Float32, degrees, servo absolute)
- /servo_bridge/cmd_tilt (Float32, degrees, servo absolute)

동작 (단순화):
- 항상 home(pan=90°, tilt=100°) 발행 — 변화 있을 때만 publish.
- follow_node 가 voice_search/voice_found/voice_resume 상태면 publish 전부 inhibit
  (follow_node 가 PAN/TILT 를 점유. servo 충돌 회피).

배경 (P-control 제거 이유):
- 이전엔 bbox 자동 추적 (P-control) 했으나, follow 모드에서 robot 본체와 카메라 방향이
  어긋나는 케이스 발생 (카메라는 사람, 본체는 벽). 추종 안정성 위해 PAN/TILT 정면 고정.
- 사람 찾기는 음성/디버그 버튼 ("위치확인") 으로만 트리거 — follow_node 가 PAN sweep 수행.
"""
from __future__ import annotations

import time
from typing import Optional

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32, String

from gogoping_msgs.msg import TrackingState

from gogoping_camera_pan.auto_tracker_logic import home_targets
from gogoping_camera_pan.camera_tracking_config import (
    CMD_PAN_TOPIC,
    CMD_TILT_TOPIC,
    PAN_HOME_DEG,
    TILT_HOME_DEG,
    TRACK_HZ,
    TRACKING_STATE_TOPIC,
)


class AutoTrackerNode(Node):
    def __init__(self) -> None:
        super().__init__("gogoping_camera_auto_tracker")

        self._last_state: Optional[TrackingState] = None
        self._last_state_ts: float = 0.0
        self._current_pan_deg: float = PAN_HOME_DEG
        self._current_tilt_deg: float = TILT_HOME_DEG
        # follow_node 의 mode — voice_* 일 때 publish inhibit (servo 충돌 회피).
        self._follow_mode: Optional[str] = None

        self.create_subscription(
            TrackingState, TRACKING_STATE_TOPIC, self._on_tracking_state, 10,
        )
        self.create_subscription(
            String, "/gogoping/follow_state", self._on_follow_state, 10,
        )
        self._pan_pub = self.create_publisher(Float32, CMD_PAN_TOPIC, 10)
        self._tilt_pub = self.create_publisher(Float32, CMD_TILT_TOPIC, 10)

        self.create_timer(1.0 / TRACK_HZ, self._tick)

        self.get_logger().info(
            f"AutoTrackerNode initialized -- track @ {TRACK_HZ} Hz, "
            f"home (pan,tilt)=({PAN_HOME_DEG}, {TILT_HOME_DEG})"
        )

    def _on_tracking_state(self, msg: TrackingState) -> None:
        self._last_state = msg
        self._last_state_ts = time.time()

    def _on_follow_state(self, msg: String) -> None:
        """follow_node 의 mode 추적 — voice_* 일 때 publish inhibit."""
        self._follow_mode = msg.data

    _VOICE_MODES = frozenset({"voice_search", "voice_found", "voice_resume"})

    def _tick(self) -> None:
        # follow_node 가 voice mode 중이면 PAN/TILT 점유 — auto_tracker publish 차단.
        # servo_bridge watchdog (1s) 가 마지막 setpoint 유지하니 깜빡임 없음.
        if self._follow_mode in self._VOICE_MODES:
            return

        # 추종 안정성 — PAN/TILT 정면 고정. 사람 자동 추적 안 함.
        # 사람 찾기는 음성/버튼 "위치확인" 으로만 트리거 — follow_node 가 PAN sweep.
        pan_target, tilt_target = home_targets(PAN_HOME_DEG, TILT_HOME_DEG)

        # 변화가 있을 때만 publish — servo bus traffic 최소화.
        if pan_target != self._current_pan_deg:
            self._current_pan_deg = pan_target
            self._pan_pub.publish(Float32(data=float(pan_target)))
        if tilt_target != self._current_tilt_deg:
            self._current_tilt_deg = tilt_target
            self._tilt_pub.publish(Float32(data=float(tilt_target)))


def main() -> None:
    rclpy.init()
    node = AutoTrackerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
