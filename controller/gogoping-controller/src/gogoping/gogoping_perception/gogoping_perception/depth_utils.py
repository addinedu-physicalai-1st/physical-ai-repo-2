"""bbox depth median — 얼굴영역 patch 거리(mm). proximity/follow/debug 공유."""
from __future__ import annotations

import numpy as np

from gogoping_perception import config


def bbox_depth_median(depth, bbox, patch=5) -> int:
    x1, y1, x2, y2 = bbox
    cx = int((x1 + x2) / 2)
    cy = int(y1 + (y2 - y1) / 3)   # 상단 1/3 (얼굴) — IR 반사 일정
    r = patch // 2
    p = depth[max(0, cy - r): cy + r + 1, max(0, cx - r): cx + r + 1]
    v = p[(p >= config.DEPTH_MIN_MM) & (p <= config.DEPTH_MAX_MM)]
    return int(np.median(v)) if v.size else 0
