"""Safety monitor — D435 depth + tracking_state → /gogoping/safety_stop publish.

판단 로직 (pure):
  (a) tracking_distance_mm > 0 and < SAFE_DISTANCE_MM → stop "person_close"
  (b) depth ROI (화면 하단 60%, bbox 외부) 의 < OBSTACLE_THRESHOLD_MM pixel
      ≥ OBSTACLE_MIN_PIXELS → stop "obstacle"
  (c) current_state in SAFETY_BYPASS_STATES → stop=False "bypassed_manual"

chatter hold + stale timeout 은 ROS node 가 담당. evaluate_safety 는 stateless.

수동 모드 (MANUAL) 는 spec 대로 항상 bypass — 개발자가 상황 판단.

2026-05-28 추가 (graph_router 심화):
  evaluate_proximity_level — person_dist_m / current_state →
  "ok" | "person_close". /gogoping/proximity_event JSON publish.
  (person-only: 장애물 wall_close 반응 제거 — 충돌 안전은 위 (b) safety_stop 가 담당.)
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

from gogoping_perception import config


@dataclass
class SafetyEvalContext:
    depth: np.ndarray                           # H×W uint16, mm
    tracking_distance_mm: int                   # 0 = invalid
    tracking_bbox: Optional[tuple]              # (x1, y1, x2, y2) or None
    current_state: str                          # FSM state


@dataclass
class SafetyDecision:
    stop: bool
    reason: str   # "ok" | "person_close" | "obstacle" | "bypassed_manual"


def evaluate_safety(ctx: SafetyEvalContext) -> SafetyDecision:
    """pure-logic: depth + tracking → stop decision. stateless."""
    # (c) bypass — manual 등
    if ctx.current_state in config.SAFETY_BYPASS_STATES:
        return SafetyDecision(stop=False, reason="bypassed_manual")

    # (a) 사람 거리 floor
    if 0 < ctx.tracking_distance_mm < config.SAFE_DISTANCE_MM:
        return SafetyDecision(stop=True, reason="person_close")

    # (b) obstacle in ROI (하단 60%, bbox 외부)
    if ctx.depth is None or ctx.depth.size == 0:
        return SafetyDecision(stop=False, reason="ok")
    h, w = ctx.depth.shape[:2]
    y_start = int(h * config.OBSTACLE_ROI_TOP_RATIO)
    roi = ctx.depth[y_start:, :]
    close_mask = (roi > 0) & (roi < config.OBSTACLE_THRESHOLD_MM)
    if ctx.tracking_bbox is not None:
        bx1, by1, bx2, by2 = ctx.tracking_bbox
        by1_roi = max(0, by1 - y_start)
        by2_roi = max(0, by2 - y_start)
        bx1_roi = max(0, bx1)
        bx2_roi = min(w, bx2)
        if by2_roi > 0 and bx2_roi > bx1_roi:
            close_mask[by1_roi:by2_roi, bx1_roi:bx2_roi] = False
    if int(close_mask.sum()) >= config.OBSTACLE_MIN_PIXELS:
        return SafetyDecision(stop=True, reason="obstacle")
    return SafetyDecision(stop=False, reason="ok")


def evaluate_proximity_level(
    person_dist_m: float,
    current_state: str,
) -> str:
    """Pure logic — graph_router 가 구독하는 proximity_event 의 level 결정.

    Returns: "ok" | "person_close"

    사람 근접만 판정한다 (person-only). 장애물(wall_close) 반응은 제거됨 —
    기본 충돌 안전은 evaluate_safety 의 safety_stop 이 담당. bypass > person_close > ok.
    """
    if current_state in config.SAFETY_BYPASS_STATES:
        return "ok"
    if person_dist_m <= config.PERSON_FRONT_DIST_M:
        return "person_close"
    return "ok"


def _make_ros_node():
    """ROS wrapper — lazy import so pure-logic tests work without ROS."""
    import rclpy
    from gogoping_msgs.msg import TrackingState
    from rclpy.node import Node
    from std_msgs.msg import Bool, Float32, String
    from gogoping_perception.shm_reader import ShmReader

    class SafetyMonitorNode(Node):
        """ROS wrapper — depth shm + tracking_state + state 구독 →
        /gogoping/safety_stop + /gogoping/proximity_event publish.
        """

        def __init__(self) -> None:
            super().__init__("gogoping_safety_monitor")
            self._reader: Optional[ShmReader] = None
            self._tracking_distance_mm: int = 0
            self._tracking_bbox: Optional[tuple] = None
            self._current_state: str = "IDLE"
            self._last_stop_ts: float = 0.0
            # graph_router 심화 (2026-05-28)
            self._person_dist_m: float = float("inf")

            self._pub = self.create_publisher(Bool, "/gogoping/safety_stop", 10)
            self._prox_pub = self.create_publisher(
                String, "/gogoping/proximity_event", 10,
            )
            self.create_subscription(
                TrackingState, "/gogoping/tracking_state", self._on_tracking, 10,
            )
            self.create_subscription(
                String, "/gogoping/state_str", self._on_state_str, 10,
            )
            self.create_subscription(
                Float32, "/gogoping/person_proximity",
                self._on_person_proximity, 10,
            )
            self._timer = self.create_timer(
                1.0 / config.SAFETY_PUBLISH_HZ, self._tick,
            )
            try:
                self._reader = ShmReader()
                self.get_logger().info("safety_monitor: shm attached")
            except Exception as e:  # noqa: BLE001
                self.get_logger().warn(f"safety_monitor: shm attach failed: {e}")

        def _on_tracking(self, msg: TrackingState) -> None:
            self._tracking_distance_mm = int(msg.distance_m * 1000.0) if msg.matched else 0
            if msg.matched:
                self._tracking_bbox = (msg.bbox_x1, msg.bbox_y1, msg.bbox_x2, msg.bbox_y2)
            else:
                self._tracking_bbox = None

        def _on_state_str(self, msg: String) -> None:
            self._current_state = msg.data

        def _on_person_proximity(self, msg: Float32) -> None:
            self._person_dist_m = float(msg.data)

        def _tick(self) -> None:
            depth = None
            if self._reader is not None:
                try:
                    snap = self._reader.poll(timeout=0.05)
                    if snap is not None:
                        depth = snap.depth
                except Exception:
                    depth = None

            ctx = SafetyEvalContext(
                depth=depth if depth is not None else np.zeros((0, 0), dtype=np.uint16),
                tracking_distance_mm=self._tracking_distance_mm,
                tracking_bbox=self._tracking_bbox,
                current_state=self._current_state,
            )
            decision = evaluate_safety(ctx)

            now = time.time()
            if decision.stop:
                self._last_stop_ts = now
            elif (now - self._last_stop_ts) < config.SAFETY_CHATTER_HOLD_S:
                decision = SafetyDecision(stop=True, reason="hold")

            self._pub.publish(Bool(data=decision.stop))
            if decision.stop:
                self.get_logger().info(f"safety_stop=True reason={decision.reason}")

            # ── graph_router 심화 — proximity_event JSON (person-only) ──────
            level = evaluate_proximity_level(
                person_dist_m=self._person_dist_m,
                current_state=self._current_state,
            )
            payload = {
                "ts": now,
                "level": level,
                "person_dist_m": float(self._person_dist_m)
                if self._person_dist_m != float("inf") else None,
            }
            self._prox_pub.publish(String(data=json.dumps(payload)))

    return SafetyMonitorNode


class SafetyMonitorNode:
    """Placeholder that instantiates the real ROS node on demand."""
    def __new__(cls, *args, **kwargs):
        real_cls = _make_ros_node()
        return real_cls(*args, **kwargs)


def main() -> None:
    import rclpy
    rclpy.init()
    node = _make_ros_node()()
    try:
        import rclpy as _rclpy
        _rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        import rclpy as _rclpy
        _rclpy.shutdown()


if __name__ == "__main__":
    main()
