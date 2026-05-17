# FSM Triggers

`robot_fsm.py` 의 transition 트리거 명세.

> **본 trigger 표는 internal API.** (2026-05-17 결정)
>
> UI / Control Server 는 trigger 를 직접 발화하지 않고 `gogoping_msgs/srv/SetGoal.srv`
> 로 *goal* 만 변경한다. `bt/behaviors/common/command_listener.py` 가 SetGoal 을 받아
> 현재 state ↔ goal 차이를 보고 본 표의 적절한 trigger 를 *자체* 발화하는 reconciler 패턴.
>
> 따라서 본 trigger 이름은 외부에 노출되지 않으며 자유롭게 리팩터링 가능.
> 외부 인터페이스 변경은 `Goal.msg` / `GoalStatus.msg` / `SetGoal.srv` 의 spec 변경 시에만.

내부 호출 주체: BT monitor 노드 (`battery_low_monitor` / `hardware_health_monitor` /
`collision_event_handler` 등), `command_listener` (goal reconciler), `main.py._on_tree_failure`.

## Trigger 목록

| Trigger | kwargs | 발화 주체 | 전이 (from → to) | 동시 작업 |
|---|---|---|---|---|
| `assist_command` | `task: str` (`carry`/`follow`/`lullaby`) | `command_listener` | IDLE → ASSIST | `blackboard.assist_task = task` 세팅. `carry` 시 `carry_mode` + `destination_key`, `follow` 또는 `carry+follow` 시 `target_person_id` 도 세팅 |
| `play_command` | `task: str` (`hideseek`) | `command_listener` | IDLE → PLAY | `blackboard.play_task = task` 세팅. `hideseek` 시 `target_person_id` + `hide_position_key` + `search_waypoints` + `home_position_key` 도 세팅 |
| `return_command` | — | `command_listener` 또는 `main.py._on_tree_failure()` | **IDLE / ASSIST / PLAY → RETURNING** | 수동 복귀 또는 SubTree FAILURE 시 자동 복귀 |
| `assist_done` | — | (main.py 루프, ASSIST main SUCCESS 감지) | ASSIST → IDLE | `assist_task = ""` 리셋 |
| `play_done` | — | (main.py 루프, PLAY main SUCCESS 감지) | PLAY → IDLE | `play_task = ""` 리셋 |
| `cancel` | — | `command_listener` | ASSIST/PLAY → IDLE | task 키 리셋 |
| `battery_low` | — | `battery_low_monitor` | IDLE/ASSIST/PLAY → RETURNING | hysteresis: 50% 진입, 55% 진출 |
| `idle_timeout` | — | `idle_timeout_monitor` (Day 2 TODO) | IDLE → RETURNING | IDLE 진입 시 timer 시작, ROS param `idle_timeout_seconds` 초과 시 발화 — 무인 자율 복귀 |
| `battery_full` | — | `battery_full_monitor` | CHARGING → IDLE | hysteresis: 80% 진입 |
| `docked` | — | `verify_docking_contact` | RETURNING → CHARGING | (발표 단계: 수동 진입) |
| `fault` | `reason: str` | `hardware_health_monitor`, `collision_event_handler`, 기타 monitor | any → ERROR | `blackboard.error_reason = reason` 세팅 |
| `reset` | — | `command_listener` (admin) | ERROR → IDLE | error_reason 클리어, BT 재build |

## 상태 전이 다이어그램

```
   CHARGING ──battery_full──▶ IDLE ◀──── reset ─── ERROR
       ▲                       │                    ▲
       │ docked                │ assist_command     │
       │                       │ play_command       │ fault
       │                       ▼                    │ (모든 active state)
       │                  ASSIST / PLAY ────────────┤
       │                       │
       │                       │ assist_done / play_done / cancel
       │                       ▼
       │                     IDLE
       │
       │  return_command  (IDLE / ASSIST / PLAY 어디서든 — main.py FAILURE fallback 포함)
       │  battery_low     (IDLE / ASSIST / PLAY)
       │  idle_timeout    (IDLE only — Day 2 TODO)
   RETURNING ◄───────────────────────────────────────
```

> **다중 source 전이**
> - `fault` (any active → ERROR): CHARGING / IDLE / ASSIST / PLAY / RETURNING 어디서든
> - `return_command` (IDLE / ASSIST / PLAY → RETURNING): 사용자 명령 또는 SubTree FAILURE fallback
> - `battery_low` (IDLE / ASSIST / PLAY → RETURNING): hysteresis 50% 진입
> - `idle_timeout` (IDLE → RETURNING): IDLE 진입 후 일정 시간 무명령 시 자율 복귀

## 호출 컨벤션

```python
# behavior 내부에서
self.context.fsm.trigger("battery_low")
self.context.fsm.trigger("fault", reason="lidar_timeout")
self.context.fsm.trigger("assist_command", task="carry")
```

- `fsm.trigger()` 는 **idempotent** — 현재 state 에서 invalid trigger 면 무시 (transitions 라이브러리 표준)
- behavior 가 같은 trigger 를 매 tick 호출해도 안전. 그러나 **불필요한 호출은 피한다** — monitor 는 edge-triggered 권장 (직전 값과 비교)
- trigger 발화 후 behavior 는 **RUNNING 리턴 유지** — 트리 강제 종료는 main.py 의 BT swap 루프가 담당
- 자세한 monitor 컨벤션: [state-bt.md](state-bt.md) 머리말 참조
