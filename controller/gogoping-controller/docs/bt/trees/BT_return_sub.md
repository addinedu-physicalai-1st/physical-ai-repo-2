# BT_return_sub

도크 복귀 SubTree — RETURNING / LOW_BATTERY_RETURN MainTree 의 Parallel 자식으로 부착.

[bt/trees/sub_trees/BT_return_sub.py](../../../src/gogoping/gogoping_modes/gogoping_modes/bt/trees/sub_trees/BT_return_sub.py)

## Root composite

```
OneShot (policy=ON_COMPLETION, name="BT_return_sub")
└─ Sequence (memory=True)
     ├─ NavigateToVertex(target_key="charging_dock_approach_key")  # 충전소입구 vertex 로 graph routing
     ├─ AlignToDock                                                 # CHARGING_DOCK_TARGET_YAW 까지 회전
     ├─ ReverseIntoDock                                              # N초 후진
     └─ VerifyDockingContact                                         # docked trigger 자동 발사 → CHARGING
```

`OneShot(ON_COMPLETION)` 으로 감싸 한 번 SUCCESS / FAILURE 후 재실행 차단 (Sequence 가 매 tick 다시 처음부터 돌아 NavigateToVertex 가 도크에서 다시 나가는 버그 방지). 이름 `BT_return_sub` 은 tree_inspector 의 `BT_*_sub` 패턴 매칭용 — admin UI BT SUB 영역에 표시됨.

## 사용 behavior

- [navigate_to_vertex](../behaviors/navigation.md#navigate_to_vertex) — graph_router 액션 (다익스트라 + nav2 NavigateThroughPoses 위임)
- [align_to_dock](../behaviors/navigation.md#align_to_dock) — `ROBOT_POSE.yaw` ↔ `CHARGING_DOCK_TARGET_YAW` 비교, `cmd_vel.angular.z` 회전
- [reverse_into_dock](../behaviors/navigation.md#reverse_into_dock) — N초 동안 `cmd_vel.linear.x` 후진 publish
- [verify_docking_contact](../behaviors/navigation.md#verify_docking_contact) — `docked` trigger 1회 발사 → CHARGING 자동 전이

## Blackboard 사전 세팅 (빌더가 책임)

빌더 `build_return_subtree(ctx)` 호출 시점 (= RETURNING / LOW_BATTERY_RETURN 진입에 따른 BT swap 시) 에 다음 키를 1회 채운다:

| 키 | 값 |
|---|---|
| `CHARGING_DOCK_APPROACH_KEY` | `"충전소입구"` (waypoints.yaml 의 vertex name) |
| `CHARGING_DOCK_TARGET_YAW` | waypoints.yaml 의 충전소입구 vertex.yaw (현재 `-π/2`) |

yaml 이 admin UI graph editor 로 갱신되면 다음 RETURNING 진입 시 자동 반영.

## 진입 / 종료 trigger

| trigger | 발화 주체 | 의미 |
|---|---|---|
| (진입) `return_request`, `battery_low`, `idle_timeout` | command_listener / battery_low_monitor / idle_timeout_monitor | MainTree swap → BT_return_sub 빌드 |
| (종료) `docked` | **VerifyDockingContact** (BT 자체) | ReverseIntoDock 완료 직후 자동 발사 → CHARGING. 접점 센서 미통합이라 시간 기반 후진을 도킹 완료로 간주 |
| (종료) `fault` | MapBoundaryMonitor / HardwareHealthMonitor 등 | → ERROR |

[../../fsm-triggers.md](../../fsm-triggers.md) 참조.

## ROS param (behavior 내부)

- `align_tolerance_rad` (기본 0.05 ≈ 3°)
- `align_angular_speed` (기본 0.5 rad/s)
- `align_timeout_sec` (기본 10.0)
- `reverse_duration_sec` (기본 10.0 — 1m / 0.1 m/s 가정)
- `reverse_linear_x` (기본 -0.1)

## 범위 외 (추후)

- `docking_contact` 토픽 / 센서 통합 — VerifyDockingContact 가 센서 값으로 진짜 검증하게 확장
- HardwareHealthMonitor, CollisionEventHandler 의 ReturnSubTree 와의 상호작용
