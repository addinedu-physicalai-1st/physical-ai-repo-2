"""근접 안전정지 판정(proximity.decide_block) 순수 로직 테스트."""
import sys
from pathlib import Path

import numpy as np

_PKG = Path(__file__).resolve().parents[1]  # .../src/eduarm
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from eduarm.proximity import decide_block  # noqa: E402


def _frame(fill_mm: int, shape=(48, 64)) -> np.ndarray:
    return np.full(shape, fill_mm, dtype=np.uint16)


def test_all_far_not_blocked():
    assert decide_block(_frame(2000), prev_blocked=False) is False


def test_near_region_blocks():
    d = _frame(2000)
    d[:10, :10] = 500  # 100 px @ 0.5m (>= min_pixels 50)
    assert decide_block(d, prev_blocked=False) is True


def test_few_near_pixels_not_blocked():
    d = _frame(2000)
    d[0, :10] = 500  # 10 px < min_pixels(50)
    assert decide_block(d, prev_blocked=False) is False


def test_zero_invalid_ignored():
    # depth 0 = 측정 실패 → 가까운 것으로 오인하면 안 됨.
    assert decide_block(_frame(0), prev_blocked=False) is False


def test_hysteresis_between_thresholds():
    d = _frame(2000)
    d[:10, :10] = 620  # 0.62m — near(600)~clear(650) 사이
    # 해제 상태에선 620 > 600 이라 block 안 됨.
    assert decide_block(d, prev_blocked=False) is False
    # 이미 block 이면 620 < clear(650) 이라 계속 block (깜빡임 방지).
    assert decide_block(d, prev_blocked=True) is True


def test_hysteresis_clears_when_far():
    d = _frame(2000)
    d[:10, :10] = 700  # 0.7m > clear(650)
    assert decide_block(d, prev_blocked=True) is False
