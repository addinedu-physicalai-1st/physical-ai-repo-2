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

from gogoping_perception.config import (
    REID_MAX_DISTANCE_JUMP_MM,
    REID_SIM_THRESHOLD,
    REID_SIM_UNLOCK_THRESHOLD,
)
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
        # [debug] 매 update() 의 ALL candidate sim — threshold 분포 측정용.
        # [(track_id, sim), ...] 형태. update() 마다 갱신, perception_node 가 로그.
        self._all_sims: list[tuple[int, float]] = []
        # drift 재매칭 시 거리 연속성 검사용 — lock 유지/갱신 시마다 업데이트.
        # 0 = 아직 valid distance 본 적 없음 (필터 비활성).
        self._last_target_distance_mm: int = 0
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

    @property
    def all_sims(self) -> list[tuple[int, float]]:
        """[debug] 마지막 update() 에서 측정한 모든 candidate (track_id, sim)."""
        return self._all_sims

    def update(self, tracks: list[Track]) -> Track | None:
        """현재 target 의 best 후보 Track 을 반환 (없으면 None)."""
        if self._target_emb is None or not tracks:
            self._last_sim = None
            self._all_sims = []
            return None

        # 모든 candidate 의 sim 한 번에 계산 — branch 따라 일부만 보는 문제 회피 +
        # threshold 결정용 분포 측정 (perception_node 가 _all_sims 로 로그).
        all_sims_with_t: list[tuple[Track, float]] = [
            (t, float(self._reid.compute_similarity(t.embedding, self._target_emb)))
            for t in tracks
        ]
        self._all_sims = [(t.track_id, s) for t, s in all_sims_with_t]

        # 1. track_id 유지 — ByteTrack 신뢰. 단 asymmetric hysteresis:
        #    sim 이 UNLOCK 임계 아래면 잘못 lock 된 것으로 간주 → 해제 후 drift 분기.
        if self._target_track_id is not None:
            for t, s in all_sims_with_t:
                if t.track_id == self._target_track_id:
                    if s < REID_SIM_UNLOCK_THRESHOLD:
                        # lock 해제 — drift 분기에서 LOCK 임계로 재매칭.
                        self._target_track_id = None
                        break
                    # 유지 — distance 갱신 (drift 시 거리 연속성 기준)
                    if t.distance_mm > 0:
                        self._last_target_distance_mm = t.distance_mm
                    self._last_sim = s
                    return t

        # 2. drift — sim + 거리 연속성 둘 다 만족하는 candidate 만.
        #    last_target_distance_mm 가 알려져 있으면 ±MAX_DISTANCE_JUMP 안만 후보.
        eligible: list[tuple[Track, float]] = []
        for t, s in all_sims_with_t:
            if (
                self._last_target_distance_mm > 0
                and t.distance_mm > 0
                and abs(t.distance_mm - self._last_target_distance_mm) > REID_MAX_DISTANCE_JUMP_MM
            ):
                continue  # 거리 점프 — 다른 사람일 가능성, drift 후보에서 제외
            eligible.append((t, s))

        best: Track | None = None
        best_sim = -1.0
        for t, s in eligible:
            if s > best_sim:
                best_sim = s
                best = t

        if best is not None and best_sim >= REID_SIM_THRESHOLD:
            self._target_track_id = best.track_id
            if best.distance_mm > 0:
                self._last_target_distance_mm = best.distance_mm
            self._last_sim = best_sim
            return best

        self._last_sim = best_sim if best is not None else None
        return None
