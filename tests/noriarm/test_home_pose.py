"""HOME_POSE 임계/holding window 헬퍼 단위 테스트."""
from __future__ import annotations

import pytest

from noriarm_framework.games.block_stacking.home_pose import (
    HOME_POSE,
    HomePoseDetector,
    is_at_home_pose,
)


def test_home_pose_values() -> None:
    """OMX-F 5 축 모두 0 rad."""
    assert HOME_POSE == [0.0, 0.0, 0.0, 0.0, 0.0]


def test_is_at_home_pose_within_threshold() -> None:
    assert is_at_home_pose([0.01, -0.02, 0.0, 0.04, -0.03])


def test_is_at_home_pose_outside_threshold() -> None:
    assert not is_at_home_pose([0.06, 0.0, 0.0, 0.0, 0.0])


def test_is_at_home_pose_wrong_length() -> None:
    with pytest.raises(ValueError):
        is_at_home_pose([0.0, 0.0])


def test_detector_no_events_when_arm_not_yet_home() -> None:
    det = HomePoseDetector(holding_s=0.5)
    assert det.update(t=0.0, joint_positions=[0.5, 0.0, 0.0, 0.0, 0.0]) == 0
    assert det.update(t=0.1, joint_positions=[0.4, 0.0, 0.0, 0.0, 0.0]) == 0
    assert det.events == 0


def test_detector_fires_once_per_visit() -> None:
    """팔이 home 으로 들어오고 0.5s 이상 머물면 1 회 카운트, 다음 visit 까지 재트리거 X."""
    det = HomePoseDetector(holding_s=0.5)
    # 진입 전.
    det.update(t=0.0, joint_positions=[0.5, 0.0, 0.0, 0.0, 0.0])
    # holding 시작 (t=1.0).
    det.update(t=1.0, joint_positions=[0.0, 0.0, 0.0, 0.0, 0.0])
    # 아직 0.4s 만 머물러서 미발화.
    assert det.update(t=1.4, joint_positions=[0.0, 0.0, 0.0, 0.0, 0.0]) == 0
    # 0.5s 도달 — 발화.
    assert det.update(t=1.5, joint_positions=[0.0, 0.0, 0.0, 0.0, 0.0]) == 1
    # 같은 visit 내 중복 발화 없음.
    assert det.update(t=1.6, joint_positions=[0.0, 0.0, 0.0, 0.0, 0.0]) == 1
    # 팔이 벗어났다가.
    det.update(t=2.0, joint_positions=[0.5, 0.0, 0.0, 0.0, 0.0])
    # 다시 들어와서 holding.
    det.update(t=3.0, joint_positions=[0.0, 0.0, 0.0, 0.0, 0.0])
    assert det.update(t=3.5, joint_positions=[0.0, 0.0, 0.0, 0.0, 0.0]) == 2
