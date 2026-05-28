"""D435 capture loop — pipeline → rs.align(color) → 640 다운스케일 → shm write.

별 thread (capture loop) 가 blocking wait_for_frames() 호출. asyncio 와의 다리는
threading.Event + 최신 frame seq atomic store. webrtc_track 의 recv() 는 seq 변경을
poll 해서 av.VideoFrame 으로 변환.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from multiprocessing.shared_memory import SharedMemory
from typing import Optional

import cv2
import numpy as np
import pyrealsense2 as rs

from . import config, shm_layout

_log = logging.getLogger("gogoping_camera.d435_capture")


@dataclass
class CapturedFrame:
    """zero-copy view 가 아니라 caller 가 보관 가능한 cv2.resize 결과.

    color: 640×480×3 BGR uint8
    depth: 640×480     uint16 (mm)
    seq:   monotonic frame counter
    cap_ns: time.time_ns() at capture
    """
    color_small: np.ndarray
    depth_small: np.ndarray
    color_full:  np.ndarray   # 1920×1080×3 BGR (WebRTC encode 용 — 원본 보존)
    seq: int
    cap_ns: int


class D435Capture:
    """D435 pipeline 관리 + shm 3개 (color/depth/meta) write.

    start() 가 daemon thread 시작. _loop 가 wait_for_frames blocking,
    align, downscale, shm write 반복.
    latest_frame() 는 thread-safe 한 마지막 CapturedFrame 반환 (webrtc_track 가 호출).
    """

    def __init__(self) -> None:
        self._pipeline = rs.pipeline()
        self._cfg = rs.config()
        self._cfg.enable_stream(
            rs.stream.color,
            config.CAMERA_COLOR_W, config.CAMERA_COLOR_H,
            rs.format.bgr8, config.CAMERA_COLOR_FPS,
        )
        self._cfg.enable_stream(
            rs.stream.depth,
            config.CAMERA_DEPTH_W, config.CAMERA_DEPTH_H,
            rs.format.z16, config.CAMERA_DEPTH_FPS,
        )
        self._align = rs.align(rs.stream.color)

        # shm — writer 가 create
        self._shm_color = SharedMemory(
            name=shm_layout.SHM_COLOR_NAME, create=True, size=shm_layout.COLOR_BYTES,
        )
        self._shm_depth = SharedMemory(
            name=shm_layout.SHM_DEPTH_NAME, create=True, size=shm_layout.DEPTH_BYTES,
        )
        self._shm_meta = SharedMemory(
            name=shm_layout.SHM_META_NAME, create=True, size=shm_layout.META_BYTES,
        )
        self._color_view = shm_layout.view_color(self._shm_color.buf)
        self._depth_view = shm_layout.view_depth(self._shm_depth.buf)
        self._meta_view = shm_layout.view_meta(self._shm_meta.buf)
        self._meta_view[:] = 0

        self._latest: Optional[CapturedFrame] = None
        self._latest_lock = threading.Lock()
        self._new_frame = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="d435-capture", daemon=True)
        self._seq = 0

    def start(self) -> None:
        self._pipeline.start(self._cfg)
        _log.info("D435 pipeline started: color %dx%d@%d, depth %dx%d@%d",
                  config.CAMERA_COLOR_W, config.CAMERA_COLOR_H, config.CAMERA_COLOR_FPS,
                  config.CAMERA_DEPTH_W, config.CAMERA_DEPTH_H, config.CAMERA_DEPTH_FPS)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)
        try:
            self._pipeline.stop()
        except Exception:
            pass
        for shm in (self._shm_color, self._shm_depth, self._shm_meta):
            try:
                shm.close()
                shm.unlink()
            except Exception:
                pass

    def latest_frame(self, timeout: float = 1.0) -> Optional[CapturedFrame]:
        """blocking — 새 frame 이 들어올 때까지 대기 후 반환.
        timeout 초 이내 새 frame 없으면 None."""
        if not self._new_frame.wait(timeout=timeout):
            return None
        self._new_frame.clear()
        with self._latest_lock:
            return self._latest

    def _loop(self) -> None:
        ds_w, ds_h = config.PERCEPTION_PRESETS[config.ACTIVE_PRESET]["downscale"]
        while not self._stop.is_set():
            try:
                frames = self._pipeline.wait_for_frames(timeout_ms=2000)
            except RuntimeError as exc:
                _log.warning("wait_for_frames timeout/error: %s", exc)
                continue

            # pyrealsense2 internal queue 에 더 새로운 frame 이 있으면 모두 drain.
            # wait_for_frames 는 oldest 부터 반환 → 그동안 쌓인 frame 으로 인해
            # perception 이 "과거" frame 처리. poll_for_frames 는 non-blocking,
            # frame 없으면 falsy 반환. 매 cycle 마다 latest frameset 으로 align/encode.
            while True:
                try:
                    newer = self._pipeline.poll_for_frames()
                except RuntimeError:
                    break
                if not newer:
                    break
                frames = newer

            aligned = self._align.process(frames)
            color_frame = aligned.get_color_frame()
            depth_frame = aligned.get_depth_frame()
            if not color_frame or not depth_frame:
                continue

            color_full = np.asanyarray(color_frame.get_data())   # 1920×1080×3 BGR
            depth_full = np.asanyarray(depth_frame.get_data())   # 1920×1080 uint16

            color_small = cv2.resize(color_full, (ds_w, ds_h), interpolation=cv2.INTER_AREA)
            depth_small = cv2.resize(depth_full, (ds_w, ds_h), interpolation=cv2.INTER_NEAREST)

            # shm write — meta seq 는 마지막에 (reader 가 seq 변화로 새 frame 감지)
            self._color_view[:] = color_small
            self._depth_view[:] = depth_small
            self._seq += 1
            self._meta_view[0] = self._seq
            self._meta_view[1] = time.time_ns()

            with self._latest_lock:
                self._latest = CapturedFrame(
                    color_small=color_small,
                    depth_small=depth_small,
                    color_full=color_full,
                    seq=self._seq,
                    cap_ns=int(self._meta_view[1]),
                )
            self._new_frame.set()
