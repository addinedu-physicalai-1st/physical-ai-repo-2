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
    """Blackboard 변수 이름 상수 — 29개.

    **문자열 직접 사용 금지** — 항상 ``Keys.<NAME>`` 형태로만 참조.
    """

    # 시스템 모니터링 (interfaces/ 가 ROS 콜백으로 W)
    BATTERY_LEVEL = "battery_level"               # float 0~100 %
    HARDWARE_HEALTH = "hardware_health"           # dict[str, bool]
    COLLISION_STATE = "collision_state"           # "ok" / "warn" / "fault"
    DOCKING_CONTACT = "docking_contact"           # bool
    ROBOT_POSE = "robot_pose"                     # dict {x: float, y: float, yaw: float} — **map frame** (PoseSubscriber 가 /amcl_pose 에서 W)
    POSE_OVERRIDE_ACTIVE = "pose_override_active" # bool — True 면 PoseSubscriber 가 W skip (디버그 좌표 강제 시)

    # 명령 / 모드 (command_listener 가 W)
    TARGET_PERSON_ID = "target_person_id"         # str (ReID / face_id)

    # Perception (vision 토픽 어댑터가 W)
    TARGET_VISIBLE = "target_visible"             # bool
    TARGET_POSE = "target_pose"                   # geometry_msgs/PoseStamped
    TARGET_FACE_BBOX = "target_face_bbox"         # tuple[int, int, int, int]
    TARGET_SEEN_AT = "target_seen_at"             # float (epoch sec)
    FOUND = "found"                               # bool — 숨바꼭질 아이 발견

    # Navigation 타겟 (config 또는 command_listener 가 W)
    DESTINATION_KEY = "destination_key"           # str — DB named_pose
    HIDE_POSITION_KEY = "hide_position_key"
    SEARCH_WAYPOINTS = "search_waypoints"         # list[str]
    PATROL_CURRENT_INDEX = "patrol_current_index"  # int — search_waypoints 의 현재 진행 인덱스 (-1=idle, N=완료)
    HOME_POSITION_KEY = "home_position_key"
    CHARGING_DOCK_APPROACH_KEY = "charging_dock_approach_key"
    CHARGING_DOCK_TARGET_YAW = "charging_dock_target_yaw"  # float (rad) — AlignToDock 의 target yaw, SubTree 빌더가 graph 에서 vertex.yaw 로 채움

    # 숨바꼭질 (SR-PLAY-007) — UI / control-service / BT 협업
    HIDESEEK_PLAY_AREA_KEY = "hideseek_play_area_key"   # str — named pose key (= 운동장2)
    HIDESEEK_REGISTERED_IDS = "hideseek_registered_ids" # list[int] — 모집 종료 시 control-service 가 W
    HIDESEEK_CAUGHT_IDS = "hideseek_caught_ids"         # list[int] — 발견 시 control-service 가 W
    HIDESEEK_PHASE = "hideseek_phase"                   # str — "move_to_play"/"recruit"/"countdown"/"patrol"/"return"/"end"/""
    HIDESEEK_SKIP_COUNTDOWN = "hideseek_skip_countdown" # bool — True 면 Countdown 즉시 SUCCESS (debug)

    # 에러 (fault 발화한 monitor 가 W)
    ERROR_REASON = "error_reason"                 # str — e.g., "lidar_timeout"
    ERROR_SOURCE = "error_source"                 # str — 발화 주체 이름

    # 수동 모드 (manual_torque_hold 가 W)
    MANUAL_TORQUE_ACTIVE = "manual_torque_active" # bool — True 면 motor torque OFF 상태 (사용자 직접 밀기 가능). admin UI 표시용

    # IDLE 타임아웃 (idle_timeout_monitor 가 W) — admin UI 카운트다운 표시용
    IDLE_ENTERED_AT = "idle_entered_at"           # float (monotonic sec). IDLE 미진입 시 -1.0
    IDLE_TIMEOUT_SECONDS = "idle_timeout_seconds" # float — 현재 적용 중인 ROS param 값


# 부팅 시 초기값 — 사용 전 writer 가 없을 가능성이 있는 키만.
# 무엇이 어떤 시점에 쓰이는지는 docs/blackboard-schema.md 의 R/W 매트릭스.
_DEFAULTS: dict[str, object] = {
    # 시스템
    Keys.BATTERY_LEVEL: 100.0,
    Keys.HARDWARE_HEALTH: {},
    Keys.COLLISION_STATE: "ok",
    Keys.DOCKING_CONTACT: False,
    Keys.ROBOT_POSE: {"x": 0.0, "y": 0.0, "yaw": 0.0},
    Keys.POSE_OVERRIDE_ACTIVE: False,
    # 명령
    Keys.TARGET_PERSON_ID: "",
    # Perception
    Keys.TARGET_VISIBLE: False,
    Keys.TARGET_SEEN_AT: 0.0,
    Keys.FOUND: False,
    # Navigation
    Keys.DESTINATION_KEY: "",
    Keys.HIDE_POSITION_KEY: "",
    Keys.SEARCH_WAYPOINTS: [],
    Keys.PATROL_CURRENT_INDEX: -1,
    Keys.HOME_POSITION_KEY: "",
    Keys.CHARGING_DOCK_APPROACH_KEY: "",
    Keys.CHARGING_DOCK_TARGET_YAW: 0.0,
    # 숨바꼭질
    Keys.HIDESEEK_PLAY_AREA_KEY: "",
    Keys.HIDESEEK_REGISTERED_IDS: [],
    Keys.HIDESEEK_CAUGHT_IDS: [],
    Keys.HIDESEEK_PHASE: "",
    Keys.HIDESEEK_SKIP_COUNTDOWN: False,
    # 에러
    Keys.ERROR_REASON: "",
    Keys.ERROR_SOURCE: "",
    # 수동 모드
    Keys.MANUAL_TORQUE_ACTIVE: False,
    # IDLE 타임아웃
    Keys.IDLE_ENTERED_AT: -1.0,
    Keys.IDLE_TIMEOUT_SECONDS: 86400.0,
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
