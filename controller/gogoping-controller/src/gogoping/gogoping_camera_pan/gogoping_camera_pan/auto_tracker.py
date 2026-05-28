"""ROS node — perception 의 TrackingState bbox → camera pan/tilt servo 명령.

Subscribes:
- /gogoping/tracking_state (TrackingState)

Publishes:
- /servo_bridge/cmd_pan  (Float32, degrees, servo absolute)
- /servo_bridge/cmd_tilt (Float32, degrees, servo absolute)

동작:
- TrackingState.mode == "tracking" + matched 일 때만 bbox center 로 P-control.
- 그 외 (mode != tracking 또는 LOST_TIMEOUT_S 초 이상 stale) → home (pan=90, tilt=100) 복귀.
- step_limit 으로 한 tick 당 servo 변화 ≤ 5도 — 부드러운 회전.

추후 sweep + search 동작은 검증 후 추가 예정.
"""
from __future__ import annotations

import time
from typing import Optional

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32

from gogoping_msgs.msg import TrackingState

from gogoping_camera_pan.auto_tracker_logic import (
    compute_pan_target,
    compute_tilt_target,
    home_targets,
)
from gogoping_camera_pan.camera_tracking_config import (
    CMD_PAN_TOPIC,
    CMD_TILT_TOPIC,
    FRAME_H_PX,
    FRAME_W_PX,
    LOST_TIMEOUT_S,
    PAN_DEAD_ZONE_PX,
    PAN_HOME_DEG,
    PAN_MAX_DEG,
    PAN_MIN_DEG,
    PAN_P_GAIN_DEG_PER_PX,
    PAN_STEP_LIMIT_DEG,
    TILT_DEAD_ZONE_PX,
    TILT_HOME_DEG,
    TILT_MAX_DEG,
    TILT_MIN_DEG,
    TILT_P_GAIN_DEG_PER_PX,
    TILT_STEP_LIMIT_DEG,
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

        self.create_subscription(
            TrackingState, TRACKING_STATE_TOPIC, self._on_tracking_state, 10,
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

    def _tick(self) -> None:
        now = time.time()
        state = self._last_state
        stale = state is None or (now - self._last_state_ts) > LOST_TIMEOUT_S

        # perception 의 mode 값별 동작:
        # - "idle" / state=None : 추종 종료 — home 복귀
        # - "lost"              : 오랜 시간 사람 못 찾음 — home 복귀 (사용자가 멀리 갔을 수도)
        # - "searching"         : 잠시 detection drop — 마지막 위치 유지 (곧 돌아올 수 있음)
        # - "tracking"+matched  : 정상 — P-control
        if state is None or state.mode == "idle" or state.mode == "lost" or stale:
            pan_target, tilt_target = home_targets(PAN_HOME_DEG, TILT_HOME_DEG)
        elif state.mode == "searching" or not state.matched:
            # 짧은 lost — 마지막 servo 위치 유지, 사람이 다시 frame 들어오면 즉시 재추적
            pan_target = self._current_pan_deg
            tilt_target = self._current_tilt_deg
        else:
            assert state is not None
            cx = (float(state.bbox_x1) + float(state.bbox_x2)) / 2.0
            cy = (float(state.bbox_y1) + float(state.bbox_y2)) / 2.0
            pan_target = compute_pan_target(
                bbox_cx_px=cx, frame_w_px=FRAME_W_PX,
                current_pan_deg=self._current_pan_deg,
                dead_zone_px=PAN_DEAD_ZONE_PX,
                p_gain=PAN_P_GAIN_DEG_PER_PX,
                pan_min=PAN_MIN_DEG, pan_max=PAN_MAX_DEG,
                step_limit_deg=PAN_STEP_LIMIT_DEG,
            )
            tilt_target = compute_tilt_target(
                bbox_cy_px=cy, frame_h_px=FRAME_H_PX,
                current_tilt_deg=self._current_tilt_deg,
                dead_zone_px=TILT_DEAD_ZONE_PX,
                p_gain=TILT_P_GAIN_DEG_PER_PX,
                tilt_min=TILT_MIN_DEG, tilt_max=TILT_MAX_DEG,
                step_limit_deg=TILT_STEP_LIMIT_DEG,
            )

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
