# Manual Behaviors

MANUAL state / 수동 모드 전용 behavior. `bt/behaviors/manual/` 안.

---

## manual_torque_hold  *(구현됨)*

`BT_manual_main` 진입 시 motor torque OFF (사용자가 직접 밀 수 있게), 나갈 때 ON 복원.

- `initialise()`: `ctx.base_driver.release_torque()` 호출 → `/gogoping/set_torque` (SetBool, data=False) → vicpinky_bringup 이 `zlac_driver.disable()` 실행. blackboard `MANUAL_TORQUE_ACTIVE = True` 세팅 (UI 표시용).
- `update()`: 매 tick `Status.RUNNING` (monitor 컨벤션 — SUCCESS/FAILURE 금지)
- `terminate(new_status)`: `enable_torque()` 호출 → driver `enable()` 복원. blackboard flag 정리. **idempotent** — 실패해도 다른 state 의 cmd_vel publish 시 driver 가 자동 enable.

torque 복원 보장: `main.py:_build_tree_for_state` 가 state 전이 시 `tree.shutdown()` 명시 호출 → py_trees 가 RUNNING 자식의 `terminate()` 전파.

| Used in | BT_manual_main (Parallel 자식 3개 중 하나) |
| 파일 | [`bt/behaviors/manual/manual_torque_hold.py`](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/manual/manual_torque_hold.py) |
| 의존 interface | [`BaseDriverClient`](../../src/gogoping/gogoping_modes/gogoping_modes/interfaces/base_driver_client.py) — `/gogoping/set_torque` (std_srvs/SetBool) wrapper |
| Blackboard write | `MANUAL_TORQUE_ACTIVE: bool` |
| 테스트 | 6 시나리오 — initialise 호출 / update RUNNING / terminate 호출 / release 실패 / enable 실패 / driver None |

