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

## 상태 목록 (10 states)

| 상태 | 분류 | 설명 |
|---|---|---|
| `IDLE` | 대기 | 충전 완료 후 명령 대기 |
| `CHARGING` | 충전 | 도킹 스테이션에서 충전 중 |
| `GOTO` | task | 목적지 vertex 로 이동 |
| `FOLLOW` | task | 특정 사람 추종 |
| `LULLABY` | task | 자장가 오디오 재생 |
| `HIDEANDSEEK` | task | 숨바꼭질 (로봇이 숨고 아이가 찾거나 반대로) |
| `MANUAL` | 수동 | torque OFF — 사용자가 직접 밀어 이동 |
| `RETURNING` | 복귀 | 명령·SubTree FAILURE 후 충전소 복귀 |
| `LOW_BATTERY_RETURNING` | 복귀 | 배터리 부족 긴급 복귀 (lockdown) |
| `ERROR` | terminal | 장애 상태 — 사람이 재시작해야 복구 |

## Trigger 목록 (13 triggers)

| Trigger | kwargs | 발화 주체 | 전이 (from → to) | 동시 작업 |
|---|---|---|---|---|
| `battery_full` | — | `battery_full_monitor` | CHARGING → IDLE | hysteresis: 70% 진입 |
| `goto_request` | — | `command_listener` | IDLE / FOLLOW / LULLABY / HIDEANDSEEK / MANUAL / RETURNING → GOTO | `destination_key` blackboard 세팅. RETURNING 에서 발화 시 BT_return_sub OneShot 의 `terminate()` 가 cmd_vel=0 정리. LOW_BATTERY_RETURNING 은 lockdown 제외 |
| `follow_request` | — | `command_listener` | IDLE / GOTO / LULLABY / HIDEANDSEEK / MANUAL / RETURNING → FOLLOW | `target_person_id` blackboard 세팅. active task 간 직접 전이 (BT swap 1회). LOW_BATTERY_RETURNING 은 lockdown 제외 |
| `lullaby_request` | — | `command_listener` | IDLE / GOTO / FOLLOW / HIDEANDSEEK / MANUAL / RETURNING → LULLABY | active task 간 직접 전이. LOW_BATTERY_RETURNING 은 lockdown 제외 |
| `hideseek_request` | — | `command_listener` | IDLE / GOTO / FOLLOW / LULLABY / MANUAL / RETURNING → HIDEANDSEEK | `target_person_id` + `hide_position_key` + `search_waypoints` + `home_position_key` blackboard 세팅. LOW_BATTERY_RETURNING 은 lockdown 제외 |
| `manual_request` | — | `command_listener` | IDLE / GOTO / FOLLOW / LULLABY / HIDEANDSEEK / RETURNING → MANUAL | torque OFF — 사용자가 직접 밀어서 이동. 진입 시 `release_torque` 서비스 호출, 진출 시 `enable_torque`. RETURNING 포함 (이전 트리 cleanup 보장). LOW_BATTERY_RETURNING 은 lockdown 제외 |
| `return_request` | — | `command_listener` 또는 `main.py._on_tree_failure()` | IDLE / GOTO / FOLLOW / LULLABY / HIDEANDSEEK / MANUAL → RETURNING | 수동 복귀 또는 SubTree FAILURE 시 자동 복귀. MANUAL 에서 발화 시 torque ON 자동 |
| `cancel` | — | `command_listener` | GOTO / FOLLOW / LULLABY / HIDEANDSEEK / MANUAL / RETURNING → IDLE | MANUAL 에서 발화 시 torque ON 자동. RETURNING 에서 발화 시 사용자 "복귀 취소" — BT_return_sub OneShot 의 `terminate()` 가 cmd_vel=0 정리. LOW_BATTERY_RETURNING 은 lockdown 제외 |
| `task_done` | — | `main.py._on_tree_success()` (MainTree root SUCCESS 감지) | GOTO / FOLLOW / LULLABY / HIDEANDSEEK → IDLE | task 완료 후 자연 종료 경로. `main.py` spin 루프가 root SUCCESS 감지 → trigger 발사 |
| `battery_low` | — | `battery_low_monitor` | IDLE / GOTO / FOLLOW / LULLABY / HIDEANDSEEK / RETURNING → LOW_BATTERY_RETURNING (**MANUAL 제외** — 자동 빼앗김 방지) | hysteresis: 20% 진입, 25% 진출 |
| `idle_timeout` | — | `idle_timeout_monitor` | IDLE → RETURNING | IDLE 진입 시 timer 시작, ROS param `idle_timeout_seconds` (기본 60s) 경과 시 발화 — 무인 자율 복귀 |
| `docked` | — | `verify_docking_contact` | RETURNING / LOW_BATTERY_RETURNING → CHARGING | BT_return_sub Sequence 의 마지막 자식이 ReverseIntoDock 완료 직후 자동 발사. 접점 센서 미통합 — 시간 기반 후진 끝났으면 도킹 완료 간주 |
| `fault` | `reason: str` | `hardware_health_monitor`, `collision_event_handler`, `map_boundary_monitor` (예: `reason="out_of_map"`), `command_listener` (`/gogoping/emergency_stop` Trigger srv 수신 시 `reason="user_emergency_stop"`), 기타 monitor | **CHARGING/IDLE/GOTO/FOLLOW/LULLABY/HIDEANDSEEK/MANUAL/RETURNING/LOW_BATTERY_RETURNING → ERROR** (ERROR 만 제외 — terminal). MANUAL 은 MapBoundaryMonitor 만 예외 배치 — 다른 monitor (battery/hw/collision) 는 MANUAL 미배치 정책 유지 | `blackboard.error_reason = reason` 세팅. ERROR 는 terminal — reset trigger 없음. 외부 인입 경로: `/gogoping/emergency_stop` (std_srvs/Trigger) — admin UI e-stop 버튼 / 안전 시스템 |

