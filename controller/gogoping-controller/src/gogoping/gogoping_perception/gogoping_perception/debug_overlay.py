"""perception debug 이미지 — YOLO 박스 오버레이 publish (subscriber 있을 때만)."""
from __future__ import annotations

from gogoping_perception.depth_utils import bbox_depth_median as _bbox_depth_median


class DebugOverlay:
    def __init__(self, publisher, bridge):
        self._pub = publisher       # None 이면 no-op (cv_bridge 미설치)
        self._bridge = bridge

    def publish(self, color, depth, results, state: str, target_id) -> None:
        if self._pub is None or self._pub.get_subscription_count() == 0:
            return
        try:
            import cv2
            annotated = color.copy()
            if results:
                r = results[0]
                if r.boxes is not None and len(r.boxes.xyxy) > 0:
                    xyxy = r.boxes.xyxy.cpu().numpy()
                    ids = (r.boxes.id.cpu().numpy().astype(int)
                           if r.boxes.id is not None else None)
                    confs = r.boxes.conf.cpu().numpy()
                    for i in range(len(xyxy)):
                        x1, y1, x2, y2 = map(int, xyxy[i].tolist())
                        tid = int(ids[i]) if ids is not None else -1
                        is_target = target_id is not None and tid == target_id
                        box_color = (0, 255, 0) if is_target else (255, 160, 0)
                        thick = 3 if is_target else 1
                        cv2.rectangle(annotated, (x1, y1), (x2, y2), box_color, thick)
                        d_mm = _bbox_depth_median(depth, (x1, y1, x2, y2))
                        dist = f" {d_mm / 1000.0:.2f}m" if d_mm > 0 else ""
                        cv2.putText(annotated, f"people{dist}", (x1, max(12, y1 - 5)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, box_color, 1, cv2.LINE_AA)
            cv2.putText(annotated, f"state={state}", (8, 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2, cv2.LINE_AA)
            msg = self._bridge.cv2_to_imgmsg(annotated, encoding="bgr8")
            msg.header.frame_id = "camera_color_optical_frame"
            self._pub.publish(msg)
        except Exception:
            pass
