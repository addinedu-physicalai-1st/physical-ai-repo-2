# BT 구현 체크리스트

코드 구현 vs 명세(스켈레톤). docs 작성/계획만 된 항목과 실제 동작하는 항목 구분.

마지막 업데이트: 2026-05-18 (텔레포트 RViz↔Gazebo 동기화 — `/debug/pose` 가 `/initialpose` 까지 같이 publish + sim_teleport_node 가 `/initialpose` 토픽 구독으로 자동 Gazebo 텔레포트. 맵 Shift+클릭과 TopBar Pose 양쪽 다 RViz/AMCL + Gazebo 동시 이동)

## 범례
- ✅ 구현 완료 (동작 검증)
- 🟡 부분 구현 (스켈레톤 파일 있음 — stub 의미 동등성 검증, 진짜 동작 미검증)
- ☐ 미구현 (코드 X, 명세만)

## 진행률 (✅ / 전체 — 🟡 / ☐ 미포함)

| 영역 | 진행 | 비고 |
|---|---|---|
| **Trees** | **9 / 13** | MainTree 8/8 ✅ · SubTree 1/5 (BT_return_sub ✅) |
| **Stubs (_stubs/)** | **1 / 5** | base ✅ · 4 stub 🟡 (의미 동등) |
| **Behaviors** | **12 / 34** | common 7/11 · navigation 4/8 · perception 0/5 · follow 0/4 · manual 1/3 · recovery 0/3 |
| **Infrastructure** | **34 / 37** | 🟡 2 (device-gogoping-laptop.sh / battery_publisher_node) · ☐ 1 (nav2 실물). PoseSubscriber + MapCache + gogoping_camera_pan 5종 추가 |
| **합계** | **55 / 88** | walking skeleton + battery line + idle_timeout + map_boundary + camera pan/tilt + **return cycle (NavTo + Align + Reverse + VerifyDocked + BT_return_sub)** |

---

## Trees

### MainTree — 8 / 8

| 트리 | 상태 | 비고 |
|---|---|---|
| BT_charging_main | ✅ | Parallel(BatteryFullMonitor + MapBoundaryMonitor + CommandListener). 부팅 시 첫 tick 에 battery_full → IDLE 자동 전이 |
| BT_idle_main | ✅ | Parallel(BatteryLowMonitor + IdleTimeoutMonitor + MapBoundaryMonitor + CommandListener). docs — [trees/BT_idle_main.md](trees/BT_idle_main.md) |
| BT_assist_main | ✅ | Parallel(BatteryLowMonitor + MapBoundaryMonitor + CommandListener + TaskSelector — carry/follow/lullaby 분기, 각 branch 는 stub). docs — [trees/BT_assist_main.md](trees/BT_assist_main.md) |
| BT_play_main | ✅ | Parallel(BatteryLowMonitor + MapBoundaryMonitor + CommandListener + TaskSelector — hideseek 분기, stub) |
| BT_manual_main | ✅ | Parallel(ManualTorqueHold + MapBoundaryMonitor + CommandListener). torque OFF/ON 라이프사이클 ✅. battery·HW·collision monitor 미배치 — 위치 안전(MapBoundary)만 예외적 배치. docs — [trees/BT_manual_main.md](trees/BT_manual_main.md) |
| BT_returning_main | ✅ | Parallel(BatteryLowMonitor + MapBoundaryMonitor + CommandListener + **ReturnSubTree**). escalation — RETURNING 중 배터리 떨어지면 LOW_BATTERY_RETURN. ReturnSubTree = OneShot(NavTo "충전소입구" → AlignToDock → ReverseIntoDock) |
| BT_low_battery_return_main | ✅ | Parallel(MapBoundaryMonitor + **ReturnSubTree**) — lockdown (CommandListener 없음, 사용자 명령 차단). ReturnSubTree 동일 (RETURNING 과 공유). docs — [trees/BT_low_battery_return_main.md](trees/BT_low_battery_return_main.md) |
| BT_error_main | ✅ | Parallel(빈 terminal). reset 없음 — 사람이 재시작 |

