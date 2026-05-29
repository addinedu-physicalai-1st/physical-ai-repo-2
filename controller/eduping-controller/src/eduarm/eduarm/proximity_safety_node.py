"""근접 안전정지 감지 — D435 로 **사람**이 너무 가까운지 판정해 publish.

device-local: 카메라와 같은 머신(eduping 노트북)에서
  - /d435/color/image_raw           → YOLO 사람 검출 (classes=[0])
  - /d435/aligned_depth_to_color/image_raw → 사람 bbox 영역의 거리(mm)
를 결합한다. 검출된 사람 중 0.6m 이내(히스테리시스 해제 0.65m)면
`/eduping/proximity_block`(Bool true)을 송출. control bridge 가 받아 팔을 정지/재개하고,
robot-web 이 (율동/무궁화) 음악을 정지/재개.

**사람 검출 게이트인 이유**: depth-only naive min 은 로봇 자기 팔(가리기 자세로 D435 를
향함)·바닥·구조물이 0.6m 안에 잡혀 영구 block 됐다. 이제 "사람" bbox 의 depth 만 보므로
팔·바닥은 트리거하지 않는다.

aligned depth 는 color 프레임에 정렬돼 같은 해상도/픽셀 좌표 → color bbox 를 그대로
depth 인덱스로 사용. color/depth 는 시간 스큐가 작아 최신 depth 캐시로 샘플(별도 동기화
불필요, 안전 판정엔 충분).

판정은 eduarm.proximity (순수 로직 — tests/test_proximity.py).
latched(transient_local) QoS — 늦게 붙는 구독자(bridge)도 마지막 상태를 즉시 받음.
"""
from __future__ import annotations

import time

import numpy as np
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSProfile, QoSReliabilityPolicy
from sensor_msgs.msg import Image
from std_msgs.msg import Bool

from eduarm.proximity import (
    CLEAR_MM_DEFAULT,
    MIN_VALID_PX_DEFAULT,
    NEAR_MM_DEFAULT,
    OFF_FRAMES_DEFAULT,
    ON_FRAMES_DEFAULT,
    PERSON_PCTL_DEFAULT,
    decide_block,
    person_distance_mm,
    step_debounce,
)

COLOR_TOPIC = "/d435/color/image_raw"
DEPTH_TOPIC = "/d435/aligned_depth_to_color/image_raw"
BLOCK_TOPIC = "/eduping/proximity_block"


class ProximitySafety(Node):
    def __init__(self) -> None:
        super().__init__("proximity_safety")
        self.declare_parameter("color_topic", COLOR_TOPIC)
        self.declare_parameter("depth_topic", DEPTH_TOPIC)
        self.declare_parameter("near_mm", NEAR_MM_DEFAULT)
        self.declare_parameter("clear_mm", CLEAR_MM_DEFAULT)
        self.declare_parameter("person_pctl", PERSON_PCTL_DEFAULT)
        self.declare_parameter("min_valid_px", MIN_VALID_PX_DEFAULT)
        self.declare_parameter("yolo_model", "yolov8n.pt")
        self.declare_parameter("yolo_conf", 0.25)
        self.declare_parameter("yolo_imgsz", 640)
        self.declare_parameter("throttle_hz", 8.0)
        # 시간 디바운스 — 검출 깜빡임(occlusion/근접 crop)이 pause/resume thrash 로 번지는 것 방지.
        self.declare_parameter("on_frames", ON_FRAMES_DEFAULT)
        self.declare_parameter("off_frames", OFF_FRAMES_DEFAULT)

        gp = self.get_parameter
        color_topic = gp("color_topic").get_parameter_value().string_value
        depth_topic = gp("depth_topic").get_parameter_value().string_value
        self._near = int(gp("near_mm").get_parameter_value().integer_value)
        self._clear = int(gp("clear_mm").get_parameter_value().integer_value)
        self._pctl = int(gp("person_pctl").get_parameter_value().integer_value)
        self._min_px = int(gp("min_valid_px").get_parameter_value().integer_value)
        self._yolo_conf = float(gp("yolo_conf").get_parameter_value().double_value)
        self._yolo_imgsz = int(gp("yolo_imgsz").get_parameter_value().integer_value)
        hz = float(gp("throttle_hz").get_parameter_value().double_value)
        self._min_period = 1.0 / max(0.1, hz)
        self._on_frames = int(gp("on_frames").get_parameter_value().integer_value)
        self._off_frames = int(gp("off_frames").get_parameter_value().integer_value)

        from ultralytics import YOLO  # lazy — import 비용 큼
        self._yolo = YOLO(gp("yolo_model").get_parameter_value().string_value)

        self._bridge = CvBridge()
        self._blocked = False
        self._streak = 0
        self._latest_depth: np.ndarray | None = None
        self._last_infer = 0.0

        # latched — bridge 가 나중에 붙어도 마지막 block 상태를 즉시 받음.
        latched = QoSProfile(
            depth=1,
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
        )
        self._pub = self.create_publisher(Bool, BLOCK_TOPIC, latched)
        self._pub.publish(Bool(data=False))  # 초기 상태 명시 송출
        self.create_subscription(Image, depth_topic, self._on_depth, 1)
        self.create_subscription(Image, color_topic, self._on_color, 1)
        self.get_logger().info(
            f"proximity_safety up — person-gated, color={color_topic} "
            f"depth={depth_topic} near<{self._near}mm clear>{self._clear}mm"
        )

    def _on_depth(self, msg: Image) -> None:
        # 16UC1 little-endian (RealSense, aligned-to-color). 최신 프레임만 캐시.
        try:
            self._latest_depth = np.frombuffer(
                msg.data, dtype=np.uint16
            ).reshape(msg.height, msg.width)
        except Exception as exc:  # noqa: BLE001
            self.get_logger().warn(f"depth decode 실패: {exc}")

    def _on_color(self, msg: Image) -> None:
        now = time.monotonic()
        if now - self._last_infer < self._min_period:
            return
        self._last_infer = now
        depth = self._latest_depth
        if depth is None:
            return
        try:
            bgr = self._bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except Exception as exc:  # noqa: BLE001
            self.get_logger().warn(f"cv_bridge failed: {exc}")
            return

        bboxes = self._detect_persons(bgr)
        dists = [
            person_distance_mm(depth, b, percentile=self._pctl, min_valid_px=self._min_px)
            for b in bboxes
        ]
        raw = decide_block(dists, self._blocked, near_mm=self._near, clear_mm=self._clear)
        blocked, self._streak = step_debounce(
            self._blocked, raw, self._streak,
            on_frames=self._on_frames, off_frames=self._off_frames,
        )
        if blocked != self._blocked:
            self._blocked = blocked
            self._pub.publish(Bool(data=blocked))
            self.get_logger().info(f"proximity_block = {blocked} (persons={len(bboxes)})")

    def _detect_persons(self, bgr) -> list[tuple[float, float, float, float]]:
        try:
            results = self._yolo(
                bgr, classes=[0], conf=self._yolo_conf,
                imgsz=self._yolo_imgsz, verbose=False,
            )
        except Exception as exc:  # noqa: BLE001
            self.get_logger().warn(f"yolo detect failed: {exc}")
            return []
        out: list[tuple[float, float, float, float]] = []
        if results:
            r = results[0]
            if r.boxes is not None and len(r.boxes):
                for xyxy in r.boxes.xyxy.cpu().numpy():
                    x1, y1, x2, y2 = (float(v) for v in xyxy.tolist())
                    out.append((x1, y1, x2, y2))
        return out


def main() -> None:
    rclpy.init()
    node = ProximitySafety()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
