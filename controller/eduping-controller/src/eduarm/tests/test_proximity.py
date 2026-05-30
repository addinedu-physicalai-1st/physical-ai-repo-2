"""근접 안전정지 판정(proximity) 순수 로직 테스트 — 사람 검출 게이트."""
import sys
from pathlib import Path

import numpy as np

_PKG = Path(__file__).resolve().parents[1]  # .../src/eduarm
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from eduarm.proximity import (  # noqa: E402
    decide_block,
    person_distance_mm,
    step_debounce,
)


def _depth(shape=(240, 424), fill=2000):
    return np.full(shape, fill, dtype=np.uint16)


def test_person_distance_median_of_bbox():
    d = _depth(fill=2000)
    d[50:150, 100:200] = 500  # bbox 영역을 0.5m 로
    dist = person_distance_mm(d, (100, 50, 200, 150))
    assert abs(dist - 500) < 1


def test_person_distance_ignores_zero_invalid():
    d = _depth(fill=0)  # 전부 invalid
    assert person_distance_mm(d, (100, 50, 200, 150)) is None


def test_person_distance_uses_near_percentile_over_background():
    # bbox 안 절반은 사람(가까움 500), 절반은 배경(멀음 3000) → 20%는 사람쪽.
    d = _depth(fill=3000)
    d[50:150, 100:150] = 500  # bbox 좌측 절반 사람
    dist = person_distance_mm(d, (100, 50, 200, 150), percentile=20)
    assert dist < 700  # 사람 최근접부로 잡혀야 함


def test_person_distance_median_rejects_minority_near_arm():
    # reach 시나리오: bbox 의 30%가 가까운 팔(400mm), 70%가 멀리 있는 사람(1500mm).
    # 20퍼센타일은 팔에 오염되지만(거짓 근접), median(50)은 사람 몸통 거리를 잡아야 한다.
    d = _depth(shape=(100, 100), fill=1500)
    d[:, :30] = 400  # 좌측 30% = 화면에 겹친 로봇 팔
    bbox = (0, 0, 100, 100)
    assert person_distance_mm(d, bbox, percentile=20) < 600   # 오염됨
    assert person_distance_mm(d, bbox, percentile=50) >= 1000  # median 은 사람


def test_person_distance_self_floor_excludes_arm():
    # 팔(250mm)이 bbox 의 60% 를 덮어 median 도 오염되는 경우 — self_floor 로 팔 제외.
    d = _depth(shape=(100, 100), fill=1200)
    d[:, :60] = 250  # 60% = 로봇 팔(아주 가까움)
    bbox = (0, 0, 100, 100)
    assert person_distance_mm(d, bbox, percentile=50) < 600          # 팔이 과반 → median 오염
    assert person_distance_mm(d, bbox, percentile=50, self_floor_mm=400) >= 1000  # 팔 제외 → 사람


def test_person_distance_self_floor_none_when_person_fully_occluded():
    # bbox 가 전부 팔(300mm) — self_floor 후 남는 픽셀 없음 → 측정 불가(None), 도달 아님.
    d = _depth(shape=(100, 100), fill=300)
    assert person_distance_mm(d, (0, 0, 100, 100), self_floor_mm=400) is None


def test_no_persons_not_blocked():
    assert decide_block([], prev_blocked=False) is False


def test_person_near_blocks():
    assert decide_block([500.0], prev_blocked=False) is True


def test_person_far_not_blocked():
    assert decide_block([800.0], prev_blocked=False) is False


def test_none_distance_ignored():
    # 거리 측정 불가(None)인 사람은 block 유발 안 함.
    assert decide_block([None], prev_blocked=False) is False


def test_hysteresis_between_thresholds():
    # 620mm: 해제 상태에선 block 안 됨(>600), 이미 block 이면 유지(<650).
    assert decide_block([620.0], prev_blocked=False) is False
    assert decide_block([620.0], prev_blocked=True) is True


def test_hysteresis_clears_when_far():
    assert decide_block([700.0], prev_blocked=True) is False


def test_multiple_persons_any_near_blocks():
    assert decide_block([900.0, 550.0], prev_blocked=False) is True


# ---- step_debounce ----------------------------------------------------------

def test_debounce_no_change_when_raw_matches():
    assert step_debounce(False, False, 0, on_frames=2, off_frames=6) == (False, 0)
    assert step_debounce(True, True, 3, on_frames=2, off_frames=6) == (True, 0)


def test_debounce_block_needs_on_frames():
    # 1프레임 근접: 아직 block 아님(streak=1).
    out, streak = step_debounce(False, True, 0, on_frames=2, off_frames=6)
    assert out is False and streak == 1
    # 연속 2프레임: block 진입.
    out, streak = step_debounce(False, True, 1, on_frames=2, off_frames=6)
    assert out is True and streak == 0


def test_debounce_single_frame_glitch_ignored():
    # block 중 1프레임만 clear → 유지(streak 누적만).
    out, streak = step_debounce(True, False, 0, on_frames=2, off_frames=6)
    assert out is True and streak == 1


def test_debounce_clear_needs_off_frames_sticky():
    # off_frames=6 도달해야 해제. 5프레임까진 유지.
    out, streak = step_debounce(True, False, 5, on_frames=2, off_frames=6)
    assert out is False and streak == 0


def test_debounce_streak_resets_on_disagreement_break():
    # clear 누적 중 다시 근접 1프레임 들어오면 streak 리셋.
    out, streak = step_debounce(True, True, 4, on_frames=2, off_frames=6)
    assert out is True and streak == 0
