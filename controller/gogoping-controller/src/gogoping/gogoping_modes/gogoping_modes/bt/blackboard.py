"""BT blackboard 스키마 — 공유 변수 키 + 초기값.

자세한 R/W 매트릭스 / 카테고리별 설명: ``docs/blackboard-schema.md``

사용:
    from gogoping_modes.bt.blackboard import Keys, init_blackboard

    # 부팅 시 1회
    init_blackboard()

    # behavior 안에서 (conventions.md §2.1)
    self.bb = self.attach_blackboard_client(name=self.name)
    self.bb.register_key(key=Keys.BATTERY_LEVEL, access=Access.READ)
    level = self.bb.get(Keys.BATTERY_LEVEL)
"""
from __future__ import annotations

import py_trees
from py_trees.common import Access


class Keys:
    """Blackboard 변수 이름 상수 — 22개.

    **문자열 직접 사용 금지** — 항상 ``Keys.<NAME>`` 형태로만 참조.
    """

    # 시스템 모니터링 (interfaces/ 가 ROS 콜백으로 W)
    BATTERY_LEVEL = "battery_level"               # float 0~100 %
    HARDWARE_HEALTH = "hardware_health"           # dict[str, bool]
    COLLISION_STATE = "collision_state"           # "ok" / "warn" / "fault"
    DOCKING_CONTACT = "docking_contact"           # bool

    # 명령 / 모드 (command_listener 가 W)
    ASSIST_TASK = "assist_task"                   # "carry" / "follow" / "lullaby" / ""
    PLAY_TASK = "play_task"                       # "hideseek" / ""
    CARRY_MODE = "carry_mode"                     # "manual" / "goto" / "follow"
    TARGET_PERSON_ID = "target_person_id"         # str (ReID / face_id)

    # Perception (vision 토픽 어댑터가 W)
    TARGET_VISIBLE = "target_visible"             # bool
    TARGET_POSE = "target_pose"                   # geometry_msgs/PoseStamped
    TARGET_FACE_BBOX = "target_face_bbox"         # tuple[int, int, int, int]
    TARGET_SEEN_AT = "target_seen_at"             # float (epoch sec)
    FOUND = "found"                               # bool — 숨바꼭질 아이 발견
    LOAD_DROPPED = "load_dropped"                 # bool

    # Navigation 타겟 (config 또는 command_listener 가 W)
    DESTINATION_KEY = "destination_key"           # str — DB named_pose
    HIDE_POSITION_KEY = "hide_position_key"
    SEARCH_WAYPOINTS = "search_waypoints"         # list[str]
    HOME_POSITION_KEY = "home_position_key"
    CHARGING_DOCK_APPROACH_KEY = "charging_dock_approach_key"

    # 에러 (fault 발화한 monitor 가 W)
    ERROR_REASON = "error_reason"                 # str — e.g., "lidar_timeout"
    ERROR_SOURCE = "error_source"                 # str — 발화 주체 이름


# 부팅 시 초기값 — 사용 전 writer 가 없을 가능성이 있는 키만.
# 무엇이 어떤 시점에 쓰이는지는 docs/blackboard-schema.md 의 R/W 매트릭스.
_DEFAULTS: dict[str, object] = {
    # 시스템
    Keys.BATTERY_LEVEL: 100.0,
    Keys.HARDWARE_HEALTH: {},
    Keys.COLLISION_STATE: "ok",
    Keys.DOCKING_CONTACT: False,
    # 명령
    Keys.ASSIST_TASK: "",
    Keys.PLAY_TASK: "",
    Keys.CARRY_MODE: "",
    Keys.TARGET_PERSON_ID: "",
    # Perception
    Keys.TARGET_VISIBLE: False,
    Keys.TARGET_SEEN_AT: 0.0,
    Keys.FOUND: False,
    Keys.LOAD_DROPPED: False,
    # Navigation
    Keys.DESTINATION_KEY: "",
    Keys.HIDE_POSITION_KEY: "",
    Keys.SEARCH_WAYPOINTS: [],
    Keys.HOME_POSITION_KEY: "",
    Keys.CHARGING_DOCK_APPROACH_KEY: "",
    # 에러
    Keys.ERROR_REASON: "",
    Keys.ERROR_SOURCE: "",
    # 주: TARGET_POSE / TARGET_FACE_BBOX 는 perception writer 가 세팅 전까지
    # 미정의 — reader 가 hasattr / try-except 로 staleness 판정.
}


def init_blackboard() -> None:
    """전역 blackboard 의 모든 default key 에 초기값 세팅.

    부팅 시 1회 호출 — ``main.py`` 의 ``GogopingModes.__init__`` 에서.
    각 behavior 는 본인의 R/W 권한을 ``register_key()`` 로 따로 등록한다.
    """
    bb = py_trees.blackboard.Client(name="init_blackboard")
    for key, default in _DEFAULTS.items():
        bb.register_key(key=key, access=Access.WRITE)
        bb.set(key, default)


# All public symbols.
__all__ = ["Keys", "init_blackboard"]