## 상태 전이 다이어그램

```
                fault (모든 non-ERROR state)
                  ┌────────────────────────────────────────────────▶ ERROR (terminal)
                  │
   CHARGING ──battery_full──▶ IDLE ◀── task_done / cancel
       ▲                       │
       │ docked                │ *_request (IDLE/task/RETURNING → target task)
       │ docked                │ return_request (IDLE/task/MAN → RETURNING)
       │                       │ cancel (RETURNING → IDLE) — 복귀 취소
       │                       │ idle_timeout (IDLE → RETURNING)
       │                       ▼
       │             ┌──────────────────────────────────────┐
       │             │  GOTO  ◀──▶  FOLLOW                  │   ※ task states 끼리
       │             │    ▲            ▲                    │     *_request 로 직접 전이
       │             │    │            │                    │     (BT swap 1회)
       │             │    ▼            ▼                    │
       │             │  LULLABY ◀──▶ HIDEANDSEEK            │
       │             │        ▲   ▲                         │
       │             │        │   └── MANUAL ───────────────┘
       │             └─┬──────────────────────────────────┘
       │               │ return_request / battery_low / cancel
       │               ▼
       │      ┌────────────────┐                ┌──────────────────────┐
       │      │ RETURNING      │── battery_low ─▶ LOW_BATTERY_RETURNING   │
       │      │ (CMD listen)   │   (escalation)  │ (lockdown — CMD 차단)│
       │      └─┬──────────────┘                └─┬────────────────────┘
       │        │ docked                          │ docked
       └────────┴──────────────────────────────────┘
```

> **다중 source 전이**
> - `goto_request` (**IDLE / FOLLOW / LULLABY / HIDEANDSEEK / MANUAL / RETURNING → GOTO**): task 간 직접 전이 + RETURNING 도중 사용자가 마음 바꿔 GOTO 명령 — BT swap 1회로 처리. LOW_BATTERY_RETURNING 은 lockdown 제외
> - `follow_request` / `lullaby_request` / `hideseek_request`: 동일 (각 task state 가 source, 해당 state 가 dest)
> - `manual_request` (**IDLE / GOTO / FOLLOW / LULLABY / HIDEANDSEEK / RETURNING → MANUAL**): 동일. MANUAL 진입 시 `ManualTorqueHold.initialise()` 가 torque OFF
> - `fault` (→ ERROR): CHARGING / IDLE / GOTO / FOLLOW / LULLABY / HIDEANDSEEK / MANUAL / RETURNING / LOW_BATTERY_RETURNING. MANUAL 도 포함 — MapBoundaryMonitor 만 예외적 배치 (사용자가 맵 밖으로 옮기면 nav2 복귀 불가 → ERROR 알림)
> - `return_request` (IDLE / GOTO / FOLLOW / LULLABY / HIDEANDSEEK / **MANUAL** → RETURNING): 사용자 명령 또는 SubTree FAILURE fallback
> - `battery_low` (IDLE / GOTO / FOLLOW / LULLABY / HIDEANDSEEK / RETURNING → LOW_BATTERY_RETURNING): hysteresis 20% 진입. **MANUAL 제외** — 자동 빼앗김 방지
> - `idle_timeout` (IDLE → RETURNING): IDLE 진입 후 일정 시간 무명령 시 자율 복귀
> - `cancel` (GOTO / FOLLOW / LULLABY / HIDEANDSEEK / MANUAL / **RETURNING** → IDLE): MANUAL 의 정상 종료 경로 (torque 자동 ON). RETURNING 에서 발화 시 사용자 "복귀 취소" — BT_return_sub OneShot 의 `terminate()` 가 cmd_vel=0 정리
> - `task_done` (GOTO / FOLLOW / LULLABY / HIDEANDSEEK → IDLE): MainTree root SUCCESS → `main.py._on_tree_success()` 감지 후 발사
> - `docked` (RETURNING / LOW_BATTERY_RETURNING → CHARGING): BT_return_sub Sequence 의 마지막 자식 `VerifyDockingContact` 가 ReverseIntoDock 완료 직후 자동 발사
>
> **task state 직접 전이의 cleanup 규약** — `*_request` trigger 가 다른 task state 에서 발화되면 `main.py._on_state_change` 가 이전 트리 `tree.shutdown()` 호출 → 모든 자식의 `terminate(INVALID)` 가 호출됨 → MANUAL 의 ManualTorqueHold 는 torque ON 복원, GOTO/FOLLOW 의 NavigateToPose/NavigateToVertex 는 nav2 goal cancel 등. **BT 의 terminate() 가 idempotent + 시간-구속 cleanup 책임을 보장**해야 안전.
>
> **MANUAL 의 자동 전이 0개** — 모든 monitor 가 의도적으로 미배치. 이탈은 사용자 명령 (cancel / return_request / *_request) 만.
>
> **ERROR 는 terminal** — 어떤 trigger 도 받지 않음. 사람이 robot 재시작해야 복구.
>
> **LOW_BATTERY_RETURNING 도 lockdown** — 사용자 명령 차단. battery_low 로만 진입 가능. 이탈은 docked / fault 만.

