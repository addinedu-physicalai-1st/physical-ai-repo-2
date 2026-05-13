# Blackboard 스키마

GogoPing BT 의 공유 변수 (`bt/blackboard.py` 의 `Keys` 상수) 와 R/W 권한 매트릭스.

> **규칙**
> - 키 이름은 **반드시 `Keys.<NAME>` 상수**로만 참조 (문자열 직접 사용 금지)
> - py_trees 의 `register_key()` 로 R/W 권한을 노드 `__init__` 에서 등록 — 미등록 접근은 런타임 에러
> - 신규 키 추가는 본 문서 PR + `Keys` 상수 + 권한 등록 세 가지 동시 변경

## 키 목록

### 시스템 모니터링 (interfaces/ 가 ROS 콜백으로 W)

| 키 | 타입 | W (writer) | R (reader) | 비고 |
|---|---|---|---|---|
| `battery_level` | `float` (0~100) | `battery_subscriber` | `battery_full_monitor`, `battery_low_monitor` | % |
| `hardware_health` | `dict[str, bool]` | (각 HW 토픽 subscriber) | `hardware_health_monitor` | 컴포넌트별 alive 플래그 |
| `collision_state` | `str` (`ok` / `warn` / `fault`) | `collision_subscriber` | `collision_event_handler` | Nav2 Collision Monitor |
| `docking_contact` | `bool` | `docking_contact_check` | `docking_contact_check` (self) | 도킹 접점 전류 흐름 |

### 명령 / 모드 (`command_listener` 가 W)

| 키 | 타입 | W | R | 비고 |
|---|---|---|---|---|
| `assist_task` | `str` (`carry` / `follow` / `lullaby` / `""`) | `command_listener` | `check_task` (BT_assist_main) | ASSIST 진입 시 세팅 |
| `play_task` | `str` (`hideseek` / `""`) | `command_listener` | `check_task` (BT_play_main) | PLAY 진입 시 세팅 |
| `carry_mode` | `str` (`manual` / `goto` / `follow`) | `command_listener` | `check_carry_mode` | carry 서브모드 |
| `target_person_id` | `str` | `command_listener` | `detect_target_person`, `child_face_tracker` | follow/hide-and-seek 추적 대상 (ReID/face_id) |

> 취소·복귀 등의 명령은 blackboard 플래그 없이 **`cancel` / `return_command` trigger 만 사용** — trigger ↔ blackboard 중복 방지.

### Perception (vision 토픽 어댑터가 W)

| 키 | 타입 | W | R | 비고 |
|---|---|---|---|---|
| `target_visible` | `bool` | `detect_target_person` | `is_target_visible`, `wait_for_reappear` | follow 대상 보임 |
| `target_pose` | `geometry_msgs/PoseStamped` | `detect_target_person` | `maintain_distance` | base_link 기준 대상 pose |
| `target_face_bbox` | `tuple[int,int,int,int]` | `detect_target_person` | `face_tracking` | 카메라 frame px (x,y,w,h) |
| `target_seen_at` | `float` (epoch sec) | `detect_target_person` | `wait_for_reappear`, `face_tracking` | 마지막 감지 시각 — staleness 판정용 |
| `found` | `bool` | `child_face_tracker` | `found_child` | 숨바꼭질 — 아이 발견 |
| `load_dropped` | `bool` | `load_stability_check` | `load_stability_check` (self) | 짐 떨어짐 |

### Navigation 타겟 (config 또는 `command_listener` 가 W)

| 키 | 타입 | W | R | 비고 |
|---|---|---|---|---|
| `destination_key` | `str` | `command_listener` | `navigate_to_pose` | carry goto 목적지 (DB named_pose) |
| `hide_position_key` | `str` | `command_listener` / config | `navigate_to_pose` | 숨바꼭질 숨을 위치 |
| `search_waypoints` | `list[str]` | config / `command_listener` | `navigate_to_pose` (loop) | 숨바꼭질 탐색 waypoint |
| `home_position_key` | `str` | config | `navigate_to_pose` | 숨바꼭질 원위치 |
| `charging_dock_approach_key` | `str` | config | `navigate_to_pose` | 도킹 접근 위치 |

> 주: `search_waypoints` 는 BT 의 `command_listener` 가 control-server 의 `GET /waypoints/patrol/hide_and_seek_search` 에서 가져와 세팅한다. control-server 도달 실패 시 `${PINGDER_BT_CACHE_DIR:-/tmp/pingder}/hide_and_seek_search.json` 캐시 fallback. helper: `gogoping_modes.utils.waypoints_client.fetch_patrol`.

### 에러 (fault 발화한 monitor 가 W)

| 키 | 타입 | W | R | 비고 |
|---|---|---|---|---|
| `error_reason` | `str` | (fault trigger 호출한 monitor) | `notify_admin_ui`, `log_error_to_db` | ERROR 진입 사유 (e.g., `"lidar_timeout"`) |
| `error_source` | `str` | (fault trigger 호출한 monitor) | `notify_admin_ui`, `log_error_to_db` | 발화 주체 식별 (e.g., `"HardwareHealthMonitor"`) — multi-writer 디버깅용 |

> 현재 FSM state 는 blackboard 키가 아니다. `context.fsm.current_state` (transitions 라이브러리 기본 속성) 를 직접 읽는다.

## `Keys` 상수 예시

```python
# bt/blackboard.py
class Keys:
    # 시스템
    BATTERY_LEVEL = "battery_level"
    HARDWARE_HEALTH = "hardware_health"
    COLLISION_STATE = "collision_state"
    DOCKING_CONTACT = "docking_contact"
    # 명령 / 모드
    ASSIST_TASK = "assist_task"
    PLAY_TASK = "play_task"
    CARRY_MODE = "carry_mode"
    TARGET_PERSON_ID = "target_person_id"
    # Perception
    TARGET_VISIBLE = "target_visible"
    TARGET_POSE = "target_pose"
    TARGET_FACE_BBOX = "target_face_bbox"
    TARGET_SEEN_AT = "target_seen_at"
    FOUND = "found"
    LOAD_DROPPED = "load_dropped"
    # Navigation
    DESTINATION_KEY = "destination_key"
    HIDE_POSITION_KEY = "hide_position_key"
    SEARCH_WAYPOINTS = "search_waypoints"
    HOME_POSITION_KEY = "home_position_key"
    CHARGING_DOCK_APPROACH_KEY = "charging_dock_approach_key"
    # 에러
    ERROR_REASON = "error_reason"
    ERROR_SOURCE = "error_source"
```

## 권한 등록 예시

```python
class BatteryLowMonitor(py_trees.behaviour.Behaviour):
    def __init__(self, name="BatteryLowMonitor"):
        super().__init__(name)
        self.bb = self.attach_blackboard_client(name)
        self.bb.register_key(key=Keys.BATTERY_LEVEL, access=py_trees.common.Access.READ)
```

## 초기값 (`init_blackboard()`)

| 키 | 초기값 |
|---|---|
| `battery_level` | `100.0` |
| `hardware_health` | `{}` |
| `collision_state` | `"ok"` |
| `docking_contact` | `False` |
| `assist_task` / `play_task` / `carry_mode` / `target_person_id` | `""` |
| `target_visible` / `found` / `load_dropped` | `False` |
| `target_pose` / `target_face_bbox` | `None` |
| `target_seen_at` | `0.0` |
| `destination_key` / `hide_position_key` / `home_position_key` / `charging_dock_approach_key` | `""` |
| `search_waypoints` | `[]` |
| `error_reason` / `error_source` | `""` |
