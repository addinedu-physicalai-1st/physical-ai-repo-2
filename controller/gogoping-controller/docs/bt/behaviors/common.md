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

배터리 ≥ 70% 감지 시 `"battery_full"` FSM trigger 발화.

- read: `Keys.BATTERY_LEVEL`
- threshold: `FULL_ENTER = 70.0` (%)
- edge-triggered (`_fired` 플래그, `initialise()` 에서 리셋)
- monitor 컨벤션 — 매 tick RUNNING 리턴

walking skeleton 단계엔 `BatterySubscriber` 가 stub 이라 `BATTERY_LEVEL` 이 init 기본값 100.0 으로 고정 → 부팅 시 첫 tick 에 즉시 fire. 사용자가 의도한 "부팅=CHARGING, 배터리 정상이면 IDLE" 시퀀스 자연 재현.

| Used in | BT_charging_main |
| 파일 | [`bt/behaviors/common/battery_full_monitor.py`](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/common/battery_full_monitor.py) |

## battery_low_monitor  *(구현됨)*

배터리 ≤ 20% 감지 시 `"battery_low"` FSM trigger 발화. hysteresis 20% 진입 / 25% 진출.

- read: `Keys.BATTERY_LEVEL`
- threshold: `LOW_ENTER = 20.0`, `LOW_EXIT = 25.0` (%)
- edge-triggered (`_fired` 플래그). hysteresis — 25% 위로 회복되면 reset 후 재발화 가능
- monitor 컨벤션 — 매 tick RUNNING 리턴
- `BatterySubscriber` 가 `/gogoping/battery` 토픽 구독으로 blackboard 갱신. sim 환경에서는 `sim_battery_node` 가 publisher + `SetBatteryLevel.srv` 디버그 server.

| Used in | BT_idle_main, BT_assist_main, BT_play_main, BT_returning_main (RETURNING → LOW_BATTERY_RETURN escalation). **MANUAL 의도적 제외** — 사용자 직접 제어 중 자동 빼앗김 방지 |
| 파일 | [`bt/behaviors/common/battery_low_monitor.py`](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/common/battery_low_monitor.py) |
| 테스트 | 5 시나리오 (100% no-fire / 20% fire / 10% no-double / 26%→20% re-fire / initialise re-arm) |

## idle_timeout_monitor  *(구현됨)*

IDLE 상태에서 N초 무명령 시 `"idle_timeout"` FSM trigger 발화 — 무인 환경 자율 도크 복귀.

- 사용 위치: BT_idle_main 만 (IDLE → RETURNING)
- 임계값: ROS param `idle_timeout_seconds` (기본 60.0s). launch arg 로 override 가능
- 타이밍 소스: `time.monotonic()` — 시스템 시계 변경에 영향 없음
- edge-triggered (`_fired` 플래그). `initialise()` 에서 timer + 플래그 리셋 → IDLE 재진입 시 새로 카운트
- monitor 컨벤션 — 매 tick RUNNING 리턴

| 파일 | [`bt/behaviors/common/idle_timeout_monitor.py`](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/common/idle_timeout_monitor.py) |
| 테스트 | 6 시나리오 (immediately no-fire / fire-after-timeout / no-double / initialise re-arm / default timeout / terminate idempotent) |

## hardware_health_monitor  *(구현됨)*

LIDAR / odom staleness 감지 → `"fault"` trigger.

**MVP 단계 모니터링 대상**:
- LIDAR `/gogoping/scan` (`sensor_msgs/LaserScan`) — 끊기면 nav2 / 충돌 회피 불가
- odom `/gogoping/odom` (`nav_msgs/Odometry`) — 끊기면 pose 추정 / 추적 불가

각 토픽의 마지막 수신 시각이 ROS param `hw_health_staleness_seconds` (기본 3.0s) 초과 시 `fsm.trigger("fault", reason="lidar_timeout" | "odom_timeout")` 발화. edge-triggered (`_fired` 플래그). LIDAR 우선 (안전상 더 critical) — 동시 stale 이면 lidar 로 보고.

