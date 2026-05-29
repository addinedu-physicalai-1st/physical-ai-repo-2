"""근접 안전정지 — D435 depth 에서 "사람이 너무 가까운가" 판정 (순수 로직).

ROS/카메라 없이 단위 테스트 가능하도록 분리. 노드(proximity_safety_node)가 depth
프레임을 넘겨 호출한다.

거리 히스테리시스: 정지는 near_mm 이내, 해제는 clear_mm 밖 — 경계에서 stop↔resume 가
깜빡이는 것을 막는다. 단일 노이즈 픽셀로 오작동하지 않도록 임계 거리 이내 픽셀 수가
min_pixels 이상일 때만 block.
"""
from __future__ import annotations

import numpy as np

NEAR_MM_DEFAULT = 600    # 0.60 m — 이내면 정지
CLEAR_MM_DEFAULT = 650   # 0.65 m — 밖이면 해제 (히스테리시스)
MIN_PIXELS_DEFAULT = 50  # 임계 거리 이내 픽셀이 이만큼 이상이어야 사람으로 인정


def decide_block(
    depth_mm: np.ndarray,
    prev_blocked: bool,
    *,
    near_mm: int = NEAR_MM_DEFAULT,
    clear_mm: int = CLEAR_MM_DEFAULT,
    min_pixels: int = MIN_PIXELS_DEFAULT,
) -> bool:
    """depth(uint16, mm) 한 프레임 → block 여부.

    depth 0 은 invalid(측정 실패)라 제외. 현재 block 상태에 따라 임계 거리를 바꿔
    (정지 near_mm / 해제 clear_mm) 히스테리시스를 준다.
    """
    threshold = clear_mm if prev_blocked else near_mm
    near = (depth_mm > 0) & (depth_mm < threshold)
    count = int(np.count_nonzero(near))
    return count >= min_pixels
