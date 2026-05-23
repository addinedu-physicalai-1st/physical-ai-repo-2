"""target_track_id 유지 + ByteTrack drift 시 ReID 재매칭.

전략:
1. set_target(embedding) 으로 외부에서 InsightFace embedding 등록.
   (실제 ReID 와 다른 모달리티지만 single-template 비교 용도. 충분한 성능
   안 나오면 갤러리 정책 재검토.)
2. update(tracks): 현재 target_track_id 가 tracks 안에 있으면 그대로 반환.
   없으면 best ReID sim track 찾아 sim ≥ threshold 면 target_track_id 갱신.
"""
from __future__ import annotations

import numpy as np

from gogoping_perception.config import REID_SIM_THRESHOLD
from gogoping_perception.reid_engine import ReIDEngine
from gogoping_perception.track import Track


class TargetTracker:
    def __init__(self, reid_engine: ReIDEngine) -> None:
        self._reid = reid_engine
        self._target_emb: np.ndarray | None = None
        self._target_track_id: int | None = None
        self._last_sim: float | None = None

    def set_target(self, embedding: list[float]) -> None:
        self._target_emb = np.asarray(embedding, dtype=np.float32)
        self._target_track_id = None
        self._last_sim = None

    def clear_target(self) -> None:
        self._target_emb = None
        self._target_track_id = None
        self._last_sim = None

    def has_target(self) -> bool:
        return self._target_emb is not None

    @property
    def last_sim(self) -> float | None:
        return self._last_sim

    def update(self, tracks: list[Track]) -> Track | None:
        """현재 target 의 best 후보 Track 을 반환 (없으면 None)."""
        if self._target_emb is None or not tracks:
            self._last_sim = None
            return None

        # 1. track_id 유지 — ByteTrack 신뢰
        if self._target_track_id is not None:
            for t in tracks:
                if t.track_id == self._target_track_id:
                    self._last_sim = float(
                        self._reid.compute_similarity(t.embedding, self._target_emb)
                    )
                    return t

        # 2. drift — ReID 로 best 찾기
        best: Track | None = None
        best_sim = -1.0
        for t in tracks:
            sim = float(self._reid.compute_similarity(t.embedding, self._target_emb))
            if sim > best_sim:
                best_sim = sim
                best = t

        if best is not None and best_sim >= REID_SIM_THRESHOLD:
            self._target_track_id = best.track_id
            self._last_sim = best_sim
            return best

        self._last_sim = best_sim if best is not None else None
        return None
