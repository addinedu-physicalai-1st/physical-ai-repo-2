"""POSIX 공유메모리 layout — gogoping_camera (writer) 와 gogoping_perception (reader) 가
import 해서 공유하는 상수 + helper.

Color: 640×480×3 uint8 (BGR), Depth: 640×480 uint16 (mm).
세 번째 shm 은 metadata (seq counter atomic uint64 + timestamp) — writer 가 increment,
reader 는 마지막 seq 가 변하면 새 frame.

수명: writer 가 SharedMemory(create=True) → reader 가 SharedMemory(name=...) attach.
writer 종료 시 unlink. reader 는 detach 만.
"""
from __future__ import annotations

import numpy as np

SHM_COLOR_NAME = "gogoping_color_640"
SHM_DEPTH_NAME = "gogoping_depth_640"
SHM_META_NAME  = "gogoping_meta"

COLOR_H, COLOR_W = 480, 640
DEPTH_H, DEPTH_W = 480, 640

COLOR_BYTES = COLOR_H * COLOR_W * 3   # 921_600
DEPTH_BYTES = DEPTH_H * DEPTH_W * 2   # 614_400
META_BYTES  = 32                      # seq(uint64) + cap_ns(uint64) + reserved

# meta layout (little-endian):
#   offset 0:  uint64 seq         (writer increment 후 마지막에 store)
#   offset 8:  uint64 capture_ns  (time.time_ns())
#   offset 16: 16 bytes reserved

def view_color(buf: memoryview) -> np.ndarray:
    return np.ndarray((COLOR_H, COLOR_W, 3), dtype=np.uint8, buffer=buf)

def view_depth(buf: memoryview) -> np.ndarray:
    return np.ndarray((DEPTH_H, DEPTH_W), dtype=np.uint16, buffer=buf)

def view_meta(buf: memoryview) -> np.ndarray:
    return np.ndarray((4,), dtype=np.uint64, buffer=buf)   # seq, cap_ns, r0, r1
