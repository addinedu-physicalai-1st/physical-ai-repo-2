# BT_manual_main

`MANUAL` state 의 MainTree — 사용자가 로봇 본체를 직접 밀어서 이동할 수 있도록
모터 torque 를 해제한 상태에서 안전 모니터링만 수행.

## Root composite (현재 walking skeleton)

```
Parallel(SuccessOnAll(synchronise=False))
└─ CommandListener          common/command_listener.md     ※ cancel / *_request / return_request 만 유효
```

> 현재는 `CommandListener` 단독. `ManualTorqueHold` 는 추후 — Vic Pinky base driver 의 torque service spec 확정 후 추가. 추후 모양:
>
> ```
> Parallel(SuccessOnAll(synchronise=False))
> ├─ ManualTorqueHold      (추후 — initialise 에서 torque OFF, terminate 에서 ON 복원)
> └─ CommandListener       (✅ 현재)
> ```
>
> Parallel 정책은 `BT_idle_main` 과 동일 — root SUCCESS 는 task 완료 의미가 아님.
> state 전이는 trigger 발화 (`cancel` / `return_request` / 다른 `*_request`) 만 담당.
> sub tree 없음.

### 의도적으로 *빠진* monitor 3개

다른 active state 와 달리 본 트리는 **모든 자동 감지 monitor 미배치**. 이유:

| 빠진 항목 | 이유 |
|---|---|
| `BatteryLowMonitor` | 사용자가 로봇을 손에 잡고 있는 상태에서 자동 RETURNING 으로 빠져나가면 UX 위험. battery 상태는 admin UI 의 BTStateInline 옆 chip 으로 visual 만 표시 |
| `HardwareHealthMonitor` | torque OFF 라 모터 fault 의미 약함. 굳이 ERROR 로 강제 전이할 필요 없음 |
| `CollisionEventHandler` | torque OFF 라 자율 충돌 위험 없음. 사용자가 충돌 회피 책임 |

따라서 MANUAL 에서 다른 state 로의 *자동* 전이는 0개. 이탈 경로는 오직 **사용자 명시 명령** (`cancel` → IDLE / `return_request` → RETURNING) 만.

> FSM 의 `fault` source 에서도 MANUAL 이 제외되어 있음 (`robot_fsm.py:_FAULT_SOURCES`).
> spec / 코드 일치 — 발화 주체 없는 trigger 는 valid source 에서도 제외.

## Behaviors

| Behavior | 책임 | 상세 |
|---|---|---|
| **`ManualTorqueHold`** (추후) | `initialise()` 에서 torque OFF service 호출, `terminate()` 에서 torque ON 복원. 매 tick RUNNING 유지 — 트리 살아있는 동안 torque off 상태 유지 | manual/manual_torque_hold.md |
| `CommandListener` (✅) | UI / Control Server 명령 수신 | MANUAL 에서는 `cancel` / `return_request` / 다른 active mode 로의 `*_request` 가 valid |

### `ManualTorqueHold` 의 lifecycle 규약

- `initialise()`:  Vic Pinky base driver 의 `release_torque` service 호출 (또는 동등 명령). 성공 시 blackboard 에 `manual_torque_active=True` 표기.
- `update()`: 항상 `Status.RUNNING` 리턴 (다른 monitor 와 동일). torque service 의 health 도 체크 가능 — 끊겼으면 `fault` 발화.
- `terminate(new_status)`: **idempotent** torque ON 복원 (`enable_torque` service). new_status 에 관계없이 무조건 호출. blackboard 의 `manual_torque_active=False`.

> **왜 별도 behavior 인가** — torque 제어는 *시간-구속* (반드시 cleanup 보장 필요). `MANUAL` state 의 trigger 가 무엇이든 (cancel / battery_low / fault / return_request) py_trees 의 `terminate()` 가 호출되어 torque 복원 보장.

## 진입 / 종료 trigger

### 진입
| Trigger | From | Source 발화 주체 |
|---|---|---|
| `manual_request` | IDLE | `command_listener` (SetGoal mode="MANUAL" 받음) |

### 종료
| Trigger | To | Source 발화 주체 |
|---|---|---|
| `cancel` | IDLE | `command_listener` (SetGoal mode="IDLE" 받음) |
| `return_request` | RETURNING | `command_listener` (SetGoal mode="RETURNING") |

> **자동 종료 trigger 0개.** battery_low / fault 모두 MANUAL source 에서 제외되어 있음.
> 사용자가 admin UI 의 battery chip 보고 직접 `cancel` 또는 `return_request` 발행해야 함.

종료 trigger 시 `main.py._on_state_change` 가 트리 swap → `ManualTorqueHold.terminate()` 호출 → torque ON 복원.

## 안전 관련 주의

1. `ManualTorqueHold.terminate()` 가 호출되지 않을 경우 torque 가 풀린 채로 다른 state 에 진입할 수 있다.
   `tree.shutdown()` 시 py_trees 가 모든 RUNNING 자식의 terminate 를 호출하는지 `py-trees-spike.md` Test 3 로 검증 후 운영.
2. MANUAL 상태에서 로봇이 *물리적으로* 위험한 곳에 있을 수 있음 (계단 근처 등) — `CollisionEventHandler` 가 nav2 collision monitor 의 keep-out zone 체크 유지.
3. `battery_low` 진입 시 torque 가 자동 복원되어 도크로 자율 주행 — 사용자가 로봇을 들고 있는 상태였다면 *놓아야* 안전.
   → admin UI 의 BTStateInline 이 MANUAL 알약 표시 시 "battery 20% 미만이면 자동 복귀합니다" 안내 문구 권장.

## 상태

- 코드: ✅ ([BT_manual_main.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/trees/main_trees/BT_manual_main.py)) — `CommandListener` 만 배치된 walking skeleton
- 의존 behavior: `CommandListener` (✅). `ManualTorqueHold` 는 추후 — torque service spec 확정 후
- 자세한 신규 behavior 명세: [`bt/behaviors/manual.md`](../behaviors/manual.md) 의 `manual_torque_hold` 항목 (추후)
