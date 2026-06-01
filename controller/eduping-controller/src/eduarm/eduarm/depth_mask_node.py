"""depth_mask_node — D435 depth image 에서 등록 어린이의 손 영역을 0 으로 지워 MoveIt
OccupancyMapMonitor 가 octomap voxel 을 만들지 못하게 한다.

문제:
  highfive_sim 의 octomap 은 D435 가 보는 모든 것 (배경 가구·사람·벽) 을 obstacle 로
  보고 IK 가 avoid_collisions=True 로 통과 못 하게 막는다 — 안전상 정확하지만, 정작
  high-five 의 타겟인 "어린이의 손" 까지 obstacle 로 잡혀 IK 가 그 위치에 도달 못 함.

해결:
  하이파이브 대상 좌표 (`/eduping/highfive/hand_point`) 가 들어올 때마다 그 점 주변
  반경 mask_radius_m (default 0.20m) 의 sphere 를 D435 depth pixel 평면에 투영해 그
  원 안쪽 픽셀을 0 으로 마스킹 → octomap monitor 는 그 영역을 "데이터 없음" 으로
  취급 → voxel 안 만들어짐 → IK 가 손 위치까지 도달 가능.
  손 위치는 mask_ttl_s 동안 유지 — point 가 사라지면 마스킹 해제 → octomap 가 즉시
  배경 복귀.

토픽:
  입력  /d435/depth/image_rect_raw  (sensor_msgs/Image, 16UC1 mm)
        /d435/depth/camera_info     (sensor_msgs/CameraInfo — fx, fy, cx, cy)
        /eduping/highfive/hand_point (geometry_msgs/PointStamped, d435_depth_optical_frame)
  출력  /d435/depth/image_rect_raw/masked (sensor_msgs/Image, 동일 encoding)

본 노드는 cv_bridge + numpy 만 사용 — system python3 (numpy 1.26 + cv_bridge ABI) 로
돌아야 함 (conda numpy 2.x 와 ABI 충돌). d435_depth_streamer 와 동일 제약.

쓰임:
  highfive_sim.launch.py 가 본 노드를 띄움. octomap 비활성 상태에선 마스킹 결과를
  소비하는 컨슈머가 없어 무해한 passthrough — 추후 octomap 부활 시 sensors_3d.yaml
  의 image_topic 을 masked 토픽으로 가리키면 자동 연결.
"""
from __future__ import annotations

from typing import Optional

import cv2
import numpy as np
import rclpy
from cv_bridge import CvBridge
from geometry_msgs.msg import PointStamped
from rclpy.duration import Duration
from rclpy.node import Node
from sensor_msgs.msg import CameraInfo, Image
import tf2_ros
from tf2_geometry_msgs import do_transform_point


