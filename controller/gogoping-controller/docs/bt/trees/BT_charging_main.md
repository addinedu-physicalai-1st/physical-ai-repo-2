# BT_charging_main

`CHARGING` state 의 MainTree — 도크에서 충전 중. 부팅 시 INITIAL_STATE.

## Root composite

```
Parallel(SuccessOnAll(synchronise=False))
├─ BatteryFullMonitor       common/battery_full_monitor.md      (✅ ≥70% → battery_full → IDLE)
├─ MapBoundaryMonitor       common/map_boundary_monitor.md       (✅ 위치 안전 — 누군가 들고 옮긴 케이스)
├─ HardwareHealthMonitor    common/hardware_health_monitor.md    (✅ LIDAR/odom staleness → fault)
└─ CommandListener          common/command_listener.md           (✅)
```

추후 추가 예정: `DockingContactCheck` — 도킹 접점 전류 흐름 감시 (현재 ☐).

### 부팅 시퀀스 — CHARGING → IDLE 자동 전이

`main.py` 의 `INITIAL_STATE="CHARGING"` 이라 가장 먼저 빌드되는 트리. 부팅 직후엔
`BatterySubscriber` 가 아직 첫 메시지 못 받은 상태일 수 있고, blackboard 초기값
`BATTERY_LEVEL=100.0` 이라 첫 tick 에 `BatteryFullMonitor` 가 ≥70% 조건 즉시 만족 →
`battery_full` trigger 발화 → IDLE.

sim 환경에선 `sim_battery_node` 가 1Hz publish 시작하면서 실제 값으로 갱신되므로
어차피 70% 이상이면 fire. 운영 (실 Pi) 에선 `battery_publisher_node` 의 publish 후
실 값이 ≥70% 일 때 fire.

## 진입 / 종료 trigger

### 진입
| Trigger | From | Source |
|---|---|---|
| (부팅 시 INITIAL_STATE) | — | `main.py` 의 `INITIAL_STATE="CHARGING"` |
| `docked` | RETURNING / LOW_BATTERY_RETURNING | `verify_docking_contact` (BT_return_sub Sequence 의 마지막 자식이 자동 발사) |

### 종료
| Trigger | To | Source |
|---|---|---|
| `battery_full` | IDLE | `battery_full_monitor` (≥70%, edge-triggered) |
| `fault` | ERROR | `map_boundary_monitor` / `hardware_health_monitor` |

> CHARGING 은 사용자 명령으로 이탈 불가 — `command_listener` 는 배치되어 있지만
> `goal_reconciler` 가 `current_state == "CHARGING"` 이면 `accepted=False` (`reason="fsm_in_charging"`)
> 으로 거부. 배터리 회복 (`battery_full`) 또는 fault 만 valid.

## 사용 behavior

- [battery_full_monitor](../behaviors/common.md#battery_full_monitor)
- [map_boundary_monitor](../behaviors/common.md#map_boundary_monitor)
- [hardware_health_monitor](../behaviors/common.md#hardware_health_monitor)
- [command_listener](../behaviors/common.md#command_listener)

## 상태

- 코드: ✅ ([BT_charging_main.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/trees/main_trees/BT_charging_main.py))
- 의존 behavior: `BatteryFullMonitor` (✅) + `MapBoundaryMonitor` (✅) + `HardwareHealthMonitor` (✅) + `CommandListener` (✅). `DockingContactCheck` 추후.
