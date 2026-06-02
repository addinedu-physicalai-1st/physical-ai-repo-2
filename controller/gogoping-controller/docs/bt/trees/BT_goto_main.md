# BT_goto_main

`GOTO` state 의 MainTree — 지정 vertex 로 이동.

## Root composite

`build_active_main_tree("MainTree[GOTO]", ctx, body=build_goto_subtree(ctx), task_body=True, ...)`

```
Parallel(SuccessOnSelected=[body])
├─ BatteryLowMonitor        common/battery_low_monitor.md        (✅ ≤20% → battery_low → LOW_BATTERY_RETURNING)
├─ MapBoundaryMonitor       common/map_boundary_monitor.md       (✅ 맵 밖 → fault → ERROR)
├─ HardwareHealthMonitor    common/hardware_health_monitor.md    (✅ LIDAR/odom staleness → fault)
├─ CommandListener          common/command_listener.md           (✅ cancel / 다른 state 전이)
└─ body: BT_goto_sub (Sequence)
      ├─ NavigateToVertex(destination_key)    — graph_router /navigate_to_vertex 호출
      └─ UIPublish("도착했습니다")             — /gogoping/ui_event
```

`CollisionMonitor` (✅ — COLLISION_STATE "stop" 5분 지속 → `cancel` → IDLE).

### task_body=True 정책

`SuccessOnSelected([body])` — body (BT_goto_sub) 가 SUCCESS 하면 root 도 SUCCESS →
`main.py._on_tree_success()` 가 `task_done` 발화 → GOTO → IDLE.
monitor 들은 항상 RUNNING 리턴 (monitor 컨벤션) — task 완료 신호는 body 만.

## 진입 trigger

| Trigger | From | 발화 주체 |
|---|---|---|
| `goto_request` | IDLE / FOLLOW / LULLABY / HIDEANDSEEK / MANUAL / RETURNING | `command_listener` (SetGoal target_state="GOTO", destination_key=...) |

## 종료 trigger

| Trigger | To | 발화 주체 |
|---|---|---|
| `task_done` | IDLE | `main.py._on_tree_success()` (body SUCCESS 시) |
| `cancel` | IDLE | `command_listener` (SetGoal target_state="IDLE") |
| `goto_request` | GOTO | `command_listener` (새 목적지로 재진입) |
| `follow_request` | FOLLOW | `command_listener` |
| `lullaby_request` | LULLABY | `command_listener` |
| `hideseek_request` | HIDEANDSEEK | `command_listener` |
| `manual_request` | MANUAL | `command_listener` |
| `return_request` | RETURNING | `command_listener` |
| `battery_low` | LOW_BATTERY_RETURNING | `battery_low_monitor` |
| `fault` | ERROR | `map_boundary_monitor` / `hardware_health_monitor` |

## 사용 behavior

- [battery_low_monitor](../behaviors/common.md#battery_low_monitor)
- [map_boundary_monitor](../behaviors/common.md#map_boundary_monitor)
- [hardware_health_monitor](../behaviors/common.md#hardware_health_monitor)
- [command_listener](../behaviors/common.md#command_listener)
- [BT_goto_sub](BT_goto_sub.md) — NavigateToVertex / UIPublish

## 상태

- 코드: ✅ ([BT_goto_main.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/trees/main_trees/BT_goto_main.py))
- shell helper: [`_shell.py`](../../src/gogoping/gogoping_modes/gogoping_modes/bt/trees/main_trees/_shell.py)
- 의존 behavior: 모두 ✅
- body SubTree: [BT_goto_sub](BT_goto_sub.md) ✅
