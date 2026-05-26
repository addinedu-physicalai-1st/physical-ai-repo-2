"""POSIX shm attach + latest frame read.

gogoping_camera 의 shm_layout 을 import (런타임 의존성 — 같은 controller 워크스페이스).
seq counter 가 변할 때만 새 frame 으로 처리. writer 가 죽으면 seq 가 멈춤 — timeout
처리.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from multiprocessing.shared_memory import SharedMemory
from typing import Optional

import numpy as np

from gogoping_camera import shm_layout

_log = logging.getLogger("gogoping_perception.shm_reader")


@dataclass
class FrameSnapshot:
    color: np.ndarray   # 640×480×3 BGR uint8 (zero-copy view)
    depth: np.ndarray   # 640×480     uint16 (mm) (zero-copy view)
    seq: int
    cap_ns: int


class ShmReader:
    """gogoping_color_640 / gogoping_depth_640 / gogoping_meta attach.

    poll(timeout) 가 새 seq 가 들어올 때까지 sleep 후 FrameSnapshot 반환. Timeout
    이전에 seq 가 안 변하면 None.
    """

    POLL_INTERVAL_S = 0.005   # 5ms — 200Hz 폴링, 30fps 캡처라 충분

    def __init__(self) -> None:
        self._color = SharedMemory(name=shm_layout.SHM_COLOR_NAME)
        self._depth = SharedMemory(name=shm_layout.SHM_DEPTH_NAME)
        self._meta  = SharedMemory(name=shm_layout.SHM_META_NAME)
        self._color_view = shm_layout.view_color(self._color.buf)
        self._depth_view = shm_layout.view_depth(self._depth.buf)
        self._meta_view  = shm_layout.view_meta(self._meta.buf)
        self._last_seq = 0

    def poll(self, timeout: float) -> Optional[FrameSnapshot]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            seq = int(self._meta_view[0])
            if seq != self._last_seq and seq != 0:
                self._last_seq = seq
                return FrameSnapshot(
                    color=self._color_view.copy(),    # snapshot copy — writer 가 다음 frame 으로 덮어쓰기 전에
                    depth=self._depth_view.copy(),
                    seq=seq,
                    cap_ns=int(self._meta_view[1]),
                )
            time.sleep(self.POLL_INTERVAL_S)
        return None

    def close(self) -> None:
        for shm in (self._color, self._depth, self._meta):
            try:
                shm.close()
            except Exception:
                pass
