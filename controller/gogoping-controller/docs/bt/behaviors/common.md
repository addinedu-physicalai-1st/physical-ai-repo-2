# Common Behaviors

여러 트리에서 재사용되는 공통 behavior. `bt/behaviors/common/` 안.

각 항목 — *(스켈레톤)* 표시는 아직 코드 구현 전.

---

## command_listener {#command_listener}  *(스켈레톤)*

외부 명령 수신 → blackboard 세팅 + `fsm.trigger()` 호출. **모든 MainTree 의 monitor 분기에서 항상 tick** (sub mode 무관 즉응).

| 항목 | 값 |
|---|---|
| Source | server `/voice/intent` 응답 → `gogoping_msgs/SendCommand` 서비스 또는 별도 토픽 |
| Blackboard write | `assist_task`, `play_task`, `carry_mode`, `target_id`, `target_vertex_name`, ... |
| FSM trigger | command 종류에 따라 — 자세한 trigger 매트릭스는 [../trees/BT_assist_main.md](../trees/BT_assist_main.md), [../trees/BT_play_main.md](../trees/BT_play_main.md), [../trees/BT_idle_main.md](../trees/BT_idle_main.md) 참조 |
| Used in | BT_idle_main, BT_assist_main, BT_play_main |

---

## battery_full_monitor / battery_low_monitor  *(스켈레톤)*

배터리 ≥ 80% / ≤ 50% 감지 → `"battery_full"` / `"battery_low"` FSM trigger.

## hardware_health_monitor  *(스켈레톤)*

센서/모터 응답 끊김 감지 → `"fault"` trigger.

## collision_event_handler  *(스켈레톤)*

Nav2 Collision Monitor 비정상 → `"fault"` trigger.

## docking_contact_check  *(스켈레톤)*

도킹 접점 전류 흐름 감시. 끊김 시 fault.

## check_task / check_carry_mode  *(스켈레톤)*

blackboard 값 비교 (TaskSelector 분기용 Condition).

## ui_publish  *(스켈레톤)*

범용 UI 알림 publish (announce / countdown_start 등). message dict 만 다르게 전달 후 즉시 SUCCESS.

| Used in | BT_hide_and_seek_sub, BT_carry_sub (goto/manual), BT_lullaby_sub |
