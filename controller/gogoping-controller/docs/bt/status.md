# BT 구현 체크리스트

코드 구현 vs 명세(스켈레톤). docs 작성/계획만 된 항목과 실제 동작하는 항목 구분.

마지막 업데이트: 2026-05-18 (walking skeleton + 배터리 monitor 라인 — BatterySubscriber 실 구현 + battery_low_monitor + sim 디버그 슬라이더)

## 범례
- ✅ 구현 완료 (동작 검증)
- 🟡 부분 구현 (스켈레톤 파일 있음 — stub 의미 동등성 검증, 진짜 동작 미검증)
- ☐ 미구현 (코드 X, 명세만)

---

## Trees

### MainTree (8개)

| 트리 | 상태 | 비고 |
|---|---|---|
| BT_charging_main | ✅ | Parallel(BatteryFullMonitor + CommandListener). 부팅 시 첫 tick 에 battery_full → IDLE 자동 전이 |
| BT_idle_main | ✅ | Parallel(BatteryLowMonitor + CommandListener). docs — [trees/BT_idle_main.md](trees/BT_idle_main.md) |
| BT_assist_main | ✅ | Parallel(BatteryLowMonitor + CommandListener + TaskSelector — carry/follow/lullaby 분기, 각 branch 는 stub). docs — [trees/BT_assist_main.md](trees/BT_assist_main.md) |
| BT_play_main | ✅ | Parallel(BatteryLowMonitor + CommandListener + TaskSelector — hideseek 분기, stub) |
| BT_manual_main | ✅ | Parallel(CommandListener). torque OFF / 자동 monitor 0개 (BatteryLowMonitor 의도적 미배치 — 사용자 직접 제어 중 자동 빼앗김 방지). docs — [trees/BT_manual_main.md](trees/BT_manual_main.md) |
| BT_returning_main | ✅ | Parallel(BatteryLowMonitor + CommandListener). escalation — RETURNING 중 배터리 떨어지면 LOW_BATTERY_RETURN. 진짜 ReturnSubTree 는 미작성 |
| BT_low_battery_return_main | ✅ | Parallel(빈 lockdown — CommandListener 없음). battery_low escalation 도피 state. docs — [trees/BT_low_battery_return_main.md](trees/BT_low_battery_return_main.md) |
| BT_error_main | ✅ | Parallel(빈 terminal). reset 없음 — 사람이 재시작 |

> **walking skeleton 단계**: 8 트리의 골격 + CommandListener / 일부 monitor 만 동작. 진짜 SubTree (carry/follow/lullaby/hideseek/return) 는 `_stubs/` 임시 placeholder. main.py 의 BT swap 루프가 FSM state 변화에 맞춰 트리를 교체 — 8 state 모두 진입/이탈 검증 (force_state 디버그 포함).

### SubTree — 진짜 구현 (0개)

| 트리 | 상태 | 비고 |
|---|---|---|
| BT_carry_sub | ☐ | StubCarry 로 대체 중. manual / goto / follow 3 mode |
| BT_follow_sub | ☐ | StubFollow 로 대체 중. 정상 ↔ Loss Recovery |
| BT_lullaby_sub | ☐ | StubLullaby 로 대체 중. UI mp3 재생 + WaitForExit |
| BT_hide_and_seek_sub | ☐ | StubHideseek 로 대체 중. 1회 실행 후 종료 |
| BT_return_sub | ☐ | NavigateToPose → AlignToDock → ApproachDock → VerifyDockingContact |

### Stub (_stubs/ — 4개 + 2 base)

walking skeleton 단계의 임시 placeholder. 진짜 SubTree 작성 시 폴더째 삭제 + 사용처 (BT_assist_main / BT_play_main) 교체. `grep -rn "STUB:" controller/gogoping-controller/` 로 검색.

| 파일 | 상태 | 의미상 동등성 |
|---|---|---|
| `_stubs/_base.py` | ✅ | `StubRunningThenSuccess` (N tick → SUCCESS) + `StubInfiniteRunning` (항상 RUNNING) |
| `_stubs/stub_carry.py` | 🟡 | `StubRunningThenSuccess(30 tick = 3초)`. 진짜 carry+goto 의 "목적지 도달 시 SUCCESS" 의미와 동등 |
| `_stubs/stub_follow.py` | 🟡 | `StubInfiniteRunning`. 진짜 follow 의 "사람 보이는 한 RUNNING" 의미와 동등 |
| `_stubs/stub_lullaby.py` | 🟡 | `StubInfiniteRunning`. 진짜 lullaby 의 "사용자 stop 명령까지 RUNNING" 의미와 동등 |
| `_stubs/stub_hideseek.py` | 🟡 | `StubRunningThenSuccess(30 tick = 3초)`. 진짜 hideseek 의 "1회 사이클 후 SUCCESS" 의미와 동등 |

