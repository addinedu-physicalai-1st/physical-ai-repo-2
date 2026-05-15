"""trajectory JSON 로더 + JointTrajectory 메시지 빌더.

trajectory JSON 포맷 (lerobot 녹화 결과):
    {
      "hz": 30,
      "num_frames": 547,
      "trajectory": [[shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper], ...]
    }

joint 값은 도(degree) 단위 — ROS2 의 라디안으로 변환한다.

이 모듈은 ROS2 메시지 빌드까지만 책임지고 publish 는 runner 가 한다 — 단위 테스트가
rclpy 없이도 가능하도록 분리.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Trajectory:
    """녹화 trajectory — 위치 기반(positional) 컬럼 목록을 그대로 들고 다닌다.

    publish 시점에 컨트롤러가 받는 joint 수가 다르면 (예: arm_controller 가 5축, JSON 은
    6축) `slice_columns()` 로 잘라낸다.
    """

    hz: float
    frames_deg: list[list[float]]

    @property
    def num_frames(self) -> int:
        return len(self.frames_deg)

    @property
    def num_columns(self) -> int:
        return len(self.frames_deg[0]) if self.frames_deg else 0

    @property
    def duration_s(self) -> float:
        return self.num_frames / self.hz if self.hz > 0 else 0.0

    def slice_columns(self, n: int) -> "Trajectory":
        """앞쪽 n 컬럼만 남긴 trajectory 를 돌려준다."""
        if n > self.num_columns:
            raise ValueError(
                f"slice_columns({n}): trajectory 가 {self.num_columns} 컬럼밖에 없습니다"
            )
        if n == self.num_columns:
            return self
        return Trajectory(
            hz=self.hz,
            frames_deg=[frame[:n] for frame in self.frames_deg],
        )


def load_trajectory(path: str | Path) -> Trajectory:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(f"trajectory 파일이 없음: {p}")
    with p.open(encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
    if "trajectory" not in data:
        raise ValueError(f"{p}: 'trajectory' 키가 없음")
    frames = data["trajectory"]
    if not isinstance(frames, list) or not frames:
        raise ValueError(f"{p}: trajectory 가 비어있음")
    if not isinstance(frames[0], list):
        raise ValueError(f"{p}: trajectory 의 각 frame 은 리스트여야 함")
    hz = float(data.get("hz", 30))
    return Trajectory(hz=hz, frames_deg=[[float(v) for v in row] for row in frames])


def deg_to_rad(values: list[float]) -> list[float]:
    return [v * math.pi / 180.0 for v in values]


def build_joint_trajectory(
    traj: Trajectory,
    joint_names: tuple[str, ...] | list[str],
    *,
    start_offset_s: float = 0.0,
):
    """Trajectory 를 ROS2 `trajectory_msgs/JointTrajectory` 메시지로 변환한다.

    ROS2 메시지 import 는 함수 안에서 lazy 하게 — 단위 테스트는 빌더의 입력 검증만
    하고 실제 메시지 생성 부분은 ROS 환경에서 통합 테스트한다.
    """
    from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint  # type: ignore[import-not-found]

    width = len(joint_names)
    if width > traj.num_columns:
        raise ValueError(
            f"joint 이름 수 ({width}) 가 trajectory 컬럼 수 ({traj.num_columns}) 보다 큽니다"
        )
    sliced = traj.slice_columns(width)

    msg = JointTrajectory()
    msg.joint_names = list(joint_names)
    period = 1.0 / sliced.hz
    for i, frame in enumerate(sliced.frames_deg):
        point = JointTrajectoryPoint()
        point.positions = deg_to_rad(frame)
        t = start_offset_s + (i + 1) * period
        sec = int(t)
        point.time_from_start.sec = sec
        point.time_from_start.nanosec = int((t - sec) * 1e9)
        msg.points.append(point)
    return msg
