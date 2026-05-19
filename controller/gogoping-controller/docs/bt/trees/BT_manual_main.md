# BT_manual_main

`MANUAL` state 의 MainTree — 사용자가 로봇 본체를 직접 밀어서 이동할 수 있도록
모터 torque 를 해제한 상태에서 안전 모니터링만 수행.

## Root composite

```
Parallel(SuccessOnAll(synchronise=False))
├─ ManualTorqueHold         manual/manual_torque_hold.md   (✅ torque OFF/ON 라이프사이클)
├─ MapBoundaryMonitor       common/map_boundary_monitor.md  (✅ 위치 안전 예외)
└─ CommandListener          common/command_listener.md       (✅ cancel / *_request / return_request)
```

Parallel 정책은 `BT_idle_main` 과 동일 — root SUCCESS 는 task 완료 의미가 아님.
state 전이:
- 사용자 명령: `cancel` / `return_request` / 다른 `*_request`
- 자동 fault: `MapBoundaryMonitor` 발화 (`fault(reason="out_of_map")` → ERROR)

sub tree 없음.

### Monitor 배치 정책 — "위치 안전만 예외"

대부분의 monitor 는 MANUAL 에 배치하지 않음. 단 `MapBoundaryMonitor` 만 예외:

| 항목 | 배치? | 이유 |
|---|---|---|
| `BatteryLowMonitor` | ❌ 제외 | 사용자가 로봇을 손에 잡고 있는 상태에서 자동 RETURNING 으로 빠져나가면 UX 위험. battery 상태는 admin UI 의 BTStateInline 옆 chip 으로 visual 만 표시 |
| `HardwareHealthMonitor` | ❌ 제외 | torque OFF 라 모터 fault 의미 약함. 굳이 ERROR 로 강제 전이할 필요 없음 |
| `CollisionEventHandler` | ❌ 제외 | torque OFF 라 자율 충돌 위험 없음. 사용자가 충돌 회피 책임 |
| **`MapBoundaryMonitor`** | **✅ 배치** | 사용자가 들고 옮기다 맵 경계 넘으면 nav2 가 path planning 불가 → return 명령 불가. 즉시 ERROR 알려야 사용자가 도로 옮길 수 있음 |

따라서 MANUAL 에서 다른 state 로의 *자동* 전이는 1개 (out_of_map fault → ERROR). 그 외 이탈은 **사용자 명시 명령** (`cancel` → IDLE / `return_request` → RETURNING / 다른 `*_request`) 만.

> FSM 의 `fault` source 에 MANUAL 포함됨 (`robot_fsm.py:_FAULT_SOURCES`) — MapBoundaryMonitor 발화 위해.

## Behaviors

| Behavior | 책임 | 상세 |
|---|---|---|
| **`ManualTorqueHold`** (✅) | `initialise()` 에서 torque OFF service 호출 (`/gogoping/set_torque` data=False), `terminate()` 에서 torque ON 복원. 매 tick RUNNING. blackboard `MANUAL_TORQUE_ACTIVE` W | [manual/manual_torque_hold](../behaviors/manual.md#manual_torque_hold) |
| `MapBoundaryMonitor` (✅) | 로봇 pose 가 맵 영역 밖이면 `fault(reason="out_of_map")` 발화 → ERROR | [common/map_boundary_monitor.md](../behaviors/common.md#map_boundary_monitor) |
| `CommandListener` (✅) | UI / Control Server 명령 수신 | MANUAL 에서는 `cancel` / `return_request` / 다른 active mode 로의 `*_request` 가 valid |

### `ManualTorqueHold` 의 lifecycle 규약

- `initialise()`: `ctx.base_driver.release_torque()` 호출 → `/gogoping/set_torque` (SetBool, data=False) → `vicpinky_bringup` 이 `zlac_driver.disable()` 실행. blackboard 의 `MANUAL_TORQUE_ACTIVE=True` 표기.
- `update()`: 항상 `Status.RUNNING` 리턴 (다른 monitor 와 동일).
- `terminate(new_status)`: **idempotent** `enable_torque()` 호출 (driver enable 복원). `new_status` 무관 무조건 호출. blackboard 의 `MANUAL_TORQUE_ACTIVE=False`.

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
| `fault` | ERROR | `MapBoundaryMonitor` (out_of_map) ※ 자동 |

> 자동 종료 trigger 1개 (out_of_map). battery_low 는 MANUAL source 에서 제외되어 있어 발화 안 됨.
> 사용자가 admin UI 의 battery chip 보고 직접 `cancel` 또는 `return_request` 발행해야 함.

종료 trigger 시 `main.py._on_state_change` 가 트리 swap → `ManualTorqueHold.terminate()` 호출 → torque ON 복원.

## 안전 관련 주의

1. `main.py:_build_tree_for_state` 가 state 전이 시 `tree.shutdown()` 명시 호출 → py_trees 가 RUNNING 자식의 `terminate()` 전파 → `ManualTorqueHold.terminate()` 가 호출되어 enable 복원. (참고: `py-trees-spike.md` Test 3 정식 검증은 미실시지만 명시 호출로 안전망 확보.)
2. MANUAL 상태에서 로봇이 *물리적으로* 위험한 곳에 있을 수 있음 (계단 근처 등) — `CollisionEventHandler` 가 nav2 collision monitor 의 keep-out zone 체크 유지.
3. battery_low 는 MANUAL 에서 자동 trigger 안 됨 — 사용자가 admin UI 보고 직접 `cancel` / `return_request` 해야 함.

## 상태

- 코드: ✅ ([BT_manual_main.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/trees/main_trees/BT_manual_main.py))
- 의존 behavior: `ManualTorqueHold` (✅) + `MapBoundaryMonitor` (✅) + `CommandListener` (✅)
- 자세한 신규 behavior 명세: [`bt/behaviors/manual.md`](../behaviors/manual.md) 의 `manual_torque_hold` 항목
