"""OMX-F 홈 포즈 정의 + 임계/holding 기반 복귀 감지.

블럭쌓기 종료 조건은 "로봇이 홈으로 2 회 돌아왔을 때" — 매 step `/joint_states` 를
구독해서 모든 관절이 HOME_POSE 와 임계 이내로 일치한 frame 이 holding_s 동안 유지
되면 1 회 이벤트로 카운트한다. 같은 visit 내 중복 트리거를 막기 위해 한 번 발화한
이후 임계를 벗어났다가 다시 들어오기 전까지는 추가 카운트하지 않는다.
"""
from __future__ import annotations

# OMX-F 5 축 (joint1..joint5) — 모두 0 rad 가 우리 학습의 home pose.
HOME_POSE: list[float] = [0.0, 0.0, 0.0, 0.0, 0.0]

# 관절별 절대 거리 임계 (rad). 학습 데이터의 home frame 표준편차보다 조금 큰 값.
HOME_POSE_TOLERANCE_RAD: float = 0.05


def is_at_home_pose(joint_positions: list[float]) -> bool:
    """현재 관절 값이 HOME_POSE 와 임계 이내인지."""
    if len(joint_positions) != len(HOME_POSE):
        raise ValueError(
            f"joint_positions 길이 {len(joint_positions)} != HOME_POSE 길이 {len(HOME_POSE)}"
        )
    return all(abs(j - h) <= HOME_POSE_TOLERANCE_RAD for j, h in zip(joint_positions, HOME_POSE))


class HomePoseDetector:
    """홈 포즈 진입/이탈 + holding_s 기반 edge detector."""

    def __init__(self, *, holding_s: float = 0.5) -> None:
        self._holding_s = holding_s
        self._inside_since: float | None = None
        self._fired_this_visit = False
        self.events = 0

    def update(self, *, t: float, joint_positions: list[float]) -> int:
        """현 frame 의 (시각 t, 관절값) 으로 detector 상태 갱신, 누적 이벤트 수를 돌려준다."""
        at_home = is_at_home_pose(joint_positions)
        if not at_home:
            self._inside_since = None
            self._fired_this_visit = False
            return self.events
        if self._inside_since is None:
            self._inside_since = t
            return self.events
        # 임계 안 — holding 시간 도달했고 아직 발화 안 했으면 카운트.
        if not self._fired_this_visit and (t - self._inside_since) >= self._holding_s:
            self.events += 1
            self._fired_this_visit = True
        return self.events
