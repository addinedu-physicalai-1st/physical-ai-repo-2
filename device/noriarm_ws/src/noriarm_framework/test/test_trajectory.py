"""trajectory 로더 + 컬럼 슬라이싱 단위 테스트.

ROS2 메시지 빌더 (`build_joint_trajectory`) 는 trajectory_msgs 의존성 때문에 여기서 직접
호출하지 않는다 — 검증은 통합 테스트에서.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from noriarm_framework.trajectory import (
    Trajectory,
    deg_to_rad,
    load_trajectory,
)


def _write_trajectory(path: Path, frames: list[list[float]], hz: float = 30.0) -> Path:
    payload = {"hz": hz, "num_frames": len(frames), "trajectory": frames}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_basic(tmp_path: Path) -> None:
    p = _write_trajectory(tmp_path / "t.json", [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], hz=10.0)
    t = load_trajectory(p)
    assert t.hz == 10.0
    assert t.num_frames == 2
    assert t.num_columns == 3
    assert t.duration_s == pytest.approx(0.2)


def test_slice_columns_drops_extras(tmp_path: Path) -> None:
    p = _write_trajectory(tmp_path / "t.json", [[1, 2, 3, 4, 5, 6], [7, 8, 9, 10, 11, 12]])
    t = load_trajectory(p)
    sliced = t.slice_columns(5)
    assert sliced.num_columns == 5
    assert sliced.frames_deg[0] == [1.0, 2.0, 3.0, 4.0, 5.0]


def test_slice_columns_too_many_raises(tmp_path: Path) -> None:
    p = _write_trajectory(tmp_path / "t.json", [[1, 2, 3]])
    t = load_trajectory(p)
    with pytest.raises(ValueError, match="컬럼밖에"):
        t.slice_columns(4)


def test_slice_columns_same_returns_self(tmp_path: Path) -> None:
    p = _write_trajectory(tmp_path / "t.json", [[1, 2, 3]])
    t = load_trajectory(p)
    assert t.slice_columns(3) is t


def test_load_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_trajectory(tmp_path / "nope.json")


def test_load_empty_trajectory(tmp_path: Path) -> None:
    p = tmp_path / "t.json"
    p.write_text(json.dumps({"hz": 30, "trajectory": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="비어있음"):
        load_trajectory(p)


def test_deg_to_rad_round_trip() -> None:
    rads = deg_to_rad([0, 90, 180, -45])
    assert rads[0] == 0.0
    assert rads[1] == pytest.approx(math.pi / 2)
    assert rads[2] == pytest.approx(math.pi)
    assert rads[3] == pytest.approx(-math.pi / 4)


# 실제 ox_quiz episode JSON 로딩 — 회귀 가드.
REPO_OX = (
    Path(__file__).resolve().parents[1]
    / "noriarm_framework"
    / "games"
    / "ox_quiz"
    / "episode_0_trajectory.json"
)


@pytest.mark.skipif(not REPO_OX.is_file(), reason="ox_quiz episode JSON 미배치")
def test_ox_episode_loads_and_slices_to_5() -> None:
    t = load_trajectory(REPO_OX)
    assert t.num_columns == 6  # lerobot 녹화는 6 컬럼 (5 arm + 1 gripper)
    sliced = t.slice_columns(5)
    assert sliced.num_columns == 5
    assert sliced.num_frames == t.num_frames
