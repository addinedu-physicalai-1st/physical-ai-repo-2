# Common Behaviors

여러 트리에서 재사용되는 공통 behavior. `bt/behaviors/common/` 안.

각 항목 — *(스켈레톤)* 표시는 아직 코드 구현 전.

---

## command_listener {#command_listener}  *(구현됨)*

외부 명령 수신 → blackboard 세팅 + `fsm.trigger()` 호출. **CHARGING/IDLE/ASSIST/PLAY/MANUAL/RETURNING MainTree 에 배치** (LOW_BATTERY_RETURN/ERROR 는 의도적 제외 — lockdown).

| 항목 | 값 |
|---|---|
| Source | `gogoping_msgs/srv/SetGoal` + `gogoping_msgs/srv/ForceState` 두 ROS 서비스 server 호스팅. Control Service 의 `GogopingRosBridge` 가 client. UI → POST `/api/gogoping/mode` (운영) / POST `/api/gogoping/debug/force-state` (디버그) → bridge → srv. |
| SetGoal 처리 | `utils/goal_reconciler.py` 의 순수 함수 호출 — 현재 state ↔ Goal 차이를 보고 적절한 `*_request` trigger 매핑. ERROR / LOW_BATTERY_RETURN 진입 시 거부 (`accepted=False` + reason). |
| ForceState 처리 | `fsm.force_state(target_state)` 호출 + sub_task 가 주어지면 blackboard 의 `assist_task` (ASSIST) 또는 `play_task` (PLAY) 세팅. transition 우회 — 디버그 전용. |
| Blackboard write | `assist_task`, `play_task`, `carry_mode`, `target_id`, `destination_key`, ... |
| FSM trigger | `assist_request` / `play_request` / `manual_request` / `return_request` / `cancel` (reconciler 가 매핑) |
| Used in | BT_charging_main, BT_idle_main, BT_assist_main, BT_play_main, BT_manual_main, BT_returning_main |
| 파일 | [`bt/behaviors/common/command_listener.py`](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/common/command_listener.py) |
| 테스트 | unit test 7 (server lifecycle / Goal 처리 / ForceState 처리) + reconciler 13 (goal_reconciler 단위) |

---

## battery_full_monitor  *(구현됨)*

배터리 ≥ 80% 감지 시 `"battery_full"` FSM trigger 발화.

- read: `Keys.BATTERY_LEVEL`
- threshold: `FULL_ENTER = 80.0` (%)
- edge-triggered (`_fired` 플래그, `initialise()` 에서 리셋)
- monitor 컨벤션 — 매 tick RUNNING 리턴

walking skeleton 단계엔 `BatterySubscriber` 가 stub 이라 `BATTERY_LEVEL` 이 init 기본값 100.0 으로 고정 → 부팅 시 첫 tick 에 즉시 fire. 사용자가 의도한 "부팅=CHARGING, 배터리 정상이면 IDLE" 시퀀스 자연 재현.

| Used in | BT_charging_main |
| 파일 | [`bt/behaviors/common/battery_full_monitor.py`](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/common/battery_full_monitor.py) |

## battery_low_monitor  *(스켈레톤)*

배터리 ≤ 50% 감지 시 `"battery_low"` FSM trigger 발화. hysteresis 50% 진입 / 55% 진출.

- read: `Keys.BATTERY_LEVEL`
- `BatterySubscriber` 가 실제 ROS 토픽 구독으로 교체되면 의미있게 동작

| Used in (예정) | BT_idle_main, BT_assist_main, BT_play_main, BT_returning_main (RETURNING → LOW_BATTERY_RETURN escalation) |

## hardware_health_monitor  *(스켈레톤)*

센서/모터 응답 끊김 감지 → `"fault"` trigger.

## collision_event_handler  *(스켈레톤)*

Nav2 Collision Monitor 비정상 → `"fault"` trigger.

## map_boundary_monitor  *(스켈레톤)*

로봇의 현재 pose (`/amcl_pose` 또는 `/odom`) 가 로드된 맵 경계 밖으로 나가면 즉시 `"fault"` trigger 를 `reason="out_of_map"` 으로 발화.

- threshold: 맵 점유 영역 (occupancy grid) 의 *외곽* + 안전 margin (예: 0.5m). ROS param 으로 조정.
- 발화 후에는 `_fired = True` 로 edge-triggered 유지 (반복 발화 방지).
- 일반 경로 이탈 (re-plan 가능한 수준) 은 본 monitor 대상이 *아님* — 그건 nav2 가 자체 처리. **본 monitor 는 "맵 밖으로 완전히 나간 catastrophic 케이스" 한정**.
- MANUAL state 에는 의도적으로 배치하지 않음 — MANUAL 은 사용자가 직접 제어하므로 자동 ERROR 전이 금지 (사용자가 로봇을 들고 맵 경계 너머로 가도 ERROR 안 가짐). 자세한 이유 [`bt/trees/BT_manual_main.md`](../trees/BT_manual_main.md).

| Used in | BT_assist_main, BT_play_main, BT_returning_main |

## docking_contact_check  *(스켈레톤)*

도킹 접점 전류 흐름 감시. 끊김 시 fault.

## check_task  *(구현됨)*

blackboard `assist_task` / `play_task` 값 비교. TaskSelector 분기용 Condition. 매칭 시 SUCCESS, 불일치 시 FAILURE.

- read: `Keys.ASSIST_TASK` 또는 `Keys.PLAY_TASK`
- Used in: BT_assist_main (carry/follow/lullaby 분기), BT_play_main (hideseek 분기)
- 파일: [`bt/behaviors/common/check_task.py`](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/common/check_task.py)
- 테스트: 5 시나리오 통과

## check_carry_mode  *(스켈레톤)*

blackboard 값 비교 (BT_carry_sub 의 CarryCore 분기용 Condition).

## ui_publish  *(스켈레톤)*

범용 UI 알림 publish (announce / countdown_start 등). message dict 만 다르게 전달 후 즉시 SUCCESS.

| Used in | BT_hide_and_seek_sub, BT_carry_sub (goto/manual), BT_lullaby_sub |
