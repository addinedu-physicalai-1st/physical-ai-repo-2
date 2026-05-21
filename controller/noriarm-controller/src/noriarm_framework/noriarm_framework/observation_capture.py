"""Game runner observation 채우기 — 최근 카메라 프레임 + 최근 관절 state 보관소.

비동기로 들어오는 카메라 프레임 (cv2.VideoCapture 또는 ROS image 토픽) 과 관절
state (`/joint_states` 구독) 의 최신값만 lock 으로 보관. _sense() 시점에 snapshot 을
꺼내 Observation 으로 묶는다.
"""
from __future__ import annotations

import threading
from typing import Iterable

import numpy as np


class LatestFrameBuffer:
    """카메라 키 → 최신 BGR ndarray 보관소. 들어온 적 없는 키는 snapshot 에서 빠진다."""

    def __init__(self, *, keys: Iterable[str]) -> None:
        self._allowed = set(keys)
        self._lock = threading.Lock()
        self._frames: dict[str, np.ndarray] = {}

    def put(self, key: str, frame: np.ndarray) -> None:
        if key not in self._allowed:
            return
        with self._lock:
            self._frames[key] = frame

    def snapshot(self) -> dict[str, np.ndarray]:
        with self._lock:
            return dict(self._frames)


class LatestJointState:
    """관절 이름 리스트 → 최신 position ndarray 보관소 — `/joint_states` 콜백이 갱신."""

    def __init__(self, *, expected_names: Iterable[str]) -> None:
        self._expected = list(expected_names)
        self._lock = threading.Lock()
        self._positions: np.ndarray | None = None

    def update(self, names: list[str], positions: list[float]) -> None:
        idx_map = {n: i for i, n in enumerate(names)}
        try:
            ordered = [positions[idx_map[n]] for n in self._expected]
        except (KeyError, IndexError):
            return
        with self._lock:
            self._positions = np.asarray(ordered, dtype=np.float64)

    def snapshot(self) -> np.ndarray | None:
        with self._lock:
            return None if self._positions is None else self._positions.copy()