---

## Behaviors

### common/

| Behavior | 상태 | 파일 |
|---|---|---|
| battery_full_monitor | ✅ | [battery_full_monitor.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/common/battery_full_monitor.py) — BT_charging_main 에 배치, 부팅 시 CHARGING → IDLE 자동 전이 (BATTERY_LEVEL init=100.0 가정) |
| battery_low_monitor | ✅ | [battery_low_monitor.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/common/battery_low_monitor.py) — hysteresis 20% 진입 / 25% 진출, edge-triggered. BT_idle/assist/play/returning_main 4개 배치 (RETURNING 은 LOW_BATTERY_RETURN escalation). 5 시나리오 통과 |
| hardware_health_monitor | ☐ | |
| collision_event_handler | ☐ | |
| map_boundary_monitor | ☐ | 맵 밖 이탈 시 fault(reason="out_of_map"). ASSIST/PLAY/RETURNING 만 (MANUAL 의도적 제외) |
| command_listener | ✅ | [command_listener.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/common/command_listener.py) — `SetGoal.srv` + `ForceState.srv` 2개 서버 호스팅. SetGoal → `goal_reconciler` 호출. ForceState → `fsm.force_state()` + sub_task blackboard 세팅 (ASSIST→assist_task, PLAY→play_task). unit test 7 + reconciler 13 |
| docking_contact_check | ☐ | |
| check_task | ✅ | [check_task.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/common/check_task.py) — TaskSelector 분기 Condition. 5 시나리오 통과 |
| check_carry_mode | ☐ | BT_carry_sub 작성 시 |
| ui_publish | ☐ | HideAndSeek / Lullaby 작성 시 |

### navigation/

| Behavior | 상태 | 파일 |
|---|---|---|
| **navigate_to_vertex** | ✅ | [navigate_to_vertex.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/navigation/navigate_to_vertex.py) — graph_router action client. import 검증만, BT 통합 동작 검증 미실시 |
| navigate_to_pose | ☐ | |
| align_to_dock | ☐ | |
| approach_dock | ☐ | |
| verify_docking_contact | ☐ | |
| stop_base | ☐ | |
| maintain_distance | ☐ | |
| check_arrival | ☐ | |

### perception/

| Behavior | 상태 |
|---|---|
| is_target_visible | ☐ |
| detect_target_person | ☐ |
| found_child | ☐ |
| child_face_tracker | ☐ |
| load_stability_check | ☐ |

### follow/

| Behavior | 상태 |
|---|---|
| face_tracking | ☐ |
| wait_for_reappear | ☐ |
| raise_camera_pan | ☐ |
| pan_camera_sweep | ☐ |

### manual/

| Behavior | 상태 |
|---|---|
| enable_manual_control | ☐ |
| wait_for_exit | ☐ |

### recovery/

| Behavior | 상태 |
|---|---|
| stop_all_motors | ☐ |
| notify_admin_ui | ☐ |
| log_error_to_db | ☐ |

---

## 인프라 / 외부 시스템

