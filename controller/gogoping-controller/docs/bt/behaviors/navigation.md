# Navigation Behaviors

nav2 / graph_router 호출 + 정지/도킹. 모두 `bt/behaviors/navigation/` 안.

---

## navigate_to_vertex {#navigate_to_vertex}

[bt/behaviors/navigation/navigate_to_vertex.py](../../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/navigation/navigate_to_vertex.py)

다익스트라로 lane 따라 vertex 까지 이동. graph_router 가 다익스트라로 vertex sequence 결정 + nav2 `NavigateToPose` 를 vertex 단위 chain 호출. graph routing 시스템 전체는 [../../graph-routing.md](../../graph-routing.md) 참조.

| 항목 | 값 |
|---|---|
| Action | `/graph_router/navigate_to_vertex` (gogoping_msgs/NavigateToVertex) |
| Blackboard read | `target_vertex_name` (str) — waypoints.yaml 의 name |
| Blackboard write | — |
| Status | RUNNING (이동 중) / SUCCESS (도착) / FAILURE (vertex 없음·경로 없음·nav2 거부·취소) |
| terminate(INVALID) | 진행 중 goal cancel |
| Used in | BT_goto_sub, BT_return_sub, BT_patrol_sub |

```python
from gogoping_modes.bt.behaviors.navigation.navigate_to_vertex import NavigateToVertex

# blackboard.target_vertex_name 을 미리 set 후
nav = NavigateToVertex()  # default target_key="target_vertex_name"
# main.py 의 BT 셋업에서: nav.setup(node=context.node)
```

---

## navigate_to_pose {#navigate_to_pose}  *(스켈레톤)*

[bt/behaviors/navigation/navigate_to_pose.py](../../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/navigation/) (예정)

nav2 `NavigateToPose` 직접 호출 — vertex 그래프 무시, 임의 pose 로 직선/우회. graph 외 일회성 이동에 사용.

| 항목 | 값 |
|---|---|
| Action | `/navigate_to_pose` (nav2_msgs/NavigateToPose) |
| Blackboard read | `target_pose_x`, `target_pose_y`, `target_pose_yaw` (또는 target_key 인자) |
| Used in | BT_hide_and_seek_sub (술래 위치), BT_return_sub (도킹 진입 직전) |

---

## align_to_dock {#align_to_dock}

[bt/behaviors/navigation/align_to_dock.py](../../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/navigation/align_to_dock.py)

블랙보드의 target yaw 까지 제자리 회전. ReturnSubTree 의 2단계 (NavigateToVertex 직후, ReverseIntoDock 직전) — 충전소입구 도착 시 nav2 가 yaw 안 맞춰주므로 (`yaw_goal_tolerance=3.14`) 본 behavior 가 보완.

| 항목 | 값 |
|---|---|
| Topic publish | `/gogoping/cmd_vel` (geometry_msgs/Twist) |
| Blackboard read | `ROBOT_POSE` (AMCL yaw), `CHARGING_DOCK_TARGET_YAW` (rad) |
| Blackboard write | — |
| Status | RUNNING (회전 중) / SUCCESS (\|yaw_error\| ≤ tolerance, cmd_vel=0 publish 후) / FAILURE (timeout 초과 또는 pose 없음) |
| ROS param | `align_tolerance_rad` (기본 0.05), `align_angular_speed` (기본 0.5), `align_timeout_sec` (기본 10.0) |
| terminate(INVALID) | cmd_vel = 0 publish (트리 중간 종료 시 정지) |
| Used in | BT_return_sub |

알고리즘: `error = wrap_to_pi(target_yaw - current_yaw)`. tolerance 안이면 정지+SUCCESS. 그렇지 않으면 부호로 회전 방향 결정, 고정 속도 `align_angular_speed` publish.

---

## reverse_into_dock {#reverse_into_dock}

[bt/behaviors/navigation/reverse_into_dock.py](../../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/navigation/reverse_into_dock.py)

고정 시간 동안 cmd_vel.linear.x 음수 publish — 도크 등진 자세에서 단순 후진 진입. 자동 도킹 (접점 감지 등) 은 발표 범위 외라 시간 기반.

| 항목 | 값 |
|---|---|
| Topic publish | `/gogoping/cmd_vel` (geometry_msgs/Twist) |
| Blackboard read/write | — |
| Status | RUNNING (elapsed < duration) / SUCCESS (elapsed ≥ duration, cmd_vel=0 publish 후) |
| ROS param | `reverse_duration_sec` (기본 10.0 — 1m / 0.1 m/s), `reverse_linear_x` (기본 -0.1) |
| terminate(INVALID) | cmd_vel = 0 publish |
| Used in | BT_return_sub |

> 명세상 `approach_dock` 으로 표기되었던 자리. 우리 디자인은 충전소입구 → 충전소 방향 후진이라 이름을 `reverse_into_dock` 으로 명확화.

---

## verify_docking_contact {#verify_docking_contact}

[bt/behaviors/navigation/verify_docking_contact.py](../../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/navigation/verify_docking_contact.py)

ReverseIntoDock 완료 후 `docked` FSM trigger 발사 → RETURNING / LOW_BATTERY_RETURNING → CHARGING 자동 전이. 자동 도킹 접점 센서는 미구현이라 현재 단순히 "후진 끝났으면 도크 도달 간주" 로 1tick SUCCESS + trigger 발사.

| 항목 | 값 |
|---|---|
| FSM trigger | `docked` (idempotent — 잘못된 state 에서는 transitions 라이브러리가 무시) |
| Blackboard read/write | — |
| Status | SUCCESS (매 tick — trigger 는 _fired 플래그로 1회만 발사) |
| terminate(INVALID) | cleanup 없음 |
| Used in | BT_return_sub (Sequence 의 마지막 자식) |

추후 확장: `blackboard.DOCKING_CONTACT` 가 True 일 때만 발사 + False 면 FAILURE 로 ReverseIntoDock 재시도 등.

---

## stop_base {#stop_base}  *(스켈레톤)*

`cmd_vel = 0` publish — 모바일 베이스 즉시 정지.

| Action / Topic | `/gogoping/cmd_vel` (Twist) |
| Used in | BT_follow_sub (target lost recovery) |

---

## maintain_distance {#maintain_distance}  *(스켈레톤)*

목표 거리 (1.5m) 유지 PD 컨트롤러 — cmd_vel + LiDAR fusion.

| Used in | BT_follow_sub |

---

## check_arrival {#check_arrival}  *(스켈레톤)*

추종 종료 조건 확인 (사용자 정지 / 목적지 도착).

| Used in | BT_follow_sub |
