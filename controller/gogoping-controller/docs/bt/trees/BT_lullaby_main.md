# BT_lullaby_main

`LULLABY` state 의 MainTree — 자장가 재생.

## Root composite

`build_active_main_tree("MainTree[LULLABY]", ctx, body=build_lullaby_subtree(ctx), task_body=True, ...)`

```
Parallel(SuccessOnSelected=[body])
├─ BatteryLowMonitor        common/battery_low_monitor.md        (✅ ≤20% → battery_low → LOW_BATTERY_RETURNING)
├─ MapBoundaryMonitor       common/map_boundary_monitor.md       (✅ 맵 밖 → fault → ERROR)
├─ HardwareHealthMonitor    common/hardware_health_monitor.md    (✅ LIDAR/odom staleness → fault)
├─ CommandListener          common/command_listener.md           (✅ cancel / 다른 state 전이)
└─ body: LullabyAudio (단일 leaf)                                (✅ 영구 RUNNING — 외부 trigger 로만 종료)
      ├─ initialise(): ui_event "lullaby_play" publish
      ├─ update():     Status.RUNNING (영구)
      └─ terminate():  ui_event "lullaby_stop" publish (idempotent)
```

### LullabyAudio 정책

body 는 `LullabyAudio` — 항상 RUNNING.
`task_done` 자동 발화 없음 — `cancel` / 다른 `*_request` / `battery_low` / `fault` 로만 종료.
모든 종료 경로에서 `main.py._build_tree_for_state()` 가 `root.stop(INVALID)` 호출
→ `LullabyAudio.terminate()` 전파 → "lullaby_stop" publish 보장.

## 진입 trigger

| Trigger | From | 발화 주체 |
|---|---|---|
| `lullaby_request` | IDLE / GOTO / FOLLOW / HIDEANDSEEK / MANUAL / RETURNING | `command_listener` (SetGoal target_state="LULLABY") |

## 종료 trigger

| Trigger | To | 발화 주체 |
|---|---|---|
| `cancel` | IDLE | `command_listener` (SetGoal target_state="IDLE") |
| `goto_request` | GOTO | `command_listener` |
| `follow_request` | FOLLOW | `command_listener` |
| `lullaby_request` | LULLABY | `command_listener` (재진입 — 동일 state) |
| `hideseek_request` | HIDEANDSEEK | `command_listener` |
| `manual_request` | MANUAL | `command_listener` |
| `return_request` | RETURNING | `command_listener` |
| `battery_low` | LOW_BATTERY_RETURNING | `battery_low_monitor` |
| `fault` | ERROR | `map_boundary_monitor` / `hardware_health_monitor` |

※ `task_done` 자동 발화 없음 — `LullabyAudio` 가 영구 RUNNING.

## 사용 behavior

- [battery_low_monitor](../behaviors/common.md#battery_low_monitor)
- [map_boundary_monitor](../behaviors/common.md#map_boundary_monitor)
- [hardware_health_monitor](../behaviors/common.md#hardware_health_monitor)
- [command_listener](../behaviors/common.md#command_listener)
- [BT_lullaby_sub](BT_lullaby_sub.md) — LullabyAudio (단일 leaf body)

## 상태

- 코드: ✅ ([BT_lullaby_main.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/trees/main_trees/BT_lullaby_main.py))
- shell helper: [`_shell.py`](../../src/gogoping/gogoping_modes/gogoping_modes/bt/trees/main_trees/_shell.py)
- 의존 behavior: 모두 ✅
- body SubTree: [BT_lullaby_sub](BT_lullaby_sub.md) ✅
