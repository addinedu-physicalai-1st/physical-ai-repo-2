# BT_idle_main

`IDLE` state 의 MainTree — 명령 대기. 모든 active mode 의 출발점.

## Root composite

```
Parallel(SuccessOnAll(synchronise=False))
├─ BatteryLowMonitor        common/battery_low_monitor.md        (✅ ≤20% → battery_low → RETURNING)
├─ IdleTimeoutMonitor       common/idle_timeout_monitor.md       (✅ N초 무명령 → idle_timeout → RETURNING)
├─ MapBoundaryMonitor       common/map_boundary_monitor.md       (✅ 맵 밖 → fault → ERROR)
├─ HardwareHealthMonitor    common/hardware_health_monitor.md    (✅ LIDAR/odom staleness → fault)
└─ CommandListener          common/command_listener.md           (✅)
```

`CollisionMonitor` 미배치 — IDLE 은 정지 상태(주행 없음)라 collision_monitor gate 무관.

### IdleTimeoutMonitor 의 역할

무인 환경에서 IDLE 진입 후 사용자 명령 없이 `idle_timeout_seconds` (ROS param, 기본 60s)
경과하면 `idle_timeout` trigger → RETURNING 자동 발화. 도크 자율 복귀 보장.

- `initialise()` 가 timer 리셋 — IDLE 재진입 시 새로 카운트
- edge-triggered (`_fired` 플래그) — 한 번 발화 후 재발화 안 함

## 진입 / 종료 trigger

### 진입
| Trigger | From | Source |
|---|---|---|
| `battery_full` | CHARGING | `battery_full_monitor` (CHARGING 안의) |
| `task_done` | GOTO / FOLLOW / LULLABY / HIDEANDSEEK | `main.py._on_tree_success()` (해당 MainTree root SUCCESS) |
| `cancel` | GOTO / FOLLOW / LULLABY / HIDEANDSEEK / MANUAL / RETURNING | `command_listener` (SetGoal target_state="IDLE") |

### 종료
| Trigger | To | Source |
|---|---|---|
| `goto_request` | GOTO | `command_listener` (SetGoal target_state="GOTO", destination_key=...) |
| `follow_request` | FOLLOW | `command_listener` (SetGoal target_state="FOLLOW", target_id=...) |
| `lullaby_request` | LULLABY | `command_listener` (SetGoal target_state="LULLABY") |
| `hideseek_request` | HIDEANDSEEK | `command_listener` (SetGoal target_state="HIDEANDSEEK", search_waypoints=[...]) |
| `manual_request` | MANUAL | `command_listener` (SetGoal target_state="MANUAL") |
| `return_request` | RETURNING | `command_listener` (SetGoal target_state="RETURNING") |
| `battery_low` | LOW_BATTERY_RETURNING | `battery_low_monitor` (≤20%, hysteresis 25% 진출) |
| `idle_timeout` | RETURNING | `idle_timeout_monitor` (param `idle_timeout_seconds` 경과) |
| `fault` | ERROR | `map_boundary_monitor` / `hardware_health_monitor` |

## 사용 behavior

- [battery_low_monitor](../behaviors/common.md#battery_low_monitor)
- [idle_timeout_monitor](../behaviors/common.md#idle_timeout_monitor)
- [map_boundary_monitor](../behaviors/common.md#map_boundary_monitor)
- [hardware_health_monitor](../behaviors/common.md#hardware_health_monitor)
- [command_listener](../behaviors/common.md#command_listener)

## 상태

- 코드: ✅ ([BT_idle_main.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/trees/main_trees/BT_idle_main.py))
- 의존 behavior: 5 개 모두 ✅
