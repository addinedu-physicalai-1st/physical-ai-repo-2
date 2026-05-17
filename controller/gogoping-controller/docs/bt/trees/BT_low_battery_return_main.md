# BT_low_battery_return_main

`LOW_BATTERY_RETURN` state 의 MainTree — 배터리 임계치 이하로 자동 진입한 **lockdown** 복귀.

## Root composite (현재 walking skeleton)

```
Parallel(SuccessOnAll(synchronise=False))
└─ (자식 0개 — idle)
```

> 현재는 **빈 Parallel**. 사용자 명령 차단 + 진짜 ReturnSubTree 미작성 이라 어떤 자식도 등록되지 않음. main.py 의 spin 이 매 tick 호출하나 노드가 없어 사실상 idle 대기. 외부 (`BatterySubscriber`) 가 `docked` trigger 를 발화하면 `main.py._on_state_change` 가 BT 를 BT_charging_main 으로 swap.

## RETURNING 과의 차이

| 항목 | RETURNING (사용자 명시 / idle_timeout) | LOW_BATTERY_RETURN (battery_low 자동) |
|---|---|---|
| 진입 trigger | `return_request` / `idle_timeout` | `battery_low` |
| 진입 source | IDLE / ASSIST / PLAY / MANUAL | IDLE / ASSIST / PLAY / **RETURNING** (RETURNING 도중에도 배터리 떨어지면 escalation) |
| `CommandListener` | ✅ 배치 — 사용자 cancel 가능 | ❌ **없음** — 사용자 명령 차단 (lockdown) |
| HardwareHealthMonitor | (추후) | (추후) — 동일 |
| CollisionEventHandler | (추후) | (추후) — 동일 |
| MapBoundaryMonitor | (추후) | (추후) — 동일 |
| ReturnSubTree | (추후) | (추후) — 동일 |
| 이탈 경로 | `cancel` / 사용자 *_request / `docked` / `fault` | `docked` / `fault` 만 |

## 사용자 명령 차단 메커니즘

CommandListener 가 없으니 `SetGoal.srv` 호출 자체가 받을 server 없음 → ROS 측에서 timeout. 추가로 안전망:

- `utils/goal_reconciler.py` 가 `current_state == "LOW_BATTERY_RETURN"` 이면 `accepted=False`, `reason="fsm_in_low_battery_return"` 으로 거부 (control-service 가 이 reason 받으면 UI 에 토스트 표시).
- `force_state` debug 는 별도 — admin 의 DebugStatePanel 에서 직접 `LOW_BATTERY_RETURN → IDLE` 등 강제 전이 가능 (개발 디버그 용도).

## FSM trigger

### 진입
| Trigger | From | Source 발화 주체 |
|---|---|---|
| `battery_low` | IDLE / ASSIST / PLAY / RETURNING | `battery_low_monitor` (추후) |

### 종료
| Trigger | To | Source 발화 주체 |
|---|---|---|
| `docked` | CHARGING | `verify_docking_contact` (추후) — ReturnSubTree 마지막 노드 |
| `fault` | ERROR | `hardware_health_monitor` / `collision_event_handler` 등 |

> 의도적으로 `cancel` / `*_request` source 에서 **제외**. ERROR 와 동일한 lockdown 정책.

## 상태

- 코드: ✅ ([BT_low_battery_return_main.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/trees/main_trees/BT_low_battery_return_main.py)) — 빈 Parallel
- 의존 behavior: 0 (현재) — 추후 HardwareHealthMonitor, CollisionEventHandler, MapBoundaryMonitor, ReturnSubTree