| 항목 | 상태 | 비고 |
|---|---|---|
| FSM (robot_fsm.py) | ✅ | 8 state (CHARGING/IDLE/ASSIST/PLAY/MANUAL/RETURNING/**LOW_BATTERY_RETURN**/ERROR) + 12 transition (`*_request` 명명) + `force_state(target)` debug API |
| FSM `force_state(target)` debug | ✅ | `fsm.machine.set_state()` + 수동 `_after_state_change()` 호출로 transition 우회. admin DebugStatePanel 진입점 |
| Goal 기반 reconciler (goal_reconciler.py) | ✅ | 순수 함수 — 현재 state ↔ Goal 차이 보고 적절한 trigger 매핑. ROS 의존성 0 → 단위 테스트 13 pass. ERROR / LOW_BATTERY_RETURN lockdown 처리 |
| Tree inspector (tree_inspector.py) | ✅ | `snapshot(fsm_state, root_tree)` → admin BTStateInline 호환 dict. **battery_level 키** 포함 (blackboard.BATTERY_LEVEL 읽음) |
| Context (context.py) | ✅ | `@dataclass(frozen=True)` — node / fsm / 6 interfaces (`ui_publisher` 만 실 구현, 나머지 5 stub) |
| main.py BT swap | ✅ | `GogopingModes` 노드 — INITIAL_STATE="CHARGING", TICK_HZ=10, PUBLISH_HZ=1. state 변화 시 트리 swap + 이전 트리 `shutdown()` |
| blackboard.py 스키마 | ✅ | 21 Keys + `init_blackboard()`. Access 권한 (READ/WRITE) 등록 |
| graph.py (다익스트라) | ✅ | 14 단위 테스트 pass |
| graph_router_node | ✅ | service + action server 노출 |
| nav2 stack (sim) | ✅ | sim_with_nav2.launch.xml |
| nav2 stack (실물) | ☐ | TODO. (`device-gogoping-laptop.sh` 에 nav2 window 자리 마련됨) |
| `device-gogoping-laptop.sh` | 🟡 | graph-router + modes 2 window. nav2 / vision 미포함 |
| `device-gogoping-sim.sh` | ✅ | gazebo + graph-router + modes + rviz self-contained |
| ROS msg/srv 계약 (gogoping_msgs) | ✅ | `Goal.msg` / `GoalStatus.msg` / `SetGoal.srv` / `ForceState.srv` / `SetBatteryLevel.srv` (CMakeLists 등록 완료) |
| BatterySubscriber (real) | ✅ | [battery_subscriber.py](../../src/gogoping/gogoping_modes/gogoping_modes/interfaces/battery_subscriber.py) — `/gogoping/battery` (sensor_msgs/BatteryState) 구독. `percentage * 100 → Keys.BATTERY_LEVEL`. NaN 시 직전 값 유지 |
| sim_battery_node | ✅ | [gogoping_bringup/sim_battery_node.py](../../../gogoping-controller/src/gogoping/gogoping_bringup/gogoping_bringup/sim_battery_node.py) — **sim 전용**. `/gogoping/battery` 1Hz publish + `/gogoping/sim/set_battery_level` srv. device-gogoping-sim.sh 가 자동 실행 |
| battery_publisher_node | 🟡 | [gogoping_bringup/battery_publisher_node.py](../../../gogoping-controller/src/gogoping/gogoping_bringup/gogoping_bringup/battery_publisher_node.py) — **Pi 운영용**. `pi.launch.py` 안 `PushRosNamespace("gogoping")` 그룹에 등록 → `/gogoping/battery` 1Hz. ROS param `source` 으로 `static`/`sysfs`/`uart` 선택. **현재 source=static (placeholder 100%)** — 진짜 ADC 통합은 하드웨어 spec 확정 후 TODO |
| Control Service `/api/gogoping/debug/battery` | ✅ | BatteryDebugSlider → state_client → POST → ros_bridge.set_battery_level_sync → `SetBatteryLevel.srv` |
| Admin UI BatteryDebugSlider | ✅ | BTStateInline 디버그 영역. QSlider(0-100) + 현재값 라벨 + 적용. 임계점 (low 20/25, full 70) 표시. sim 환경 전용 (실물엔 `service_unavailable`) |
| Admin UI GogoPingDashboard 실 배터리 표시 | ✅ | header `battery_chip` (StatChip) + 시스템 카드 `battery` (BatteryBar) 둘 다 snapshot.battery_level 로 라이브 갱신. **실물에서도 동작** (BatterySubscriber → blackboard → snapshot → WS → dashboard) |
| server REST `/waypoints/route` `/waypoints/navigate` | ✅ | tests/test_waypoints_router.py 통과 |
| admin UI lanes / route 시각화 | ✅ | graph map 모드 |
| robot-web 음성 → goto_vertex | ✅ | "X로 가" / "복귀" 인식 + `/waypoints/navigate` 호출 (보조 모드 우회 통과). 분류기는 [service/ai-service/ai_service/hub.py](../../../../service/ai-service/ai_service/hub.py) `_try_goto_vertex` / `_is_return_text` |
| Control Service `/api/gogoping/mode` | ✅ | mode_to_goal.py 매핑 (대기/추종/운반/자장가/숨바꼭질/수동/복귀) + ros_bridge.send_goal_sync |
| Control Service `/api/gogoping/debug/force-state` | ✅ | DebugStatePanel → state_client → POST → ros_bridge.force_state_sync → `ForceState.srv` |
| Control Service `GogopingRosBridge` | ✅ | SetGoal + ForceState 클라이언트 + `/gogoping/state` 토픽 구독 |
| Control Service `/ws/robot-state` | ✅ | gogoping state WS fan-out |
| Admin UI BTStateInline | ✅ | 3 cell (state/main/sub) + 임베디드 DebugStatePanel |
| Admin UI DebugStatePanel | ✅ | state combo + sub combo + 적용 버튼. state 의존 sub 옵션 (ASSIST→carry/follow/lullaby, PLAY→hideseek) |
| Robot-web shared/robots.json | ✅ | gogoping 모드 — 대기 / 보조▾(추종/운반/자장가) / 놀이▾(숨바꼭질) / 수동 / 복귀 |

---

## 갱신 컨벤션

새 behavior/트리 코드 추가 시 본 파일의 ☐ 를 ✅ 또는 🟡 로 변경 + 같은 commit 으로 [README.md](README.md), file-structure.md, 카테고리 .md 와 함께 업데이트.