**부팅 grace period**: `initialise()` 가 한 번도 메시지를 못 받은 토픽의 `_last_*` 를 *현재 시각* 으로 세팅 → 부팅 직후 트리 진입 시 grace period (= staleness threshold) 이후에야 fault. 노드 시작 직후 LIDAR / odom publisher 가 늦게 뜨는 false-positive 회피.

**배치**: CHARGING / IDLE / ASSIST / PLAY / RETURNING / LOW_BATTERY_RETURN (**6 트리**). **MANUAL/ERROR 제외** — MANUAL 은 사용자 직접 제어 중 자동 ERROR 차단 (battery/HW/collision 일관 정책). ERROR 는 terminal.

**향후 확장**:
- ZLAC 모터 통신 끊김 — vicpinky_bringup 이 `/gogoping/motor_health` (`diagnostic_msgs`) publish 하면 추가
- IMU staleness — IMU 도입 시 추가

| Used in | 6 트리 (CHARGING/IDLE/ASSIST/PLAY/RETURNING/LOW_BATTERY_RETURN) |
| 파일 | [`bt/behaviors/common/hardware_health_monitor.py`](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/common/hardware_health_monitor.py) |
| 의존 토픽 | `/gogoping/scan`, `/gogoping/odom` (직접 subscribe — 별도 interface 없음, ctx.node 사용) |
| ROS param | `hw_health_staleness_seconds` (float, 기본 3.0) |

## collision_event_handler  *(스켈레톤)*

Nav2 Collision Monitor 비정상 → `"fault"` trigger.

## map_boundary_monitor  *(구현됨)*

로봇의 현재 pose 가 로드된 맵 영역 밖이면 즉시 `"fault"` trigger 를 `reason="out_of_map"` 으로 발화.

**판별 방식** — `MapCache.is_outside(x, y)` 가 OccupancyGrid 기반으로:
1. 격자 박스 (width × height) 밖 → True
2. 박스 안이지만 `data[idx] == -1` (unknown 셀) → True  ← **비정형 맵 (L자/ㄷ자 등) 자동 처리**
3. 그 외 (free=0 / occupied=100) → False
4. 맵 미수신 시 None → 발화 안 함 (보수적 default — ERROR terminal 이라 false positive 회피)

**데이터 흐름**:
```
/amcl_pose     (nav2_amcl, map frame) ──→ PoseSubscriber ──→ blackboard.ROBOT_POSE
/map           (nav2_map_server)      ──→ MapCache       ──→ ctx.map_cache.is_outside(x,y)
                                              │
                                              ▼
                                    MapBoundaryMonitor (매 tick R)
                                              │ outside == True
                                              ▼
                              blackboard.ERROR_REASON = "out_of_map"
                              blackboard.ERROR_SOURCE = "MapBoundaryMonitor"
                              fsm.trigger("fault", reason="out_of_map")
                                              │
                                              ▼
                                         state: ERROR (terminal)
```

- 발화 후에는 `_fired = True` 로 edge-triggered 유지 (반복 발화 방지). ERROR terminal 이라 re-arm 필요 없으나 `initialise()` 가 새 트리 진입 시 리셋해주므로 ASSIST/PLAY/RETURNING 재진입 시 다시 발화 가능.
- 일반 경로 이탈 (re-plan 가능한 수준) 은 본 monitor 대상이 *아님* — 그건 nav2 가 자체 처리. **본 monitor 는 "맵 밖으로 완전히 나간 catastrophic 케이스" 한정**.
- MANUAL state 에는 의도적으로 배치하지 않음 — MANUAL 은 사용자가 직접 제어하므로 자동 ERROR 전이 금지. 자세한 이유 [`bt/trees/BT_manual_main.md`](../trees/BT_manual_main.md).

