# BT_play_main

`PLAY` state 의 MainTree — 아이와의 놀이 (현재 hideseek 만). TaskSelector 분기.

## Root composite

```
Parallel(SuccessOnSelected=[TaskSelector])
├─ BatteryLowMonitor        common/battery_low_monitor.md        (✅ ≤20% → battery_low → RETURNING)
├─ MapBoundaryMonitor       common/map_boundary_monitor.md       (✅ 맵 밖 → fault → ERROR)
├─ HardwareHealthMonitor    common/hardware_health_monitor.md    (✅ LIDAR/odom staleness → fault)
├─ CommandListener          common/command_listener.md           (✅ cancel / 다른 active mode 전이)
│
└─ TaskSelector (Selector, memory=False)
      └─ Sequence(hideseek_branch, memory=True)
            ├─ CheckTask(play_task=="hideseek")    (✅)
            └─ build_hide_and_seek_sub(ctx)         (✅ patrol-only — BT_hide_and_seek_sub.md)
```

추후 추가 예정: `CollisionEventHandler` (현재 ☐).
진짜 hideseek (인식/FOUND) 확장: ☐ — `BT_hide_and_seek_sub` 안에서.

### TaskSelector 정책

- `Selector(memory=False)` — 매 tick `play_task` 재평가. 사용자가 mode 변경 시 즉시 다른 branch 진입.
- 현재 PLAY 안엔 hideseek 하나뿐이지만 향후 task 추가 시 동일 패턴으로 branch 추가.

### Parallel 정책 — SuccessOnSelected=[TaskSelector]

TaskSelector 가 SUCCESS 면 BT_play_main root 도 SUCCESS → `main.py._on_tree_success` 가
`play_done` trigger 발화 → PLAY → IDLE. monitor 들은 SUCCESS 안 함 (monitor 컨벤션:
항상 RUNNING). 따라서 TaskSelector 만이 task 완료 신호.

## 진입 / 종료 trigger

### 진입
| Trigger | From | Source |
|---|---|---|
| `play_request` | IDLE / ASSIST / MANUAL / RETURNING | `command_listener` (SetGoal mode="PLAY", task=hideseek) |

### 종료
| Trigger | To | Source |
|---|---|---|
| `play_done` | IDLE | `main.py._on_tree_success()` (root SUCCESS 감지) |
| `cancel` | IDLE | `command_listener` (SetGoal mode="IDLE") |
| `assist_request` | ASSIST | `command_listener` (PLAY → ASSIST 직접 전이) |
| `manual_request` | MANUAL | `command_listener` (PLAY → MANUAL 직접 전이) |
| `return_request` | RETURNING | `command_listener` 또는 `main.py._on_tree_failure()` (root FAILURE 시) |
| `battery_low` | LOW_BATTERY_RETURN | `battery_low_monitor` |
| `fault` | ERROR | `map_boundary_monitor` / `hardware_health_monitor` |

## hideseek task 의 blackboard 준비

`command_listener` 가 `play_request(task="hideseek")` 발화 직전 다음 키 세팅
([blackboard-schema.md](../../blackboard-schema.md)):

- `play_task = "hideseek"`
- `target_person_id` — ReID / face_id (놀이 상대 아이)
- `hide_position_key` — 숨을 위치 (named_pose)
- `search_waypoints` — 탐색 waypoint 리스트 (control-server `/waypoints/patrol/hide_and_seek_search` 에서 가져옴)
- `home_position_key` — 원위치

## 사용 behavior

- [battery_low_monitor](../behaviors/common.md#battery_low_monitor)
- [map_boundary_monitor](../behaviors/common.md#map_boundary_monitor)
- [hardware_health_monitor](../behaviors/common.md#hardware_health_monitor)
- [command_listener](../behaviors/common.md#command_listener)
- [check_task](../behaviors/common.md#check_task) — Selector 분기용
- (sub_tree 호출) → [BT_hide_and_seek_sub](BT_hide_and_seek_sub.md) (patrol-only)

## 상태

- 코드: ✅ ([BT_play_main.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/trees/main_trees/BT_play_main.py))
- 의존 behavior: BatteryLow / MapBoundary / HardwareHealth / CommandListener / CheckTask 모두 ✅
- SubTree: [BT_hide_and_seek_sub](BT_hide_and_seek_sub.md) ✅ (patrol-only — 진짜 hideseek 확장은 ☐)
