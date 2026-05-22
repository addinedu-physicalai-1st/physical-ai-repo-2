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
| `battery_level` | `float` (0~100) | `battery_subscriber` | `battery_full_monitor`, `battery_low_monitor`, `tree_inspector` | % |
| `hardware_health` | `dict[str, bool]` | (각 HW 토픽 subscriber) | `hardware_health_monitor` | 컴포넌트별 alive 플래그 |
| `collision_state` | `str` (`ok` / `warn` / `fault`) | `collision_subscriber` | `collision_event_handler` | Nav2 Collision Monitor |
| `docking_contact` | `bool` | `docking_contact_check` | `docking_contact_check` (self) | 도킹 접점 전류 흐름 |
| `robot_pose` | `dict {x: float, y: float, yaw: float}` | `pose_subscriber` (`/amcl_pose` → map frame) | `map_boundary_monitor`, `align_to_dock`, `tree_inspector` | AMCL localization 결과 (map frame). 부팅 시 `{0.0, 0.0, 0.0}` |
| `pose_override_active` | `bool` | `command_listener` (`SetRobotPose.srv`) | `pose_subscriber` (W skip 판정) | True 면 `/amcl_pose` 메시지 무시 → ROBOT_POSE 유지. 디버그 좌표 강제용 |

### 명령 / 모드 (`command_listener` 가 W)

| 키 | 타입 | W | R | 비고 |
|---|---|---|---|---|
| `assist_task` | `str` (`goto` / `follow` / `lullaby` / `""`) | `command_listener` | `check_task` (BT_assist_main) | ASSIST 진입 시 세팅 |
| `play_task` | `str` (`hideseek` / `""`) | `command_listener` | `check_task` (BT_play_main) | PLAY 진입 시 세팅 |
| `target_person_id` | `str` | `command_listener` | `detect_target_person`, `child_face_tracker` | follow/hide-and-seek 추적 대상 (ReID/face_id) |

> 취소·복귀 등의 명령은 blackboard 플래그 없이 **`cancel` / `return_request` trigger 만 사용** — trigger ↔ blackboard 중복 방지.

### Perception (vision 토픽 어댑터가 W)

| 키 | 타입 | W | R | 비고 |
|---|---|---|---|---|
| `target_visible` | `bool` | `detect_target_person` | `is_target_visible`, `wait_for_reappear` | follow 대상 보임 |
| `target_pose` | `geometry_msgs/PoseStamped` | `detect_target_person` | `maintain_distance` | base_link 기준 대상 pose |
| `target_face_bbox` | `tuple[int,int,int,int]` | `detect_target_person` | `face_tracking` | 카메라 frame px (x,y,w,h) |
| `target_seen_at` | `float` (epoch sec) | `detect_target_person` | `wait_for_reappear`, `face_tracking` | 마지막 감지 시각 — staleness 판정용 |
| `found` | `bool` | `child_face_tracker` | `found_child` | 숨바꼭질 — 아이 발견 |

### Navigation 타겟 (config 또는 `command_listener` 가 W)

| 키 | 타입 | W | R | 비고 |
|---|---|---|---|---|
| `destination_key` | `str` | `command_listener` | `navigate_to_vertex` (BT_goto_sub 에서 `target_key=Keys.DESTINATION_KEY` 로 명시) | goto 목적지 (waypoints.yaml vertex 이름) |
| `target_vertex_name` | `str` | `select_vertex` | `navigate_to_vertex` (default `target_key`) | NavigateToVertex 의 기본 R 키. BT_patrol_sub 의 각 visit 마다 SelectVertex 가 W. **string literal — Keys 에 등재되지 않음** (현재 정책) |
| `hide_position_key` | `str` | `command_listener` / config | `navigate_to_pose` | 숨바꼭질 숨을 위치 |
| `search_waypoints` | `list[str]` | config / `command_listener` | `navigate_to_pose` (loop) | 숨바꼭질 탐색 waypoint |
| `home_position_key` | `str` | config | `navigate_to_pose` | 숨바꼭질 원위치 |
| `charging_dock_approach_key` | `str` | config | `navigate_to_pose` | 도킹 접근 위치 |
| `charging_dock_target_yaw` | `float` (rad) | SubTree 빌더 (graph 의 vertex.yaw) | `align_to_dock` | AlignToDock 의 target yaw — robot 이 도크 등진 자세로 정렬 |

