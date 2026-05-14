# BT_assist_main

ASSIST FSM state 의 MainTree. TaskSelector 로 sub mode (carry / follow / lullaby) 분기 + monitor 분기에서 trigger 수신.

## Root composite

`Parallel (policy: SuccessOnAll, synchronise: false)` — 두 분기 동시 tick.

```
Parallel (BT_assist_main)
├── monitor: Sequence
│   ├── command_listener        # ← return_command / cancel / sub mode 변경
│   ├── battery_low_monitor     # ← battery_low trigger
│   ├── hardware_health_monitor # ← fault trigger
│   └── collision_event_handler # ← fault trigger
└── task: TaskSelector (check_task → BT_*_sub)
    ├── (assist_task=="carry")    → BT_carry_sub
    ├── (assist_task=="follow")   → BT_follow_sub
    └── (assist_task=="lullaby")  → BT_lullaby_sub
```

monitor 가 trigger 발사하면 sub_tree 의 RUNNING 이 INVALID 로 끊기고 (terminate 호출), FSM 이 다른 state 로 transition.

## command_listener 가 받는 trigger (ASSIST 안에서 의미 있는 것)

| 발화 / 명령 | intent kind | FSM trigger | 결과 |
|---|---|---|---|
| "복귀" / "돌아가" / "충전" | sub_command(action=return) | `return_command` | ASSIST → RETURNING (BT_returning_main) |
| "그만" / "정지" / "취소" | sub_command(action=stop) | `cancel` | 현재 sub_tree 종료, ASSIST 유지 (TaskSelector 가 다시 분기) |
| "운반" / "추종" / "자장가" | mode_change(mode=...) | `assist_command` (task 변경) | blackboard.assist_task 갱신 → TaskSelector 다른 sub_tree 선택 |
| "X로 가" (vertex) | goto_vertex(name) | `assist_command(task=carry, carry_mode=goto, target_vertex_name=X)` | carry sub mode 진입 후 [navigate_to_vertex](../behaviors/navigation.md#navigate_to_vertex) 호출 |

다른 state 의 trigger 매트릭스: [BT_idle_main](BT_idle_main.md), [BT_play_main](BT_play_main.md).

FSM transition 정의: [../../fsm-triggers.md](../../fsm-triggers.md).

## 진입 / 종료

- **진입**: IDLE → ASSIST (`assist_command` trigger)
- **종료**:
  - `return_command` → RETURNING
  - `cancel` (전체 종료 의미) → IDLE
  - `battery_low` → RETURNING
  - `fault` → ERROR

## 사용 behavior

| Behavior | 카테고리 | 위치 |
|---|---|---|
| command_listener | common | [behaviors/common.md#command_listener](../behaviors/common.md#command_listener) |
| battery_low_monitor | common | [behaviors/common.md](../behaviors/common.md) |
| hardware_health_monitor | common | [behaviors/common.md](../behaviors/common.md) |
| collision_event_handler | common | [behaviors/common.md](../behaviors/common.md) |
| check_task | common | [behaviors/common.md](../behaviors/common.md) |
| (sub_tree 호출) | — | [BT_carry_sub](BT_carry_sub.md), [BT_follow_sub](BT_follow_sub.md), [BT_lullaby_sub](BT_lullaby_sub.md) |
