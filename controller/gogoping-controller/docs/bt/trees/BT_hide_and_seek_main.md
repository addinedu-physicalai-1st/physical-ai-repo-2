# BT_hide_and_seek_main

`HIDEANDSEEK` state 의 MainTree — 숨바꼭질. body 는 [BT_hide_and_seek_sub](BT_hide_and_seek_sub.md) 의 6-step Sequence (move → recruit → countdown → patrol → return → end).

## Root composite

`build_active_main_tree("MainTree[HIDEANDSEEK]", ctx, body=build_hide_and_seek_sub(ctx), task_body=True, ...)`

```
Parallel(SuccessOnSelected=[body])
├─ BatteryLowMonitor        common/battery_low_monitor.md        (✅ ≤20% → battery_low → LOW_BATTERY_RETURNING)
├─ MapBoundaryMonitor       common/map_boundary_monitor.md       (✅ 맵 밖 → fault → ERROR)
├─ HardwareHealthMonitor    common/hardware_health_monitor.md    (✅ LIDAR/odom staleness → fault)
├─ CommandListener          common/command_listener.md           (✅ cancel / 다른 state 전이)
└─ body: build_hide_and_seek_sub(ctx)
      └─ BT_hide_and_seek_sub (Sequence, 6-step)   — move → recruit → countdown → patrol → return → end (✅)
            └─ (play_area / waypoints 결손 시) Failure leaf  — 방어 분기
```

추후 추가 예정: `CollisionEventHandler` (현재 ☐).

### task_body=True 정책

`SuccessOnSelected([body])` — body (BT_hide_and_seek_sub) 가 SUCCESS 하면 root 도 SUCCESS →
`main.py._on_tree_success()` 가 `task_done` 발화 → HIDEANDSEEK → IDLE.
다만 6-step body 의 마지막 step (`step_end`) 이 `py_trees.behaviours.Running()` 을 자식으로 — root SUCCESS 가 정상 경로에선 발생하지 않는다. 사용자 명시 cancel 이 종료시킨다. 자세한 의도: [BT_hide_and_seek_sub.md](BT_hide_and_seek_sub.md#step_end--영구-running-idle).

## 진입 trigger

| Trigger | From | 발화 주체 |
|---|---|---|
| `hideseek_request` | IDLE / GOTO / FOLLOW / LULLABY / MANUAL / RETURNING | `command_listener` (SetGoal target_state="HIDEANDSEEK", target_id=..., search_waypoints=[...]) |

## 종료 trigger

| Trigger | To | 발화 주체 |
|---|---|---|
| `task_done` | IDLE | `main.py._on_tree_success()` (patrol 완료 시 body SUCCESS) |
| `cancel` | IDLE | `command_listener` (SetGoal target_state="IDLE") |
| `goto_request` | GOTO | `command_listener` |
| `follow_request` | FOLLOW | `command_listener` |
| `lullaby_request` | LULLABY | `command_listener` |
| `hideseek_request` | HIDEANDSEEK | `command_listener` (새 waypoints 로 재진입) |
| `manual_request` | MANUAL | `command_listener` |
| `return_request` | RETURNING | `command_listener` |
| `battery_low` | LOW_BATTERY_RETURNING | `battery_low_monitor` |
| `fault` | ERROR | `map_boundary_monitor` / `hardware_health_monitor` |

## blackboard 준비

`command_listener` 가 `hideseek_request` 발화 직전 다음 키 세팅:

| Key | 값 | 비고 |
|---|---|---|
| `target_person_id` | ReID / face_id | 놀이 상대 아이 (진짜 hideseek 확장 시 사용) |
| `search_waypoints` | list[str] | 탐색 waypoint — 빈 리스트 시 goal_reconciler 거부 |
| `home_position_key` | str | 원위치 vertex |

## 사용 behavior

- [battery_low_monitor](../behaviors/common.md#battery_low_monitor)
- [map_boundary_monitor](../behaviors/common.md#map_boundary_monitor)
- [hardware_health_monitor](../behaviors/common.md#hardware_health_monitor)
- [command_listener](../behaviors/common.md#command_listener)
- [BT_hide_and_seek_sub](BT_hide_and_seek_sub.md) — 6-step Sequence body (move/recruit/countdown/patrol/return/end)
- [BT_goto_sub](BT_goto_sub.md) — move / return step 의 이동 빌딩 블록
- [BT_patrol_sub](BT_patrol_sub.md) — patrol step 의 순찰 빌딩 블록

## 상태

- 코드: ✅ ([BT_hide_and_seek_main.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/trees/main_trees/BT_hide_and_seek_main.py))
- shell helper: [`_shell.py`](../../src/gogoping/gogoping_modes/gogoping_modes/bt/trees/main_trees/_shell.py)
- 의존 behavior: 모두 ✅
- body SubTree: [BT_hide_and_seek_sub](BT_hide_and_seek_sub.md) ✅ (6-step Sequence)
