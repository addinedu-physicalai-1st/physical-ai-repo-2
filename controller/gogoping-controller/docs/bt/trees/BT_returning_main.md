# BT_returning_main

`RETURNING` state 의 MainTree — 사용자 명령 또는 `idle_timeout` 으로 자율 도크 복귀 중.

## Root composite

```
Parallel(SuccessOnAll(synchronise=False))
├─ BatteryLowMonitor        common/battery_low_monitor.md     (✅)  ← escalation: → LOW_BATTERY_RETURNING
├─ MapBoundaryMonitor       common/map_boundary_monitor.md    (✅)
├─ HardwareHealthMonitor    common/hardware_health_monitor.md (✅)  ← LIDAR/odom staleness
├─ CommandListener          common/command_listener.md        (✅)
└─ ReturnSubTree            sub_trees/BT_return_sub.md        (✅)  ← OneShot(NavTo → Align → Reverse)
```

`BatteryLowMonitor` 가 RETURNING 중에도 배터리 더 떨어지면 `battery_low` trigger → LOW_BATTERY_RETURNING 로 escalation. `ReturnSubTree` 는 OneShot 으로 감싸 SUCCESS 후 재실행 X — robot 은 도크에 들어간 상태로 cmd_vel=0 정지. 자동 `docked` trigger 는 발표 범위 외 (사람이 admin UI 디버그 버튼으로 발사 → CHARGING).

추후 추가 예정: CollisionEventHandler.

## LOW_BATTERY_RETURNING 과의 차이

| 항목 | RETURNING | LOW_BATTERY_RETURNING |
|---|---|---|
| 진입 trigger | `return_request` / `idle_timeout` | `battery_low` |
| BatteryLowMonitor | ✅ (escalation 용) | ✗ (이미 가장 낮은 상태) |
| CommandListener | ✅ (사용자 cancel 가능) | ✗ (lockdown — 사용자 명령 차단) |
| MapBoundaryMonitor | ✅ | ✅ |
| HardwareHealthMonitor | ✅ | ✅ |
| ReturnSubTree | ✅ | ✅ |
| 이탈 경로 | `cancel` / 사용자 *_request / `docked` / `fault` | `docked` / `fault` 만 |

## FSM trigger

### 진입
| Trigger | From | Source 발화 주체 |
|---|---|---|
| `return_request` | IDLE / GOTO / FOLLOW / LULLABY / HIDEANDSEEK / MANUAL | `command_listener` 또는 `main.py._on_tree_failure()` |
| `idle_timeout` | IDLE | `idle_timeout_monitor` |

### 종료
| Trigger | To | Source 발화 주체 |
|---|---|---|
| `docked` | CHARGING | **사람** (admin UI 디버그 버튼) — 자동 도킹은 발표 범위 외 |
| `battery_low` | LOW_BATTERY_RETURNING | `battery_low_monitor` (escalation) |
| `cancel` / `*_request` | IDLE / GOTO / FOLLOW / LULLABY / HIDEANDSEEK / MANUAL | `command_listener` (사용자 명령) |
| `fault` | ERROR | `map_boundary_monitor` 등 |

## 사용 behavior

- [battery_low_monitor](../behaviors/common.md#battery_low_monitor)
- [map_boundary_monitor](../behaviors/common.md#map_boundary_monitor)
- [hardware_health_monitor](../behaviors/common.md#hardware_health_monitor)
- [command_listener](../behaviors/common.md#command_listener)
- [BT_return_sub](BT_return_sub.md) — NavigateToVertex / AlignToDock / ReverseIntoDock 호출

## 상태

- 코드: ✅ ([BT_returning_main.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/trees/main_trees/BT_returning_main.py)) — 5 자식 모두 배치 완료
