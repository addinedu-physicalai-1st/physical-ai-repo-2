"""OMX-F 홈 포즈 정의 + 임계/holding 기반 복귀 감지.

블럭쌓기 종료 조건은 "로봇이 홈으로 2 회 돌아왔을 때" — 매 step `/joint_states` 를
구독해서 모든 관절이 HOME_POSE 와 임계 이내로 일치한 frame 이 holding_s 동안 유지
되면 1 회 이벤트로 카운트한다. 같은 visit 내 중복 트리거를 막기 위해 한 번 발화한
이후 임계를 벗어났다가 다시 들어오기 전까지는 추가 카운트하지 않는다.
"""
from __future__ import annotations

# OMX-F 5 축 (joint1..joint5) — 사용자 OMX bringup 후 default 자세 (2026-05-26 echo).
HOME_POSE: list[float] = [
    0.09357282806081724,
    -1.8714565612206893,
    1.6858448858861124,
    1.6551652701283999,
    0.013805827090763945,
]

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

    def __init__(self, *, holding_s: float = 0.5, count_initial: bool = False) -> None:
        self._holding_s = holding_s
        self._inside_since: float | None = None
        # ACT 게임 시작 시점에 OMX 가 이미 HOME 자세 (RPS 끝나 HOME 복귀 직후) 인 상황을
        # 첫 카운트로 치지 않기 위해, default 는 '이미 fired 한 visit' 으로 초기화한다.
        # 임계 밖으로 한 번 나갔다가 다시 들어와야 진짜 첫 발화.
        self._fired_this_visit = not count_initial
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
