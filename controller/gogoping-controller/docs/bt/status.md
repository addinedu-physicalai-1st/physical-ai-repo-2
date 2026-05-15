# BT 구현 체크리스트

코드 구현 vs 명세(스켈레톤). docs 작성/계획만 된 항목과 실제 동작하는 항목 구분.

마지막 업데이트: 2026-05-15 (task 10 완료)

## 범례
- ✅ 구현 완료 (동작 검증)
- 🟡 부분 구현 (스켈레톤 파일 있음, 동작 미검증)
- ☐ 미구현 (코드 X, 명세만)

---

## Trees

### MainTree (6개)

| 트리 | 상태 | 비고 |
|---|---|---|
| BT_idle_main | ☐ | |
| BT_assist_main | ☐ | docs 작성 — [trees/BT_assist_main.md](trees/BT_assist_main.md) |
| BT_play_main | ☐ | |
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
| battery_full_monitor | ☐ | |
| battery_low_monitor | ☐ | |
| hardware_health_monitor | ☐ | |
| collision_event_handler | ☐ | |
| command_listener | ☐ | |
| docking_contact_check | ☐ | |
| check_task | ☐ | |
| check_carry_mode | ☐ | |
| ui_publish | ☐ | |

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
| FSM (robot_fsm.py) | ☐ | 6 state 정의만 — transition 미연결 |
| context.py | ☐ | |
| blackboard.py 스키마 | 🟡 | 파일 존재, 키 등록 미검증 |
| main.py BT swap | ☐ | |
| graph.py (다익스트라) | ✅ | 14 단위 테스트 pass |
| graph_router_node | ✅ | service + action server 노출 |
| nav2 stack (sim) | ✅ | sim_with_nav2.launch.xml |
| nav2 stack (실물) | ☐ | laptop launch 미작성 (placeholder) |
| server REST `/waypoints/route` `/waypoints/navigate` | ✅ | tests/test_waypoints_router.py 통과 |
| admin UI lanes / route 시각화 | ✅ | graph map 모드 |
| robot-web 음성 → goto_vertex | ✅ | "X로 가" / "복귀" 인식 + `/waypoints/navigate` 호출 (보조 모드 우회 통과). 분류기는 [service/ai-service/ai_service/hub.py](../../../../service/ai-service/ai_service/hub.py) `_try_goto_vertex` / `_is_return_text` |

---

## 갱신 컨벤션

새 behavior/트리 코드 추가 시 본 파일의 ☐ 를 ✅ 또는 🟡 로 변경 + 같은 commit 으로 [README.md](README.md), file-structure.md, 카테고리 .md 와 함께 업데이트.
