"""교사 추종 P 컨트롤 — bbox + LiDAR 입력 → Twist 출력.

상태 없음 — step() 마다 입력만으로 결정. ROS 와 분리되어 단위 테스트 가능.
"""
from dataclasses import dataclass

from gogoping_follow.config import (
    KP_DIST, KP_ANGLE,
    TARGET_BBOX_AREA_PX, ANGLE_DEADZONE_PX,
    LINEAR_X_MAX, ANGULAR_Z_MAX,
    LIDAR_HARD_STOP_M, LIDAR_SLOW_M,
)


@dataclass
class TwistCommand:
    linear_x: float = 0.0
    angular_z: float = 0.0


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


class TeacherFollower:
    """순수 P 컨트롤.

    image_width: 카메라 가로 해상도 (px). 중심선 = image_width / 2.
    """

    def __init__(self, image_width: int = 640) -> None:
        self.image_width = image_width
        self.image_center = image_width / 2.0

    def step(
        self,
        *,
        bbox_center_x: float,
        bbox_size_px: float,
        lidar_min_m: float,
    ) -> TwistCommand:
        """입력 → Twist 출력.

        bbox_center_x: bbox 중심 x 좌표 (px, 0=왼쪽 끝)
        bbox_size_px:  bbox 한 변의 길이 (sqrt(area)) — 거리 proxy
        lidar_min_m:   카메라 전방 ±15° 범위 LiDAR 최솟값 (m)
        """
        # LiDAR hard stop
        if lidar_min_m <= LIDAR_HARD_STOP_M:
            return TwistCommand(0.0, 0.0)

        # 거리 제어 — bbox 가 작을수록 멀음 → 전진
        size_err = TARGET_BBOX_AREA_PX - bbox_size_px
        linear_x = KP_DIST * size_err
        if lidar_min_m < LIDAR_SLOW_M:
            linear_x *= 0.5
        linear_x = _clamp(linear_x, -LINEAR_X_MAX, LINEAR_X_MAX)

        # 회전 제어 — bbox 중심이 화면 중심에서 벗어난 만큼 보정
        offset = self.image_center - bbox_center_x
        if abs(offset) < ANGLE_DEADZONE_PX:
            angular_z = 0.0
        else:
            angular_z = KP_ANGLE * offset
            angular_z = _clamp(angular_z, -ANGULAR_Z_MAX, ANGULAR_Z_MAX)

        return TwistCommand(linear_x, angular_z)
