# BT_follow_main

`FOLLOW` state 의 MainTree — 지정 대상 추종.

## Root composite

`build_active_main_tree("MainTree[FOLLOW]", ctx, body=StubFollow(), task_body=True, ...)`

```
Parallel(SuccessOnSelected=[body])
├─ BatteryLowMonitor        common/battery_low_monitor.md        (✅ ≤20% → battery_low → LOW_BATTERY_RETURNING)
├─ MapBoundaryMonitor       common/map_boundary_monitor.md       (✅ 맵 밖 → fault → ERROR)
├─ HardwareHealthMonitor    common/hardware_health_monitor.md    (✅ LIDAR/odom staleness → fault)
├─ CommandListener          common/command_listener.md           (✅ cancel / 다른 state 전이)
└─ body: StubFollow                                              (☐ BT_follow_sub 미구현 — 영구 RUNNING)
```

`CollisionMonitor` 제외 — 사람 추종(REACTIVE)은 nav2 controller 를 안 거쳐(cmd_vel_raw 직접) collision_monitor gate 대상이 아니고, 추종 중 사람을 정지시키면 안 됨.

### StubFollow 정책

현재 body 는 `StubFollow()` — 항상 RUNNING 을 리턴하는 placeholder.
`task_done` 자동 발화 없음 — `cancel` / 다른 `*_request` 로만 FOLLOW 상태를 빠져나올 수 있다.

`BT_follow_sub` 구현 완료 후 `StubFollow` 를 `build_follow_subtree(ctx)` 로 교체 예정.
([status.md](../status.md) 의 BT_follow_sub 항목 ☐ 참조)

## 진입 trigger

| Trigger | From | 발화 주체 |
|---|---|---|
| `follow_request` | IDLE / GOTO / LULLABY / HIDEANDSEEK / MANUAL / RETURNING | `command_listener` (SetGoal target_state="FOLLOW", target_id=...) |

## 종료 trigger

| Trigger | To | 발화 주체 |
|---|---|---|
| `cancel` | IDLE | `command_listener` (SetGoal target_state="IDLE") |
| `goto_request` | GOTO | `command_listener` |
| `follow_request` | FOLLOW | `command_listener` (다른 target_id 로 재진입) |
| `lullaby_request` | LULLABY | `command_listener` |
| `hideseek_request` | HIDEANDSEEK | `command_listener` |
| `manual_request` | MANUAL | `command_listener` |
| `return_request` | RETURNING | `command_listener` |
| `battery_low` | LOW_BATTERY_RETURNING | `battery_low_monitor` |
| `fault` | ERROR | `map_boundary_monitor` / `hardware_health_monitor` |

※ `task_done` 자동 발화 없음 — `StubFollow` 가 영구 RUNNING 이므로 body SUCCESS 미발생.
`BT_follow_sub` 구현 후 완료 경로 추가 예정.

## 사용 behavior

- [battery_low_monitor](../behaviors/common.md#battery_low_monitor)
- [map_boundary_monitor](../behaviors/common.md#map_boundary_monitor)
- [hardware_health_monitor](../behaviors/common.md#hardware_health_monitor)
- [command_listener](../behaviors/common.md#command_listener)
- [BT_follow_sub](BT_follow_sub.md) — 추종 로직 (☐ 미구현)

## 상태

- 코드: ✅ ([BT_follow_main.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/trees/main_trees/BT_follow_main.py))
- shell helper: [`_shell.py`](../../src/gogoping/gogoping_modes/gogoping_modes/bt/trees/main_trees/_shell.py)
- body: `StubFollow` (☐ — BT_follow_sub 구현 후 교체 예정)
