# BT_follow_main

`FOLLOW` state 의 MainTree — 지정 대상 추종.

## Root composite

`build_active_main_tree("MainTree[FOLLOW]", ctx, body=FollowTrack("FollowTrack", ctx), task_body=True, ...)`

```
Parallel(SuccessOnSelected=[body])
├─ BatteryLowMonitor        common/battery_low_monitor.md        (✅ ≤15% → battery_low → LOW_BATTERY_RETURNING)
├─ MapBoundaryMonitor       common/map_boundary_monitor.md       (✅ 맵 밖 → fault → ERROR)
├─ HardwareHealthMonitor    common/hardware_health_monitor.md    (✅ LIDAR/odom staleness → fault)
├─ CommandListener          common/command_listener.md           (✅ cancel / 다른 state 전이)
└─ body: FollowTrack        ../behaviors/perception.md           (✅ /gogoping/tracking_state → TARGET_* 브리지)
```

`CollisionMonitor`·`ProximitySafetyMonitor` 제외 — 추종은 가까운 게 정상이라 근접 정지 대상이 아님. 실제 추종 제어(cmd_vel)는 `follow_node` 가 담당하고, 본 트리는 FOLLOW state 유지 + perception 반영(관측·표시).

### FollowTrack body (구 StubFollow 대체 완료)

body 는 단일 leaf `FollowTrack` — `/gogoping/tracking_state` 를 구독해 `TARGET_*` blackboard 로 브리지하며 **영구 RUNNING**(`task_done` 자동 발화 없음 → `cancel` / 다른 `*_request` 로만 이탈).
SubTree(`BT_follow_sub`) 는 **존재하지 않는다** — 구 `_stubs/stub_follow.py` placeholder 는 legacy(미사용).

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

※ `task_done` 자동 발화 없음 — `FollowTrack` 이 영구 RUNNING 이므로 body SUCCESS 미발생.
추종은 `cancel` / 다른 `*_request` 로만 이탈한다.

## 사용 behavior

- [battery_low_monitor](../behaviors/common.md#battery_low_monitor)
- [map_boundary_monitor](../behaviors/common.md#map_boundary_monitor)
- [hardware_health_monitor](../behaviors/common.md#hardware_health_monitor)
- [command_listener](../behaviors/common.md#command_listener)
- [FollowTrack](../behaviors/perception.md) — tracking_state → TARGET_* 브리지 (body)

## 상태

- 코드: ✅ ([BT_follow_main.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/trees/main_trees/BT_follow_main.py))
- shell helper: [`_shell.py`](../../src/gogoping/gogoping_modes/gogoping_modes/bt/trees/main_trees/_shell.py)
- body: `FollowTrack` ✅ ([perception/follow_track.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/perception/follow_track.py)) — SubTree 아님 (구 StubFollow 대체 완료)