> 주: `search_waypoints` 는 BT 의 `command_listener` 가 control-server 의 `GET /waypoints/patrol/hide_and_seek_search` 에서 가져와 세팅한다. control-server 도달 실패 시 `${PINGDER_BT_CACHE_DIR:-/tmp/pingder}/hide_and_seek_search.json` 캐시 fallback. helper: `gogoping_modes.utils.waypoints_client.fetch_patrol`.

### 에러 (fault 발화한 monitor 가 W)

| 키 | 타입 | W | R | 비고 |
|---|---|---|---|---|
| `error_reason` | `str` | (fault trigger 호출한 monitor), `command_listener` (emergency_stop 시 `"user_emergency_stop"`) | `notify_admin_ui`, `log_error_to_db` | ERROR 진입 사유 (e.g., `"lidar_timeout"`, `"out_of_map"`, `"user_emergency_stop"`) |
| `error_source` | `str` | (fault trigger 호출한 monitor), `command_listener` (`"emergency_stop_service"`) | `notify_admin_ui`, `log_error_to_db` | 발화 주체 식별 (e.g., `"HardwareHealthMonitor"`, `"emergency_stop_service"`) — multi-writer 디버깅용 |

### 수동 모드 (manual_torque_hold 가 W)

| 키 | 타입 | W | R | 비고 |
|---|---|---|---|---|
| `manual_torque_active` | `bool` | `manual_torque_hold` (initialise=True, terminate=False) | admin UI (snapshot 경유) | True 면 motor torque OFF 상태 — 사용자가 직접 밀어 이동 중. UI 표시용 |

### IDLE 타임아웃 (idle_timeout_monitor 가 W)

| 키 | 타입 | W | R | 비고 |
|---|---|---|---|---|
| `idle_entered_at` | `float` (monotonic sec) | `idle_timeout_monitor` (initialise=time.monotonic(), terminate=-1.0) | `tree_inspector.snapshot` | IDLE 진입 시각. snapshot 변환 시 `idle_seconds_remaining` 계산 base. 미진입 = -1.0 |
| `idle_timeout_seconds` | `float` | `idle_timeout_monitor` (param 읽은 값) | `tree_inspector.snapshot` | 현재 적용 중인 ROS param `idle_timeout_seconds` 값. admin UI 카운트다운 totals 표시용 |

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
    ROBOT_POSE = "robot_pose"
    POSE_OVERRIDE_ACTIVE = "pose_override_active"
    # 명령 / 모드
    ASSIST_TASK = "assist_task"
    PLAY_TASK = "play_task"
    TARGET_PERSON_ID = "target_person_id"
    # Perception
    TARGET_VISIBLE = "target_visible"
    TARGET_POSE = "target_pose"
    TARGET_FACE_BBOX = "target_face_bbox"
    TARGET_SEEN_AT = "target_seen_at"
    FOUND = "found"
    # Navigation
    DESTINATION_KEY = "destination_key"
    HIDE_POSITION_KEY = "hide_position_key"
    SEARCH_WAYPOINTS = "search_waypoints"
    HOME_POSITION_KEY = "home_position_key"
    CHARGING_DOCK_APPROACH_KEY = "charging_dock_approach_key"
    CHARGING_DOCK_TARGET_YAW = "charging_dock_target_yaw"
    # 에러
    ERROR_REASON = "error_reason"
    ERROR_SOURCE = "error_source"
    # 수동 모드
    MANUAL_TORQUE_ACTIVE = "manual_torque_active"
    # IDLE 타임아웃
    IDLE_ENTERED_AT = "idle_entered_at"
    IDLE_TIMEOUT_SECONDS = "idle_timeout_seconds"
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
| `robot_pose` | `{"x": 0.0, "y": 0.0, "yaw": 0.0}` |
| `pose_override_active` | `False` |
| `assist_task` / `play_task` / `target_person_id` | `""` |
| `target_visible` / `found` | `False` |
| `target_pose` / `target_face_bbox` | `None` (writer 가 세팅 전까진 미정의 — reader 는 try/except) |
| `target_seen_at` | `0.0` |
| `destination_key` / `hide_position_key` / `home_position_key` / `charging_dock_approach_key` | `""` |
| `search_waypoints` | `[]` |
| `charging_dock_target_yaw` | `0.0` |
| `error_reason` / `error_source` | `""` |
| `manual_torque_active` | `False` |
| `idle_entered_at` | `-1.0` |
| `idle_timeout_seconds` | `86400.0` (24시간 — IdleTimeoutMonitor 기본값, ROS param `idle_timeout_seconds` 로 오버라이드 가능) |