class DepthMaskNode(Node):
    def __init__(self) -> None:
        super().__init__("depth_mask_node")
        self.declare_parameter("input_topic", "/d435/depth/image_rect_raw")
        self.declare_parameter("camera_info_topic", "/d435/depth/camera_info")
        self.declare_parameter("hand_point_topic", "/eduping/highfive/hand_point")
        self.declare_parameter("output_topic", "/d435/depth/image_rect_raw/masked")
        # OccupancyMapMonitor (image_transport) 가 image_topic 와 동일 prefix 에서
        # camera_info 를 찾음 — image=/d435/depth/image_rect_raw/masked 이면
        # /d435/depth/image_rect_raw/camera_info 를 봄. realsense 가 publish 하는 곳
        # (/d435/depth/camera_info) 과 어긋나서 octomap 가 CameraInfo received: 0 으로
        # 굳어 collision 데이터 없음. 본 노드가 받은 CameraInfo 그대로 새 토픽에 fan-out.
        self.declare_parameter(
            "output_camera_info_topic",
            "/d435/depth/image_rect_raw/camera_info",
        )
        self.declare_parameter("camera_frame", "d435_depth_optical_frame")
        # 20cm 면 손바닥 + 손목 + 5cm 여유. 너무 크면 인접 가구가 같이 뚫림.
        self.declare_parameter("mask_radius_m", 0.20)
        # hand_point 가 1.0s 이상 안 들어오면 마스킹 해제 (어린이 떠난 것으로 간주).
        self.declare_parameter("mask_ttl_s", 1.0)

        self._input_topic = self.get_parameter(
            "input_topic").get_parameter_value().string_value
        self._info_topic = self.get_parameter(
            "camera_info_topic").get_parameter_value().string_value
        self._hand_topic = self.get_parameter(
            "hand_point_topic").get_parameter_value().string_value
        self._output_topic = self.get_parameter(
            "output_topic").get_parameter_value().string_value
        self._output_info_topic = self.get_parameter(
            "output_camera_info_topic").get_parameter_value().string_value
        self._camera_frame = self.get_parameter(
            "camera_frame").get_parameter_value().string_value
        self._mask_radius_m = float(self.get_parameter(
            "mask_radius_m").get_parameter_value().double_value)
        self._mask_ttl_s = float(self.get_parameter(
            "mask_ttl_s").get_parameter_value().double_value)

        self._bridge = CvBridge()
        self._fx: Optional[float] = None
        self._fy: Optional[float] = None
        self._cx: Optional[float] = None
        self._cy: Optional[float] = None
        # 마지막 hand point — camera_frame 좌표계 (depth optical).
        self._hand_xyz: Optional[tuple[float, float, float]] = None
        self._hand_received_at_s: float = 0.0

        self._tf_buffer = tf2_ros.Buffer()
        self._tf_listener = tf2_ros.TransformListener(self._tf_buffer, self)

        self._info_sub = self.create_subscription(
            CameraInfo, self._info_topic, self._on_info, 10,
        )
        self._hand_sub = self.create_subscription(
            PointStamped, self._hand_topic, self._on_hand, 10,
        )
        self._depth_sub = self.create_subscription(
            Image, self._input_topic, self._on_depth, 5,
        )
        self._depth_pub = self.create_publisher(Image, self._output_topic, 5)
        # CameraInfo fan-out — image_transport convention 에 맞춰 image 와 동일 ns 에.
        self._info_pub = self.create_publisher(CameraInfo, self._output_info_topic, 10)

        self.get_logger().info(
            f"depth_mask_node ready — mask r={self._mask_radius_m:.2f}m "
            f"ttl={self._mask_ttl_s:.1f}s "
            f"sub {self._input_topic} + {self._hand_topic} → pub {self._output_topic} "
            f"+ camera_info {self._info_topic} → {self._output_info_topic}",
        )

    def _on_info(self, msg: CameraInfo) -> None:
        # CameraInfo.k 는 3x3 row-major: [fx 0 cx; 0 fy cy; 0 0 1].
        k = msg.k
        self._fx, self._fy, self._cx, self._cy = (
            float(k[0]), float(k[4]), float(k[2]), float(k[5]),
        )
        # image_transport 가 같은 ns 에서 찾는 토픽으로 그대로 fan-out.
        self._info_pub.publish(msg)

    def _on_hand(self, msg: PointStamped) -> None:
        # hand_point 는 보통 d435_depth_optical_frame 으로 publish (DepthViewer 기준).
        # 다른 frame 이면 TF 로 변환. 동일하면 변환 생략 (성능).
        if msg.header.frame_id == self._camera_frame:
            x, y, z = msg.point.x, msg.point.y, msg.point.z
        else:
            try:
                tform = self._tf_buffer.lookup_transform(
                    self._camera_frame, msg.header.frame_id,
                    rclpy.time.Time(), timeout=Duration(seconds=0.05),
                )
            except (tf2_ros.LookupException, tf2_ros.ConnectivityException,
                    tf2_ros.ExtrapolationException) as exc:
                self.get_logger().warn(
                    f"TF {msg.header.frame_id} → {self._camera_frame} 실패: {exc}",
                    throttle_duration_sec=2.0,
                )
                return
            transformed = do_transform_point(msg, tform)
            x, y, z = transformed.point.x, transformed.point.y, transformed.point.z

        self._hand_xyz = (float(x), float(y), float(z))
        self._hand_received_at_s = self._now_s()

    def _on_depth(self, msg: Image) -> None:
        # 카메라 intrinsic 도착 전엔 그냥 passthrough.
        if self._fx is None:
            self._depth_pub.publish(msg)
            return

        # hand 없거나 stale → passthrough (octomap 가 정상 동작).
        now_s = self._now_s()
        if (self._hand_xyz is None
                or now_s - self._hand_received_at_s > self._mask_ttl_s):
            self._depth_pub.publish(msg)
            return

        x, y, z = self._hand_xyz
        if z <= 0.0:
            self._depth_pub.publish(msg)
            return

        # pinhole projection: (u, v) = (fx*x/z + cx, fy*y/z + cy).
        assert self._fy is not None and self._cx is not None and self._cy is not None
        u = int(round(x * self._fx / z + self._cx))
        v = int(round(y * self._fy / z + self._cy))
        # mask 반경 (pixel) — 손 위치 z 깊이에서 mask_radius_m 가 차지하는 픽셀 수.
        r_px = max(1, int(round(self._mask_radius_m * self._fx / z)))

        # 16UC1 또는 32FC1 둘 다 처리. cv_bridge 가 알아서 numpy 로.
        try:
            img = self._bridge.imgmsg_to_cv2(msg, msg.encoding).copy()
        except Exception as exc:
            self.get_logger().warn(
                f"cv_bridge decode 실패 ({msg.encoding}): {exc}", throttle_duration_sec=2.0,
            )
            self._depth_pub.publish(msg)
            return

        h, w = img.shape[:2]
        if 0 <= u < w and 0 <= v < h:
            # 단색 0 으로 채우기 — circle.
            cv2.circle(img, (u, v), r_px, 0, thickness=-1)
            # 너무 가깝거나 부분 가려진 경우엔 radius 가 큼 — 클램핑은 cv2.circle 가 알아서.
        else:
            # 손이 시야 밖 — depth 변형 없이 그대로 통과.
            self._depth_pub.publish(msg)
            return

        try:
            out = self._bridge.cv2_to_imgmsg(img, encoding=msg.encoding)
        except Exception as exc:
            self.get_logger().warn(
                f"cv_bridge encode 실패: {exc}", throttle_duration_sec=2.0,
            )
            self._depth_pub.publish(msg)
            return
        out.header = msg.header
        # 단순 보존 — same step / encoding / is_bigendian.
        out.is_bigendian = msg.is_bigendian
        out.step = msg.step
        self._depth_pub.publish(out)

    def _now_s(self) -> float:
        return float(self.get_clock().now().nanoseconds * 1e-9)


def main(args: list[str] | None = None) -> int:
    rclpy.init(args=args)
    node = DepthMaskNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    main()
