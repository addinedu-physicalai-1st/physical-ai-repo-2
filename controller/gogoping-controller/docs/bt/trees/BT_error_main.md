# BT_error_main

ERROR state 의 MainTree — terminal. 모터 즉시 정지 + (추후) admin alert + log.

## Root composite

```
Parallel(SuccessOnAll(synchronise=False))
└─ StopAllMotors      recovery/stop_all_motors.md  (✅ cmd_vel=0 + torque OFF)
```

추후 확장 예정 — `Sequence` 안에 `NotifyAdminUI` / `LogErrorToDB` 추가 (현재는 StopAllMotors 1개만).

## 사용 behavior

| Behavior | 책임 | 상세 |
|---|---|---|
| `StopAllMotors` (✅) | `initialise()` 1회 — cmd_vel=0 + `release_torque()` | [recovery/stop_all_motors](../behaviors/recovery.md#stop_all_motors) |

## 진입 trigger

| Trigger | From | Source 발화 주체 |
|---|---|---|
| `fault` (reason="user_emergency_stop") | 거의 모든 state | `/gogoping/emergency_stop` (Trigger srv) — admin UI e-stop 버튼 / 외부 안전 시스템 |
| `fault` (reason="out_of_map") | CHARGING/IDLE/ASSIST/PLAY/MANUAL/RETURNING/LOW_BATTERY_RETURN | `MapBoundaryMonitor` |
| `fault` (reason="lidar_timeout" 등) | 동일 | `HardwareHealthMonitor` (스켈레톤) |
| `fault` (reason="...") | 동일 | `CollisionEventHandler` (스켈레톤) |

## 종료 trigger

**없음** — ERROR 는 terminal. 사람이 robot 재시작 (process restart) 해야 복구.

robot 재시작 시:
- `vicpinky_bringup.__init__` 의 enable sequence 가 자동 실행 → motor torque ON
- gogoping_modes 가 INITIAL_STATE (CHARGING) 부터 다시 시작

## 안전 관련 주의

1. **MANUAL → ERROR 전이의 timing 안전**:
   - `ManualTorqueHold.terminate()` 가 일반 전이 시 `enable_torque()` 호출 (1초 wait sequence).
   - ERROR 전이 시엔 의도적으로 skip — `StopAllMotors` 의 `release_torque` 가 즉시 실행되도록.
   - 자세히는 [recovery.md](../behaviors/recovery.md#stop_all_motors) 의 "MANUAL → ERROR overlap 주의" 섹션.

2. **CommandListener 미배치** — ERROR 에서 SetGoal / ForceState 받지 않음 (terminal lockdown).

3. **MapBoundaryMonitor 미배치** — 이미 ERROR 상태라 추가 fault 무의미.

4. **Emergency Stop 호출 경로**:
   ```
   Admin UI 버튼 / 외부 트리거
        ↓
   ROS srv /gogoping/emergency_stop (std_srvs/Trigger)
        ↓ command_listener._on_emergency_stop_request
   blackboard.ERROR_REASON = "user_emergency_stop"
   blackboard.ERROR_SOURCE = "emergency_stop_service"
        ↓
   fsm.force_state("ERROR")  → BT_error_main 빌드
        ↓
   StopAllMotors.initialise()
        ├─ ctx.cmd_vel_pub.publish(Twist(0,0))
        └─ ctx.base_driver.release_torque()
   ```

## 상태

- 코드: ✅ ([BT_error_main.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/trees/main_trees/BT_error_main.py))
- 의존 behavior: `StopAllMotors` (✅). `NotifyAdminUI` / `LogErrorToDB` 추후.
- 자세한 behavior 명세: [`bt/behaviors/recovery.md`](../behaviors/recovery.md)
