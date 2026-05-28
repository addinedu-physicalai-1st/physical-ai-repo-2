"""한국어 mode 라벨 → Goal.target_state 변환.

robot-web 의 모드 메뉴 (``shared/robots.json`` 의 gogoping.modeTree) 가 보내는
한국어 라벨 ("추종", "이동", "수동", "자장가", "숨바꼭질", "대기", "복귀") 을
``gogoping_msgs/msg/Goal`` 의 ``{target_state, destination_key, target_id,
search_waypoints}`` 필드로 변환.

평탄화 (2026-05-25): mode + task 두 축 → target_state 하나로 단순화.
robots.json 의 한국어 라벨은 UI 표시용이라 그대로 유지. 매핑만 변경.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# Day 1 walking skeleton 데모 기본값. UI 에 명시 선택 (어느 선생님 / 어느 장소) 추가 후 제거.
DEMO_DEFAULT_TARGET_ID = "demo_teacher"
DEMO_DEFAULT_DESTINATION_KEY = "demo_destination"
DEMO_DEFAULT_CHILD_ID = "demo_child"


@dataclass
class Goal:
    """``gogoping_msgs/msg/Goal`` 의 Python dataclass 미러."""

    target_state: str
    destination_key: str = ""
    target_id: str = ""
    search_waypoints: list[str] = field(default_factory=list)
    play_area_key: str = ""

    def to_dict(self) -> dict:
        return {
            "target_state": self.target_state,
            "destination_key": self.destination_key,
            "target_id": self.target_id,
            "search_waypoints": list(self.search_waypoints),
            "play_area_key": self.play_area_key,
        }


class UnsupportedMode(ValueError):
    """robots.json 의 gogoping modes 외 라벨이 들어온 경우."""


_LABEL_TO_GOAL = {
    "대기": lambda: Goal(target_state="IDLE"),
    "수동": lambda: Goal(target_state="MANUAL"),
    "복귀": lambda: Goal(target_state="RETURNING"),
    "추종": lambda: Goal(target_state="FOLLOW", target_id=DEMO_DEFAULT_TARGET_ID),
    "이동": lambda: Goal(target_state="GOTO", destination_key=DEMO_DEFAULT_DESTINATION_KEY),
    "자장가": lambda: Goal(target_state="LULLABY"),
    "숨바꼭질": lambda: Goal(
        target_state="HIDEANDSEEK",
        target_id=DEMO_DEFAULT_CHILD_ID,
        # search_waypoints 는 router 의 /mode 핸들러가 _build_hideseek_goal_dynamic
        # → _build_group_patrol_order 로 yaml 의 group 셔플된 vertex 리스트로 동적 교체.
        # 빈 list 로 두면 yaml 로드 실패 시 reconciler 의 missing_search_waypoints 로 거부 —
        # hardcoded fallback 없음 (운영자가 yaml 정합성 확인하라는 의도).
        play_area_key="운동장-단상",
    ),
}


def mode_to_goal(mode_label: str) -> Goal:
    """한국어 mode 라벨 → Goal.

    Raises
    ------
    UnsupportedMode
        gogoping modes (대기/추종/이동/자장가/숨바꼭질/수동/복귀) 에 없는 라벨.
    """
    factory = _LABEL_TO_GOAL.get(mode_label)
    if factory is None:
        raise UnsupportedMode(f"unknown mode label: {mode_label!r}")
    return factory()


__all__ = ["Goal", "UnsupportedMode", "mode_to_goal", "DEMO_DEFAULT_TARGET_ID",
           "DEMO_DEFAULT_DESTINATION_KEY", "DEMO_DEFAULT_CHILD_ID"]
