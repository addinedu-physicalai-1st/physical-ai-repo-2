"""한국어 mode 라벨 → Goal.msg 필드 변환.

robot-web 의 모드 메뉴 (``shared/robots.json`` 의 gogoping.modeTree) 가 보내는
한국어 mode 이름 ("추종", "운반", "수동", "자장가", "숨바꼭질", "대기") 을
``gogoping_msgs/msg/Goal`` 의 ``{mode, task, destination_key, target_id}``
필드로 변환.

UI 가 target_id / destination_key 를 명시적으로 지정하지 않는 Day 1 단계엔 *데모용 기본값*
사용 — 실제 운영 시에는 UI 에 추가 dropdown 등이 필요 (어느 선생님을 따라갈지 / 어느
장소로 운반할지). 데모 기본값은 ``DEMO_*`` 상수로 격리해 후속 수정 명확하게.

순수 함수 — ROS / FastAPI 의존성 없음. 단위 테스트 가능.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# Day 1 walking skeleton 용 데모 기본값.
# Day 2~3 에 UI 에 명시 선택 (어느 선생님 / 어느 장소) 추가 후 제거.
DEMO_DEFAULT_TARGET_ID = "demo_teacher"
DEMO_DEFAULT_DESTINATION_KEY = "demo_destination"
DEMO_DEFAULT_CHILD_ID = "demo_child"


@dataclass
class Goal:
    """``gogoping_msgs/msg/Goal`` 의 Python dataclass 미러.

    ROS srv 호출 시 본 dataclass 의 필드를 그대로 ``Goal.msg`` 인스턴스에 copy.
    """

    mode: str
    task: str = ""
    destination_key: str = ""
    target_id: str = ""

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "task": self.task,
            "destination_key": self.destination_key,
            "target_id": self.target_id,
        }


class UnsupportedMode(ValueError):
    """robots.json 의 gogoping modes 외 라벨이 들어온 경우."""


def mode_to_goal(mode_label: str) -> Goal:
    """한국어 mode 라벨 → Goal.

    Raises
    ------
    UnsupportedMode
        gogoping modes (대기/보조/추종/운반/자장가/놀이/숨바꼭질/수동) 에 없는 라벨.
        "보조" / "놀이" 는 그룹 라벨 (selfSelectable: false) 이라 직접 클릭 불가하지만
        들어오면 거부.
    """
    if mode_label == "대기":
        return Goal(mode="IDLE")

    if mode_label == "수동":
        return Goal(mode="MANUAL")

    if mode_label == "복귀":
        return Goal(mode="RETURNING")

    if mode_label == "추종":
        return Goal(
            mode="ASSIST", task="follow",
            target_id=DEMO_DEFAULT_TARGET_ID,
        )

    if mode_label == "운반":
        return Goal(
            mode="ASSIST", task="goto",
            destination_key=DEMO_DEFAULT_DESTINATION_KEY,
        )

    if mode_label == "자장가":
        return Goal(mode="ASSIST", task="lullaby")

    if mode_label == "숨바꼭질":
        return Goal(
            mode="PLAY", task="hideseek",
            target_id=DEMO_DEFAULT_CHILD_ID,
        )

    # 보조 / 놀이 — 그룹 라벨 (selfSelectable: false). UI 는 선택 못 함.
    if mode_label in ("보조", "놀이"):
        raise UnsupportedMode(
            f"mode={mode_label!r} 은 그룹 라벨 — 직접 클릭 불가. "
            f"하위 모드 (추종/운반/자장가 / 숨바꼭질) 를 사용하세요."
        )

    raise UnsupportedMode(f"unknown mode label: {mode_label!r}")


__all__ = [
    "Goal", "UnsupportedMode", "mode_to_goal",
    "DEMO_DEFAULT_TARGET_ID", "DEMO_DEFAULT_DESTINATION_KEY", "DEMO_DEFAULT_CHILD_ID",
]
