# BT 구현 체크리스트

코드 구현 vs 명세(스켈레톤). docs 작성/계획만 된 항목과 실제 동작하는 항목 구분.

마지막 업데이트: 2026-05-15 (task 10 완료)

## 범례
- ✅ 구현 완료 (동작 검증)
- 🟡 부분 구현 (스켈레톤 파일 있음, 동작 미검증)
- ☐ 미구현 (코드 X, 명세만)

---

## Trees

### MainTree (7개)

| 트리 | 상태 | 비고 |
|---|---|---|
| BT_idle_main | ☐ | |
| BT_assist_main | ☐ | docs 작성 — [trees/BT_assist_main.md](trees/BT_assist_main.md) |
| BT_play_main | ☐ | |
| BT_manual_main | ☐ | docs 작성 — [trees/BT_manual_main.md](trees/BT_manual_main.md). torque off 모드 |
| BT_charging_main | ☐ | |
| BT_returning_main | ☐ | |
| BT_error_main | ☐ | |

### SubTree (5개)

| 트리 | 상태 | 비고 |
|---|---|---|
| BT_carry_sub | ☐ | manual / goto / follow 3 mode |
| BT_follow_sub | ☐ | |
| BT_lullaby_sub | ☐ | |
| BT_hide_and_seek_sub | ☐ | |
| BT_return_sub | ☐ | |

---

## Behaviors

### common/

| Behavior | 상태 | 파일 |
|---|---|---|
| battery_full_monitor | ✅ | [battery_full_monitor.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/common/battery_full_monitor.py) — BT_charging_main 에 배치, 부팅 시 CHARGING → IDLE 자동 전이 (BATTERY_LEVEL init=100.0 가정) |
| battery_low_monitor | ☐ | Day 2 (`BatterySubscriber` 가 진짜 ROS 토픽 구독 시작 후) |
| hardware_health_monitor | ☐ | Day 2 |
| collision_event_handler | ☐ | Day 2 |
| map_boundary_monitor | ☐ | 맵 밖 이탈 시 fault(reason="out_of_map"). ASSIST/PLAY/RETURNING 만 (MANUAL 의도적 제외). Day 2 |
| command_listener | ✅ | [command_listener.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/common/command_listener.py) — SetGoal.srv 서버 + goal_reconciler 호출. unit test 7 + reconciler 13 |
| docking_contact_check | ☐ | Day 2 |
| check_task | ✅ | [check_task.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/common/check_task.py) — TaskSelector 분기 Condition. 5 시나리오 통과 |
| check_carry_mode | ☐ | Day 3+ (BT_carry_sub 작성 시) |
| ui_publish | ☐ | Day 3+ (HideAndSeek / Lullaby 작성 시) |

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
| FSM (robot_fsm.py) | 🟡 | 7 state (CHARGING/IDLE/ASSIST/PLAY/MANUAL/RETURNING/ERROR) + 13 transition + add_callback API 구현, sanity check pass. ROS 통합 / BT swap 검증 Day 3 |
| context.py | ☐ | |
| blackboard.py 스키마 | 🟡 | 파일 존재, 키 등록 미검증 |
| main.py BT swap | ☐ | |
| graph.py (다익스트라) | ✅ | 14 단위 테스트 pass |
| graph_router_node | ✅ | service + action server 노출 |
| nav2 stack (sim) | ✅ | sim_with_nav2.launch.xml |
| nav2 stack (실물) | ☐ | Day 2~ TODO. (`device-gogoping-laptop.sh` 에 nav2 window 자리 마련됨) |
| `device-gogoping-laptop.sh` | 🟡 | graph-router + modes 2 window. nav2 / vision 은 Day 2~ |
| server REST `/waypoints/route` `/waypoints/navigate` | ✅ | tests/test_waypoints_router.py 통과 |
| admin UI lanes / route 시각화 | ✅ | graph map 모드 |
| robot-web 음성 → goto_vertex | ✅ | "X로 가" / "복귀" 인식 + `/waypoints/navigate` 호출 (보조 모드 우회 통과). 분류기는 [service/ai-service/ai_service/hub.py](../../../../service/ai-service/ai_service/hub.py) `_try_goto_vertex` / `_is_return_text` |

---

## 갱신 컨벤션

새 behavior/트리 코드 추가 시 본 파일의 ☐ 를 ✅ 또는 🟡 로 변경 + 같은 commit 으로 [README.md](README.md), file-structure.md, 카테고리 .md 와 함께 업데이트.
