"""target_track_id 유지 + ByteTrack drift 시 ReID 재매칭 + enrollment FSM.

전략 (개정):
1. set_face_template(emb): control-service 가 보낸 face emb 를 fallback 으로 저장.
2. start_enrollment(target_n): ENROLLING 상태로 진입. N=15 frame 동안 perception_node
   가 accumulate_body(emb) 로 OSNet body emb 누적.
3. finalize_enrollment(): 누적 emb 평균 → L2 norm → body_template. ACTIVE 전이.
4. update(tracks): ACTIVE 상태에서 일반 ReID 매칭 (body_template 사용).
   ENROLLING 상태에선 face_template 으로 매칭 시도 (안정성 floor).

상태:
  IDLE → start_enrollment → ENROLLING → finalize_enrollment → ACTIVE
        ←─────────────── clear_target ────────────────────┘
"""
from __future__ import annotations

import numpy as np

from gogoping_perception.config import REID_SIM_THRESHOLD
from gogoping_perception.reid_engine import ReIDEngine
from gogoping_perception.track import Track


class TargetTracker:
    def __init__(self, reid_engine: ReIDEngine) -> None:
        self._reid = reid_engine
        # face emb (control-service 가 보냄) — fallback / enrollment 중 매칭 floor.
        self._face_template: np.ndarray | None = None
        # body emb 평균 (enrollment finalize 후) — primary 매칭 vector.
        self._body_template: np.ndarray | None = None
        # 매칭 시 사용할 active template — _body_template 또는 _face_template.
        self._target_emb: np.ndarray | None = None
        self._target_track_id: int | None = None
        self._last_sim: float | None = None
        # enrollment FSM.
        self._state: str = "IDLE"  # IDLE | ENROLLING | ACTIVE
        self._enroll_target_n: int = 0
        self._enroll_accumulated: list[np.ndarray] = []

    # ── backward-compat (legacy single-template path) ─────────────────────────
    def set_target(self, embedding: list[float]) -> None:
        """[deprecated path — keep for rollback] face emb 만 받아 즉시 ACTIVE.

        새 흐름은 set_face_template + start_enrollment → finalize_enrollment.
        """
        emb = np.asarray(embedding, dtype=np.float32)
        self._face_template = emb
        self._body_template = None
        self._target_emb = emb
        self._target_track_id = None
        self._last_sim = None
        self._state = "ACTIVE"
        self._enroll_accumulated = []
        self._enroll_target_n = 0

    # ── new enrollment API ────────────────────────────────────────────────────
    def set_face_template(self, embedding) -> None:
        """face emb (InsightFace 512-d) 저장. fallback / 안정성 floor.

        IDLE 상태 유지 — start_enrollment 또는 set_target 으로 ACTIVE 전이.
        """
        self._face_template = np.asarray(embedding, dtype=np.float32)

    def start_enrollment(self, target_n: int) -> None:
        """ENROLLING 상태 진입. perception_node 가 매 frame accumulate_body 호출 예정."""
        self._enroll_target_n = int(target_n)
        self._enroll_accumulated = []
        self._state = "ENROLLING"
        self._target_track_id = None
        # 매칭 시 face emb 를 floor 로 사용 — drift 시 face emb 비교라도.
        self._target_emb = self._face_template
        self._last_sim = None

    def accumulate_body(self, embedding) -> None:
        """ENROLLING 중 body emb 누적. target_n 도달 시 자동 finalize."""
        if self._state != "ENROLLING":
            return
        emb = np.asarray(embedding, dtype=np.float32)
        if emb.size == 0:
            return
        # L2-normalize 보정 (이미 norm 된 emb 가 일반적이지만 안전)
        n = np.linalg.norm(emb)
        if n > 1e-8:
            emb = emb / n
        self._enroll_accumulated.append(emb)
        if len(self._enroll_accumulated) >= self._enroll_target_n:
            self.finalize_enrollment(force=False)

    def finalize_enrollment(self, force: bool = False) -> None:
        """누적 emb 평균 → body_template. ACTIVE 전이.

        force=True 면 N 미달이라도 강제 (timeout 케이스).
        누적 0개면 face_template 으로 fallback.
        """
        if not self._enroll_accumulated:
            # fallback to face emb
            self._body_template = self._face_template
        else:
            avg = np.mean(np.stack(self._enroll_accumulated), axis=0)
            n = np.linalg.norm(avg)
            if n > 1e-8:
                avg = avg / n
            self._body_template = avg.astype(np.float32)
        self._target_emb = self._body_template
        self._state = "ACTIVE"

    @property
    def state(self) -> str:
        return self._state

    # ── existing API ──────────────────────────────────────────────────────────
    def clear_target(self) -> None:
        self._face_template = None
        self._body_template = None
        self._target_emb = None
        self._target_track_id = None
        self._last_sim = None
        self._state = "IDLE"
        self._enroll_accumulated = []
        self._enroll_target_n = 0

    def has_target(self) -> bool:
        """ENROLLING 또는 ACTIVE 면 target 있음."""
        return self._state in ("ENROLLING", "ACTIVE")

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
