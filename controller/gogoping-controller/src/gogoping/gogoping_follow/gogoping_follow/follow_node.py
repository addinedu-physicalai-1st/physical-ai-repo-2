"""gogoping_follow ROS 노드 — Image + Scan + FollowTarget → cmd_vel + TrackingState.

Image frame 마다 단일 target YOLO + ReID 매칭 → bbox + LiDAR clamp 로 P 컨트롤.
"""
import math
import time

import rclpy
from cv_bridge import CvBridge
from geometry_msgs.msg import Twist
from rclpy.node import Node
from sensor_msgs.msg import Image, LaserScan

from gogoping_msgs.msg import FollowTarget, TrackingState

from gogoping_follow.config import (
    CMD_VEL_HZ,
    TRACKING_STATE_HZ,
    LOST_TIMEOUT_S,
)
from gogoping_follow.teacher_detector import Detection, TeacherDetector
from gogoping_follow.teacher_follower import TeacherFollower


class FollowNode(Node):
    def __init__(self) -> None:
        super().__init__("gogoping_follow_node")
        self._bridge = CvBridge()
        self._detector: TeacherDetector | None = None
        self._follower = TeacherFollower(image_width=640)

        self._target_id: str = ""
        self._target_name: str = ""
        self._last_detection: Detection | None = None
        self._last_detection_ts: float = 0.0
        self._last_lidar_front_min: float = 10.0

        self.create_subscription(Image, "/camera/image_raw", self._on_image, 10)
        self.create_subscription(LaserScan, "/scan", self._on_scan, 10)
        self.create_subscription(
            FollowTarget, "/gogoping/follow_target", self._on_follow_target, 10
        )
        self._cmd_pub = self.create_publisher(Twist, "/cmd_vel", 10)
        self._state_pub = self.create_publisher(
            TrackingState, "/gogoping/tracking_state", 10
        )
        self.create_timer(1.0 / CMD_VEL_HZ, self._tick_control)
        self.create_timer(1.0 / TRACKING_STATE_HZ, self._tick_state)
        self.get_logger().info(
            "FollowNode initialized — waiting for FollowTarget (YOLO+ReID lazy-load on first target)"
        )

    def _ensure_detector(self) -> TeacherDetector | None:
        if self._detector is not None:
            return self._detector
        try:
            self._detector = TeacherDetector()
            self.get_logger().info("TeacherDetector ready (YOLO + ReID loaded)")
        except RuntimeError as e:
            self.get_logger().warn(f"TeacherDetector lazy-load failed: {e}")
            self._detector = None
        return self._detector

    def _on_follow_target(self, msg: FollowTarget) -> None:
        if not msg.teacher_id:
            self._target_id = ""
            self._target_name = ""
            self._last_detection = None
            if self._detector is not None:
                self._detector.clear_target()
            self.get_logger().info("FollowTarget stop")
            return
        detector = self._ensure_detector()
        if detector is None:
            self.get_logger().warn("Cannot start follow — detector unavailable")
            return
        self._target_id = msg.teacher_id
        self._target_name = msg.teacher_name
        detector.set_target(list(msg.embedding))
        self.get_logger().info(
            f"FollowTarget start: {msg.teacher_name} ({msg.teacher_id[:8]}...)"
        )

    def _on_image(self, msg: Image) -> None:
        if not self._target_id:
            self._last_detection = None
            return
        detector = self._ensure_detector()
        if detector is None:
            return
        try:
            frame = self._bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except Exception as e:
            self.get_logger().warn(f"cv_bridge convert failed: {e}")
            return
        det = detector.step(frame)
        if det is not None:
            self._last_detection = det
            self._last_detection_ts = time.time()

    def _on_scan(self, msg: LaserScan) -> None:
        n = len(msg.ranges)
        if n == 0:
            return
        center = n // 2
        window = max(1, n // 24)  # ±7.5° approx of ±15° area
        front = [
            r for r in msg.ranges[center - window : center + window]
            if not math.isinf(r) and not math.isnan(r) and r > 0.05
        ]
        self._last_lidar_front_min = min(front) if front else 10.0

    def _tick_control(self) -> None:
        if not self._target_id:
            return
        det = self._last_detection
        if det is None or (time.time() - self._last_detection_ts) > LOST_TIMEOUT_S:
            self._cmd_pub.publish(Twist())  # safety stop
            return
        x1, y1, x2, y2 = det.bbox
        cx = (x1 + x2) / 2.0
        size = math.sqrt(max(1, (x2 - x1) * (y2 - y1)))
        cmd = self._follower.step(
            bbox_center_x=cx,
            bbox_size_px=size,
            lidar_min_m=self._last_lidar_front_min,
        )
        twist = Twist()
        twist.linear.x = cmd.linear_x
        twist.angular.z = cmd.angular_z
        self._cmd_pub.publish(twist)

    def _tick_state(self) -> None:
        msg = TrackingState()
        now = time.time()
        if not self._target_id:
            msg.mode = "idle"
            msg.matched = False
            msg.distance_m = float("nan")
            msg.angle_deg = float("nan")
            msg.bbox_size_px = 0
            msg.bbox_x1 = 0
            msg.bbox_y1 = 0
            msg.bbox_x2 = 0
            msg.bbox_y2 = 0
            msg.track_id = 0
            msg.reid_sim = float("nan")
        elif self._last_detection is not None and (now - self._last_detection_ts) < LOST_TIMEOUT_S:
            msg.mode = "tracking"
            msg.matched = True
            msg.distance_m = float(self._last_lidar_front_min)
            x1, y1, x2, y2 = self._last_detection.bbox
            offset_px = self._follower.image_center - (x1 + x2) / 2.0
            msg.angle_deg = float(offset_px * 0.1)  # rough estimate
            msg.bbox_size_px = int(math.sqrt(max(1, (x2 - x1) * (y2 - y1))))
            msg.bbox_x1 = int(x1)
            msg.bbox_y1 = int(y1)
            msg.bbox_x2 = int(x2)
            msg.bbox_y2 = int(y2)
            msg.track_id = 0  # ByteTrack 미통합 — 별도 perception 노드에서 채우게 됨
            msg.reid_sim = float(self._last_detection.reid_sim)
        else:
            msg.mode = "searching"
            msg.matched = False
            msg.distance_m = float("nan")
            msg.angle_deg = float("nan")
            msg.bbox_size_px = 0
            msg.bbox_x1 = 0
            msg.bbox_y1 = 0
            msg.bbox_x2 = 0
            msg.bbox_y2 = 0
            msg.track_id = 0
            msg.reid_sim = float("nan")
        msg.teacher_id = self._target_id
        msg.ts_ms = int(now * 1000)
        self._state_pub.publish(msg)


def main() -> None:
    rclpy.init()
    node = FollowNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
