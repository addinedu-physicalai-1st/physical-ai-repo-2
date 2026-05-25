# BT_low_battery_returning_main

`LOW_BATTERY_RETURNING` state 의 MainTree — 배터리 임계치 이하로 자동 진입한 **lockdown** 복귀.

## Root composite

```
Parallel(SuccessOnAll(synchronise=False))
├─ MapBoundaryMonitor       common/map_boundary_monitor.md     (✅)
├─ HardwareHealthMonitor    common/hardware_health_monitor.md  (✅)  ← LIDAR/odom staleness
└─ ReturnSubTree            sub_trees/BT_return_sub.md         (✅)  ← OneShot(NavTo → Align → Reverse)
```

> 안전 monitor + 복귀 SubTree. 사용자 명령 차단 (CommandListener 없음). `docked` trigger 가 외부에서 발화 (사람의 admin UI 디버그 버튼) 되거나 `MapBoundaryMonitor`/`HardwareHealthMonitor` 가 fault 발화하면 다른 state 로 전이.

## RETURNING 과의 차이

| 항목 | RETURNING (사용자 명시 / idle_timeout) | LOW_BATTERY_RETURNING (battery_low 자동) |
|---|---|---|
| 진입 trigger | `return_request` / `idle_timeout` | `battery_low` |
| 진입 source | IDLE / GOTO / FOLLOW / LULLABY / HIDEANDSEEK / MANUAL | IDLE / GOTO / FOLLOW / LULLABY / HIDEANDSEEK / **RETURNING** (RETURNING 도중에도 배터리 떨어지면 escalation) |
| `CommandListener` | ✅ 배치 — 사용자 cancel 가능 | ❌ **없음** — 사용자 명령 차단 (lockdown) |
| HardwareHealthMonitor | ✅ | ✅ — 동일 |
| CollisionEventHandler | (추후) | (추후) — 동일 |
| MapBoundaryMonitor | ✅ | ✅ — 동일 |
| ReturnSubTree | ✅ | ✅ — 동일 |
| 이탈 경로 | `cancel` / 사용자 *_request / `docked` / `fault` | `docked` / `fault` 만 |

## Lockdown 정책 — "사용자 명령만 차단, 안전 monitor 는 정상 동작"

CommandListener 가 없으니 `SetGoal.srv` 호출 자체가 받을 server 없음 → ROS 측에서 timeout. 추가로 안전망:

- `utils/goal_reconciler.py` 가 `current_state == "LOW_BATTERY_RETURNING"` 이면 `accepted=False`, `reason="fsm_in_low_battery_returning"` 으로 거부 (control-service 가 이 reason 받으면 UI 에 토스트 표시).
- `force_state` debug 는 별도 — admin 의 DebugStatePanel 에서 직접 `LOW_BATTERY_RETURNING → IDLE` 등 강제 전이 가능 (개발 디버그 용도).

**안전 monitor 는 정상 배치** — `MapBoundaryMonitor` (✅), `HardwareHealthMonitor` (✅), CollisionEventHandler (추후). 사용자 명령은 차단하되 자율 fault 감지는 유지 (안전 > UX). 따라서 `fault` trigger 도 LOW_BATTERY_RETURNING 의 유효 이탈 경로.

## FSM trigger

### 진입
| Trigger | From | Source 발화 주체 |
|---|---|---|
| `battery_low` | IDLE / GOTO / FOLLOW / LULLABY / HIDEANDSEEK / RETURNING | `battery_low_monitor` |

### 종료
| Trigger | To | Source 발화 주체 |
|---|---|---|
| `docked` | CHARGING | **사람** (admin UI 디버그 버튼) — 자동 도킹 (`verify_docking_contact`) 은 발표 범위 외 |
| `fault` | ERROR | `hardware_health_monitor` / `collision_event_handler` 등 |

> 의도적으로 `cancel` / `*_request` source 에서 **제외**. ERROR 와 동일한 lockdown 정책.

## 상태

- 코드: ✅ ([BT_low_battery_returning_main.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/trees/main_trees/BT_low_battery_returning_main.py)) — `MapBoundaryMonitor` + `HardwareHealthMonitor` + `ReturnSubTree` 배치
- 의존 behavior: `MapBoundaryMonitor` (✅), `HardwareHealthMonitor` (✅), `BT_return_sub` (✅) — 추후 CollisionEventHandler