| Used in | **7 트리** — BT_charging_main, BT_idle_main, BT_assist_main, BT_play_main, BT_manual_main, BT_returning_main, BT_low_battery_return_main (ERROR 만 제외 — terminal). **MANUAL 예외** — battery/hw/collision 은 MANUAL 미배치지만 MapBoundaryMonitor 만 예외적 배치 (위치 안전 우선) |
| 파일 | [`bt/behaviors/common/map_boundary_monitor.py`](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/common/map_boundary_monitor.py) |
| 의존 interfaces | [`PoseSubscriber`](../../src/gogoping/gogoping_modes/gogoping_modes/interfaces/pose_subscriber.py) · [`MapCache`](../../src/gogoping/gogoping_modes/gogoping_modes/interfaces/map_cache.py) |
| 테스트 | 7 시나리오 (inside / outside fire / map None / no-double / ERROR_REASON 세팅 / initialise re-arm / pose 누락) |

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

## ui_publish  *(구현됨)*

범용 UI 알림 publish — `message: dict` 1회 publish 후 즉시 SUCCESS. `update()` 가
`ctx.ui.publish_event(message)` 호출.

- read: 없음 (blackboard 의존 X)
- write: 없음
- 사용 예:
  ```python
  UIPublish("AnnounceFound", ctx, message={"event": "announce", "text": "찾았다!"})
  UIPublish("StartCountdown", ctx, message={"event": "countdown_start", "seconds": 30})
  ```
- 자장가 stop 같은 cleanup-시점 publish 는 ❌ — 그건 [`lullaby_audio`](#lullaby_audio) 처럼
  `terminate()` 책임을 가진 behavior 가 처리.
- "1회" 는 단일 활성화당 1회 — Selector(memory=False) 재진입 시 다시 publish (의도된 동작).

| 항목 | 값 |
|---|---|
| Topic publish | `/gogoping/ui_event` (`std_msgs/String` JSON) — via `ctx.ui.publish_event()` |
| Status | SUCCESS (즉시) |
| terminate(INVALID) | no-op |
| Used in | BT_lullaby_sub (간접 — LullabyAudio 사용), 추후 BT_hide_and_seek_sub (announce/countdown), BT_carry_sub |
| 파일 | [`bt/behaviors/common/ui_publish.py`](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/common/ui_publish.py) |
| 테스트 | 5 시나리오 (update=SUCCESS / publish_event 1회 호출 / initialise no-op / 임의 message dict 통과 / 재활성화 시 다시 publish) |

---

## lullaby_audio  *(구현됨)*

자장가 SubTree 본체. `initialise()` 에 play publish, `update()` 영구 RUNNING, `terminate()`
에 stop publish (idempotent).

- read: 없음
- write: 없음
- mp3 재생 자체는 robot-web frontend 의 `<audio>` element 가 담당 (별도 PR) — BT 는
  `/gogoping/ui_event` 에 이벤트만 publish.
- `_stop_published` flag — `__init__` 초기값 `True` (cold terminate 시 publish 안 함).
  `initialise()` 가 `False` 로 리셋 → play publish 된 lifetime 안에서만 stop publish 보장.

| 항목 | 값 |
|---|---|
| Topic publish | `/gogoping/ui_event` (`std_msgs/String` JSON) — via `ctx.ui.publish_event()` |
| Messages | `PLAY_MSG = {"event": "lullaby_play", "src": "lullaby.mp3", "loop": True}` / `STOP_MSG = {"event": "lullaby_stop"}` |
| Status | initialise=play publish 1회 / update=RUNNING 영구 / terminate=stop publish (idempotent) |
| terminate(INVALID) | stop publish (`_stop_published` flag) |
| Used in | BT_lullaby_sub (단일 leaf) |
| 파일 | [`bt/behaviors/common/lullaby_audio.py`](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/common/lullaby_audio.py) |
| 테스트 | 7 시나리오 (play publish / update RUNNING / stop publish / idempotent / 재진입 flag 리셋 / 메시지 상수 / cold terminate no-op) |