## 호출 컨벤션

```python
# behavior 내부에서
self.context.fsm.trigger("battery_low")
self.context.fsm.trigger("fault", reason="lidar_timeout")
self.context.fsm.trigger("goto_request")
```

- `fsm.trigger()` 는 **idempotent** — 현재 state 에서 invalid trigger 면 무시 (transitions 라이브러리 표준)
- behavior 가 같은 trigger 를 매 tick 호출해도 안전. 그러나 **불필요한 호출은 피한다** — monitor 는 edge-triggered 권장 (직전 값과 비교)
- trigger 발화 후 behavior 는 **RUNNING 리턴 유지** — 트리 강제 종료는 main.py 의 BT swap 루프가 담당
- 자세한 monitor 컨벤션: [state-bt.md](state-bt.md) 머리말 참조

## 디버그 — `fsm.force_state(target_state)`

transition 우회 강제 전이. **디버그 / 데모 전용**.

```python
fsm.force_state("GOTO")          # CHARGING / ERROR / 어디서든 → GOTO 즉시
```

내부 동작:

1. `machine.set_state(target)` — transitions 라이브러리의 비공식 API. before/after 콜백 미발화.
2. 수동으로 `_after_state_change()` 호출 — main.py 의 BT swap hook 발화. 트리 교체 정상.

진입점:

- Admin UI 의 **DebugStatePanel** (BTStateInline 옆) — state combo + 적용 버튼.
- POST `/api/gogoping/debug/force-state` → Control Service `GogopingRosBridge.force_state_sync` → `gogoping_msgs/srv/ForceState` 호출.
- ROS srv 직접 호출도 가능 — `ros2 service call /gogoping/force_state gogoping_msgs/srv/ForceState "{target_state: 'GOTO'}"`.

ForceState.srv 는 `target_state` 단일 필드 — 10 state 이름 중 하나 (`IDLE` / `CHARGING` / `GOTO` / `FOLLOW` / `LULLABY` / `HIDEANDSEEK` / `MANUAL` / `RETURNING` / `LOW_BATTERY_RETURNING` / `ERROR`).

운영 (`SetGoal.srv`) 과의 차이 — force_state 는 reconciler 우회. ERROR/LOW_BATTERY_RETURNING lockdown 도 무시. 따라서 운영 코드 / UI 운영 경로에서는 호출 금지, 디버그 패널에서만 사용.

## 변경 이력

- **2026-05-25** — 평탄화 리팩터링 (Task 1~15). ASSIST/PLAY + TaskSelector 제거. 10 states / 13 triggers 체계로 전환.
  - ASSIST(goto/follow/lullaby) → GOTO / FOLLOW / LULLABY 각각 독립 state
  - PLAY(hideseek) → HIDEANDSEEK 독립 state
  - `assist_request` / `play_request` → `goto_request` / `follow_request` / `lullaby_request` / `hideseek_request` (4개로 분리)
  - `assist_done` / `play_done` → `task_done` (단일 trigger — 4 task state 공통)
  - `ForceState.srv` 에서 `sub_task` 필드 제거 (target_state 단일 필드)
  - `Goal.msg` 에서 `mode` + `task` → `target_state` (단일 필드)
  - blackboard `ASSIST_TASK` / `PLAY_TASK` 키 제거
- **이전** — 8 states (CHARGING / IDLE / ASSIST / PLAY / MANUAL / RETURNING / LOW_BATTERY_RETURNING / ERROR) / 12 triggers
