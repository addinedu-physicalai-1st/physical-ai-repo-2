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
| `assist_command` | `task: str` (`carry`/`follow`/`lullaby`) | `command_listener` | **IDLE / PLAY / MANUAL → ASSIST** | `blackboard.assist_task = task` 세팅. `carry` 시 `carry_mode` + `destination_key`, `follow` 또는 `carry+follow` 시 `target_person_id` 도 세팅. PLAY/MANUAL 에서 직접 전이 시 BT swap 의 `terminate()` 가 이전 트리 cleanup (MANUAL 의 torque ON 복원 등) |
| `play_command` | `task: str` (`hideseek`) | `command_listener` | **IDLE / ASSIST / MANUAL → PLAY** | `blackboard.play_task = task` 세팅. `hideseek` 시 `target_person_id` + `hide_position_key` + `search_waypoints` + `home_position_key` 도 세팅. 다른 active mode 에서 직접 전이 가능 |
| `manual_command` | — | `command_listener` | **IDLE / ASSIST / PLAY → MANUAL** | torque OFF — 사용자가 직접 밀어서 이동. 진입 시 `release_torque` 서비스 호출, 진출 시 `enable_torque`. 다른 active mode 에서 직접 전이 가능 (이전 트리 cleanup 보장) |
| `return_command` | — | `command_listener` 또는 `main.py._on_tree_failure()` | **IDLE / ASSIST / PLAY / MANUAL → RETURNING** | 수동 복귀 또는 SubTree FAILURE 시 자동 복귀. MANUAL 에서 발화 시 torque ON 자동 |
| `assist_done` | — | (main.py 루프, ASSIST main SUCCESS 감지) | ASSIST → IDLE | `assist_task = ""` 리셋 |
| `play_done` | — | (main.py 루프, PLAY main SUCCESS 감지) | PLAY → IDLE | `play_task = ""` 리셋 |
| `cancel` | — | `command_listener` | ASSIST/PLAY/MANUAL → IDLE | task 키 리셋. MANUAL 에서 발화 시 torque ON 자동 |
| `battery_low` | — | `battery_low_monitor` | IDLE/ASSIST/PLAY → RETURNING (**MANUAL 제외** — 자동 빼앗김 방지) | hysteresis: 50% 진입, 55% 진출 |
| `idle_timeout` | — | `idle_timeout_monitor` (Day 2 TODO) | IDLE → RETURNING | IDLE 진입 시 timer 시작, ROS param `idle_timeout_seconds` 초과 시 발화 — 무인 자율 복귀 |
| `battery_full` | — | `battery_full_monitor` | CHARGING → IDLE | hysteresis: 80% 진입 |
| `docked` | — | `verify_docking_contact` | RETURNING → CHARGING | (발표 단계: 수동 진입) |
| `fault` | `reason: str` | `hardware_health_monitor`, `collision_event_handler`, **`map_boundary_monitor`** (예: `reason="out_of_map"`), 기타 monitor | **CHARGING/IDLE/ASSIST/PLAY/RETURNING → ERROR** (MANUAL 제외 — monitor 미배치) | `blackboard.error_reason = reason` 세팅 |
| `reset` | — | `command_listener` (admin) | ERROR → IDLE | error_reason 클리어, BT 재build |

## 상태 전이 다이어그램

```
   CHARGING ──battery_full──▶ IDLE ◀──── reset ─── ERROR
       ▲                       │ ▲                  ▲
       │ docked                │ │ assist_done      │
       │                       │ │ play_done        │
       │                       │ │ cancel           │ fault
       │                       │ │                  │ (CHARGING/IDLE/ASSIST/
       │                       │ │                  │  PLAY/RETURNING — MANUAL 제외)
       │                       ▼ │                  │
       │             ┌───────────────────────┐      │
       │             │  ASSIST ◀────▶ PLAY   │──────┤
       │             │     ▲            ▲    │      │
       │             │     │            │    │      │
       │             │     └─▶ MANUAL ◀─┘    │      │
       │             └───────────────────────┘      │
       │                       │                    │
       │                       │ ※ active modes 끼리
       │                       │   assist_command / play_command / manual_command
       │                       │   으로 직접 전이 가능 (BT swap 1회)
       │
       │  return_command  (IDLE / ASSIST / PLAY / MANUAL 어디서든 — main.py FAILURE fallback 포함)
       │  battery_low     (IDLE / ASSIST / PLAY — MANUAL 제외)
       │  idle_timeout    (IDLE only — Day 2 TODO)
   RETURNING ◄───────────────────────────────────────
```

> **다중 source 전이**
> - `assist_command` (**IDLE / PLAY / MANUAL → ASSIST**): active mode 간 직접 전이 — BT swap 1회로 처리
> - `play_command` (**IDLE / ASSIST / MANUAL → PLAY**): 동일
> - `manual_command` (**IDLE / ASSIST / PLAY → MANUAL**): 동일. MANUAL 진입 시 `ManualTorqueHold.initialise()` 가 torque OFF
> - `fault` (→ ERROR): CHARGING / IDLE / ASSIST / PLAY / RETURNING. **MANUAL 제외** — monitor 미배치
> - `return_command` (IDLE / ASSIST / PLAY / **MANUAL** → RETURNING): 사용자 명령 또는 SubTree FAILURE fallback
> - `battery_low` (IDLE / ASSIST / PLAY → RETURNING): hysteresis 50% 진입. **MANUAL 제외** — 자동 빼앗김 방지
> - `idle_timeout` (IDLE → RETURNING): IDLE 진입 후 일정 시간 무명령 시 자율 복귀
> - `cancel` (ASSIST / PLAY / **MANUAL** → IDLE): MANUAL 의 정상 종료 경로 (torque 자동 ON)
>
> **active mode 직접 전이의 cleanup 규약** — `*_command` trigger 가 다른 active mode 에서 발화되면 `main.py._on_state_change` 가 이전 트리 `tree.shutdown()` 호출 → 모든 자식의 `terminate(INVALID)` 가 호출됨 → MANUAL 의 ManualTorqueHold 는 torque ON 복원, ASSIST 의 NavigateToPose 는 nav2 goal cancel 등. **BT 의 terminate() 가 idempotent + 시간-구속 cleanup 책임을 보장**해야 안전.
>
> **MANUAL 의 자동 전이 0개** — 모든 monitor 가 의도적으로 미배치. 이탈은 사용자 명령 (cancel / return_command / *_command) 만.

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