> **walking skeleton 단계**: 8 트리의 골격 + CommandListener / 일부 monitor 만 동작. 진짜 SubTree (carry/follow/lullaby/hideseek/return) 는 `_stubs/` 임시 placeholder. main.py 의 BT swap 루프가 FSM state 변화에 맞춰 트리를 교체 — 8 state 모두 진입/이탈 검증 (force_state 디버그 포함).

### SubTree — 0 / 5

| 트리 | 상태 | 비고 |
|---|---|---|
| BT_carry_sub | ☐ | StubCarry 로 대체 중. manual / goto / follow 3 mode |
| BT_follow_sub | ☐ | StubFollow 로 대체 중. 정상 ↔ Loss Recovery |
| BT_lullaby_sub | ☐ | StubLullaby 로 대체 중. UI mp3 재생 + WaitForExit |
| BT_hide_and_seek_sub | ☐ | StubHideseek 로 대체 중. 1회 실행 후 종료 |
| BT_return_sub | ✅ | [BT_return_sub.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/trees/sub_trees/BT_return_sub.py) — OneShot(Sequence([NavigateToVertex("충전소입구"), AlignToDock, ReverseIntoDock, **VerifyDockingContact**])). 빌더가 waypoints.yaml 의 충전소입구 vertex.yaw 를 blackboard.CHARGING_DOCK_TARGET_YAW 로 자동 주입. ReverseIntoDock 완료 후 VerifyDockingContact 가 `docked` trigger 자동 발사 → CHARGING 전이. 6 빌더 테스트 통과 (tests/test_gogoping_return_subtree_builder.py). ⚠ **알려진 이슈** — RETURNING 중 cancel 시 robot 즉시 안 멈춤 + 경로 잔상 ([trees/BT_return_sub.md 의 "알려진 이슈" 섹션](trees/BT_return_sub.md#알려진-이슈--cancel-cleanup-2026-05-18) 참조) |

### Stub (_stubs/) — 1 / 5 (+ 4 🟡)

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

### common/ — 7 / 11

| Behavior | 상태 | 파일 |
|---|---|---|
| battery_full_monitor | ✅ | [battery_full_monitor.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/common/battery_full_monitor.py) — BT_charging_main 에 배치, 부팅 시 CHARGING → IDLE 자동 전이 (BATTERY_LEVEL init=100.0 가정) |
| battery_low_monitor | ✅ | [battery_low_monitor.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/common/battery_low_monitor.py) — hysteresis 20% 진입 / 25% 진출, edge-triggered. BT_idle/assist/play/returning_main 4개 배치 (RETURNING 은 LOW_BATTERY_RETURN escalation). 5 시나리오 통과 |
| idle_timeout_monitor | ✅ | [idle_timeout_monitor.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/common/idle_timeout_monitor.py) — IDLE 진입 후 ROS param `idle_timeout_seconds` (기본 60s) 경과 시 `idle_timeout` trigger. edge-triggered, `initialise()` 에서 timer 리셋. BT_idle_main 만 배치. 6 시나리오 통과 |
| hardware_health_monitor | ☐ | |
| collision_event_handler | ☐ | |
| map_boundary_monitor | ✅ | [map_boundary_monitor.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/common/map_boundary_monitor.py) — blackboard.ROBOT_POSE 읽고 `map_cache.is_outside(x, y)` → 박스 밖 또는 unknown 셀이면 `fault(reason="out_of_map")` 발화. **7 트리 배치** (CHARGING/IDLE/ASSIST/PLAY/MANUAL/RETURNING/LOW_BATTERY_RETURN, ERROR 만 제외). MANUAL 은 다른 monitor 와 달리 위치 안전 예외로 포함. 발화 시 blackboard.ERROR_REASON / ERROR_SOURCE 도 세팅. 7 시나리오 통과 |
| command_listener | ✅ | [command_listener.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/common/command_listener.py) — `SetGoal.srv` + `ForceState.srv` 2개 서버 호스팅. SetGoal → `goal_reconciler` 호출. ForceState → `fsm.force_state()` + sub_task blackboard 세팅 (ASSIST→assist_task, PLAY→play_task). unit test 7 + reconciler 13 |
| docking_contact_check | ☐ | |
| check_task | ✅ | [check_task.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/common/check_task.py) — TaskSelector 분기 Condition. 5 시나리오 통과 |
| check_carry_mode | ☐ | BT_carry_sub 작성 시 |
| ui_publish | ☐ | HideAndSeek / Lullaby 작성 시 |

### navigation/ — 1 / 8

| Behavior | 상태 | 파일 |
|---|---|---|
| **navigate_to_vertex** | ✅ | [navigate_to_vertex.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/navigation/navigate_to_vertex.py) — graph_router action client. import 검증만, BT 통합 동작 검증 미실시 |
| navigate_to_pose | ☐ | |
| align_to_dock | ✅ | [align_to_dock.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/navigation/align_to_dock.py) — blackboard ROBOT_POSE.yaw vs CHARGING_DOCK_TARGET_YAW 비교 → cmd_vel.angular.z publish. 9 단위 테스트 통과 (tests/test_gogoping_align_to_dock.py) |
| reverse_into_dock | ✅ | [reverse_into_dock.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/navigation/reverse_into_dock.py) — N초 동안 cmd_vel.linear.x 후진 publish → SUCCESS. 명세상 `approach_dock` 자리 (디자인상 이름 변경). 8 단위 테스트 통과 (tests/test_gogoping_reverse_into_dock.py) |
| verify_docking_contact | ✅ | [verify_docking_contact.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/navigation/verify_docking_contact.py) — ReverseIntoDock 완료 후 `docked` trigger 1회 발사 → CHARGING 자동 전이. 자동 도킹 센서 미구현이라 현재 시간 기반 후진만으로 도킹 간주. 5 단위 테스트 통과 (tests/test_gogoping_verify_docking_contact.py) |
| manual_torque_hold | ✅ | [manual_torque_hold.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/manual/manual_torque_hold.py) — initialise 에서 `/gogoping/set_torque` (SetBool data=False) 호출로 motor disable, terminate 에서 enable 복원. blackboard `MANUAL_TORQUE_ACTIVE` W. BT_manual_main 만 배치. 6 시나리오 통과 (tests/test_gogoping_manual_torque_hold.py). 의존 interface: [BaseDriverClient](../../src/gogoping/gogoping_modes/gogoping_modes/interfaces/base_driver_client.py) |
| stop_base | ☐ | |
| maintain_distance | ☐ | |
| check_arrival | ☐ | |

### perception/ — 0 / 5

| Behavior | 상태 |
|---|---|
| is_target_visible | ☐ |
| detect_target_person | ☐ |
| found_child | ☐ |
| child_face_tracker | ☐ |
| load_stability_check | ☐ |

### follow/ — 0 / 4

| Behavior | 상태 |
|---|---|
| face_tracking | ☐ |
| wait_for_reappear | ☐ |
| raise_camera_pan | ☐ |
| pan_camera_sweep | ☐ |

### manual/ — 1 / 3

| Behavior | 상태 |
|---|---|
| manual_torque_hold | ✅ |
| enable_manual_control | ☐ |
| wait_for_exit | ☐ |

### recovery/ — 0 / 3

| Behavior | 상태 |
|---|---|
| stop_all_motors | ☐ |
| notify_admin_ui | ☐ |
| log_error_to_db | ☐ |

---

## 인프라 / 외부 시스템 — 29 / 32

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
| nav2 stack (실물) | 🟡 | localization 만 — map_server + AMCL + lifecycle_manager (`localization_real.launch.xml` + `nav2_params_real.yaml`). planner / controller / bt_navigator 는 추후 |
| `device-gogoping-laptop.sh` | ✅ | graph-router + **localization** + modes 3 window. nav2 navigation / vision 미포함 |
| `device-gogoping-sim.sh` | ✅ | gazebo + graph-router + modes + rviz self-contained |
| ROS msg/srv 계약 (gogoping_msgs) | ✅ | `Goal.msg` / `GoalStatus.msg` / `SetGoal.srv` / `ForceState.srv` / `SetBatteryLevel.srv` / `SetRobotPose.srv` / `SetGazeboPose.srv` (CMakeLists 등록 완료) |
| BatterySubscriber (real) | ✅ | [battery_subscriber.py](../../src/gogoping/gogoping_modes/gogoping_modes/interfaces/battery_subscriber.py) — `/gogoping/battery` (sensor_msgs/BatteryState) 구독. `percentage * 100 → Keys.BATTERY_LEVEL`. NaN 시 직전 값 유지 |
| PoseSubscriber (real) | ✅ | [pose_subscriber.py](../../src/gogoping/gogoping_modes/gogoping_modes/interfaces/pose_subscriber.py) — `/amcl_pose` (geometry_msgs/PoseWithCovarianceStamped, **map frame**) 구독. AMCL 가 publisher. quaternion → yaw atan2 변환 → `Keys.ROBOT_POSE = {x, y, yaw}`. RViz 2D Pose Estimate 정상 영향. POSE_OVERRIDE_ACTIVE flag 체크 |
| MapCache (real) | ✅ | [map_cache.py](../../src/gogoping/gogoping_modes/gogoping_modes/interfaces/map_cache.py) — `/map` (절대 경로, root namespace) OccupancyGrid 구독. **transient_local + reliable QoS** (nav2_map_server 와 일치). `is_outside(x, y)` 메서드 — 격자 박스 밖 또는 unknown 셀이면 True, 맵 미수신 시 None |
| sim_battery_node | ✅ | [gogoping_bringup/sim_battery_node.py](../../../gogoping-controller/src/gogoping/gogoping_bringup/gogoping_bringup/sim_battery_node.py) — **sim 전용**. `/gogoping/battery` 1Hz publish + `/gogoping/sim/set_battery_level` srv. device-gogoping-sim.sh 가 자동 실행 |
| sim_teleport_node | ✅ | [gogoping_bringup/sim_teleport_node.py](../../../gogoping-controller/src/gogoping/gogoping_bringup/gogoping_bringup/sim_teleport_node.py) — **sim 전용**. `/gogoping/sim/teleport_pose` srv + `/initialpose` sub (PoseWithCovarianceStamped) → subprocess 로 `gz service -s /world/pingdergarten/set_pose` 호출 → 가제보 entity 텔레포트. `/initialpose` 미러로 admin UI 맵 Shift+클릭 / RViz 2D Pose Estimate 시 자동 Gazebo 동기화. ROS param `world_name` / `entity_name` / `z` / `timeout_ms` |
| battery_publisher_node | 🟡 | [gogoping_bringup/battery_publisher_node.py](../../../gogoping-controller/src/gogoping/gogoping_bringup/gogoping_bringup/battery_publisher_node.py) — **Pi 운영용**. `pi.launch.py` 안 `PushRosNamespace("gogoping")` 그룹에 등록 → `/gogoping/battery` 1Hz. ROS param `source` 으로 `static`/`sysfs`/`uart` 선택. **현재 source=static (placeholder 100%)** — 진짜 ADC 통합은 하드웨어 spec 확정 후 TODO |
| Control Service `/api/gogoping/debug/battery` | ✅ | BatteryDebugSlider → state_client → POST → ros_bridge.set_battery_level_sync → `SetBatteryLevel.srv` |
| Admin UI BatteryDebugSlider | ✅ | BTStateInline 디버그 영역. QSlider(0-100) + 현재값 라벨 + 적용. 임계점 (low 20/25, full 70) 표시. sim 환경 전용 (실물엔 `service_unavailable`) |
| Admin UI GogoPingDashboard 실 배터리 표시 | ✅ | header `battery_chip` (StatChip) + 시스템 카드 `battery` (BatteryBar) 둘 다 snapshot.battery_level 로 라이브 갱신. **실물에서도 동작** (BatterySubscriber → blackboard → snapshot → WS → dashboard) |
| Admin UI MapStatusCard (좌표 + IN/OUT) | ✅ | ODOM 카드 옆 (slim) — 배지 (🟢 IN MAP / 🔴 OUT OF MAP / ⚪ UNKNOWN) + 좌표 (x/y/yaw) 표시만. [widgets/map_status_card.py](../../../../app/admin-app/widgets/map_status_card.py) |
| Admin UI PoseDebugPanel | ✅ | BTStateInline 디버그 영역 (DebugStatePanel + BatteryDebugSlider 옆). x/y/yaw QDoubleSpinBox + 적용 + 원복. [widgets/pose_debug_panel.py](../../../../app/admin-app/widgets/pose_debug_panel.py) |
| Debug 좌표 override (SetRobotPose + SetGazeboPose + /initialpose) | ✅ | admin UI 적용 → POST `/api/gogoping/debug/pose` → router 가 **셋 다 호출**: (1) `bridge.set_robot_pose_sync` → command_listener server (SW override, blackboard.ROBOT_POSE 강제 + POSE_OVERRIDE_ACTIVE=True). (2) `bridge.set_gazebo_pose_sync` → sim_teleport_node (가제보 entity 텔레포트, sim 만, 실물은 service_unavailable). (3) `waypoints_bridge.set_initial_pose` → `/initialpose` publish (AMCL 재초기화 + RViz robot frame 이동, sim/실물 동일). 원복 = SW override 해제만 (Gazebo / `/initialpose` 둘 다 skip). |
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
| gogoping_camera_pan `servo_bridge` node | ✅ | [servo_bridge.py](../../src/gogoping/gogoping_camera_pan/gogoping_camera_pan/servo_bridge.py) + [firmware](../../src/gogoping/gogoping_camera_pan/firmware/servo_bridge/servo_bridge.ino) — Arduino Uno + MG995 ×2 (pan D9, tilt D10). 시리얼 (`/dev/arduino-camera`, 115200, `PT:`/`OK:` 라인) ↔ `~/cmd_pan`/`~/cmd_tilt` (Float32) 구독, `~/state` (JointState) publish. clamp (pan 5~175°, tilt 30~150°) + rate_limit + 20Hz state 재송신 (펌웨어 1000ms watchdog 대응). 패키지 문서 — [src/gogoping/gogoping_camera_pan/CLAUDE.md](../../src/gogoping/gogoping_camera_pan/CLAUDE.md) |
| gogoping_camera_pan `keyboard_teleop` node | ✅ | [keyboard_teleop.py](../../src/gogoping/gogoping_camera_pan/gogoping_camera_pan/keyboard_teleop.py) — 터미널 raw stdin teleop (a/d=pan, w/s=tilt, space=center, [/]=step 조절). TTY 필요해서 `ros2 run` 으로 실행. BT 통합 전 수동 보정용 |
| gogoping_camera_pan `pan_scanner` node | ✅ | [pan_scanner.py](../../src/gogoping/gogoping_camera_pan/gogoping_camera_pan/pan_scanner.py) — 자동 sin sweep (`/cmd_pan` publish). keyboard_teleop 과 동시 사용 X. BT 의 `pan_camera_sweep` behavior 와는 별도 (이쪽은 dev 도구) |
| Control Service `/api/camera_pan/cmd` + `/camera_pan/state` WS | ✅ | [service/control-service/control_service/camera_pan/{ros_bridge,router}.py](../../../../service/control-service/control_service/camera_pan/ros_bridge.py) — POST cmd → `~/cmd_pan`/`~/cmd_tilt` publish, WS `/camera_pan/state` 로 JointState fan-out. Admin UI 가 사용 |
| Admin UI CameraPanCard | ✅ | [widgets/camera_pan_card.py](../../../../app/admin-app/widgets/camera_pan_card.py) — 글로벌 단축키 W/A/S/D=pan·tilt±, C=center (text 입력 위젯 안에선 무시). 카드 포커스 시 화살표·Space 도 동작. 30Hz smooth tick. [services/camera_pan_client.py](../../../../app/admin-app/services/camera_pan_client.py) 가 control-service WS 와 통신 |

---

## 갱신 컨벤션

새 behavior/트리 코드 추가 시 본 파일의 ☐ 를 ✅ 또는 🟡 로 변경 + 같은 commit 으로 [README.md](README.md), file-structure.md, 카테고리 .md 와 함께 업데이트.
