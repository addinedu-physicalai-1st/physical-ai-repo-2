# Recovery Behaviors

ERROR state 전용 — 안전 정지 + alert + 로깅. `bt/behaviors/recovery/` 안.

Used in: BT_error_main 만.

---

## stop_all_motors  *(구현됨)*

ERROR state 진입 즉시 cmd_vel = 0 + motor torque OFF.

- `initialise()` (1회):
  1. `ctx.cmd_vel_pub.publish(Twist(0,0))` — 진행 중인 nav 명령 즉시 cancel
  2. `ctx.base_driver.release_torque()` — ZLAC disable (free-wheel, 사람이 안전한 곳으로 밀어내기 가능)
- `update()`: `Status.SUCCESS` — 1 tick 으로 끝
- `terminate()`: no-op (ERROR 가 terminal — 호출될 일 없음)

ERROR 가 terminal state 라 enable 복원은 robot 재시작 시 `bringup.py` 의 init sequence 가 자동 처리.

### MANUAL → ERROR 시 overlap 주의

`ManualTorqueHold.terminate()` 가 일반 전이 시 `enable_torque()` 호출하지만, ERROR 진입 시엔 skip 처리됨 (`bt/behaviors/manual/manual_torque_hold.py:terminate`). 이유: Pi 의 `_on_set_torque(True)` 는 set_vel_mode → enable → 1초 wait → get_rpm 검증 sequence 라 약 1초간 모터 enable 상태가 됨. e-stop 응답 시간 보장 위해 ERROR 전이 시엔 enable skip → StopAllMotors 의 release_torque 만 빠르게 실행.

| 의존 interface | [`BaseDriverClient`](../../src/gogoping/gogoping_modes/gogoping_modes/interfaces/base_driver_client.py), `ctx.cmd_vel_pub` |
| Used in | BT_error_main 만 |
| 파일 | [`bt/behaviors/recovery/stop_all_motors.py`](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/recovery/stop_all_motors.py) |

---

## (추후) notify_admin_ui

WebSocket 으로 ERROR alert publish — admin UI 의 ERROR overlay 표시. blackboard 의 `ERROR_REASON`, `ERROR_SOURCE` 활용. *(스켈레톤)*

## (추후) log_error_to_db

error_log 테이블 INSERT — 디버깅용. ERROR 발생 시각/원인 영구 기록. *(스켈레톤)*
