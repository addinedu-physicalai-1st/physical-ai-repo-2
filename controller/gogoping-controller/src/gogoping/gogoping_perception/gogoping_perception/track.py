"""ByteTrack 결과 단위 — track_id 별 bbox + embedding."""
from dataclasses import dataclass

import numpy as np


@dataclass
class Track:
    track_id: int
    bbox: tuple[int, int, int, int]  # x1, y1, x2, y2
    embedding: np.ndarray            # OSNet 512-d (L2-normalized)
    conf: float
    # D435 depth median at bbox 상단 1/3 (얼굴 영역) — mm.
    # 0 = invalid. drift 재매칭에서 거리 연속성 검사용.
    distance_mm: int = 0
