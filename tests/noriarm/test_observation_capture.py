"""카메라/joint state observation 채우기 헬퍼 단위 테스트."""
from __future__ import annotations

import numpy as np

from noriarm_framework.observation_capture import LatestFrameBuffer


def test_latest_frame_buffer_starts_empty() -> None:
    buf = LatestFrameBuffer(keys=("top", "gripper"))
    assert buf.snapshot() == {}


def test_latest_frame_buffer_overwrites_per_key() -> None:
    buf = LatestFrameBuffer(keys=("top",))
    old = np.zeros((10, 10, 3), dtype=np.uint8)
    new = np.ones((10, 10, 3), dtype=np.uint8)
    buf.put("top", old)
    buf.put("top", new)
    snap = buf.snapshot()
    assert np.array_equal(snap["top"], new)


def test_latest_frame_buffer_ignores_unknown_keys() -> None:
    buf = LatestFrameBuffer(keys=("top",))
    buf.put("unknown", np.zeros((1, 1, 3), dtype=np.uint8))
    assert buf.snapshot() == {}
