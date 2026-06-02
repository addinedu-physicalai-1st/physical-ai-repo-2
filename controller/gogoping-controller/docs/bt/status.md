# BT 구현 체크리스트

코드 구현 vs 명세(스켈레톤). docs 작성/계획만 된 항목과 실제 동작하는 항목 구분.

마지막 업데이트: 2026-05-25 (평탄화 리팩터링 — 8 state→10 state. ASSIST/PLAY/TaskSelector/CheckTask 삭제. GOTO/FOLLOW/LULLABY/HIDEANDSEEK 각 독립 MainTree 추가. `_shell.py` shell helper 신규. `main.py` task_done 단일 trigger. `Goal.msg` target_state 단일 필드. 직전 (2026-05-22) — patrol 빌딩블록 + BT_patrol_sub + SelectVertex + PanCameraSweep)

## 범례
- ✅ 구현 완료 (동작 검증)
- 🟡 부분 구현 (스켈레톤 파일 있음 — stub 의미 동등성 검증, 진짜 동작 미검증)
- ☐ 미구현 (코드 X, 명세만)

## 진행률 (✅ / 전체 — 🟡 / ☐ 미포함)

| 영역 | 진행 | 비고 |
|---|---|---|
| **Trees** | **14 / 15** + 1 빌딩블록 | MainTree 10/10 ✅ · SubTree 4/5 (BT_return_sub ✅ · BT_lullaby_sub ✅ · BT_goto_sub ✅ · **BT_hide_and_seek_sub ✅ patrol-only** · BT_follow_sub ☐) · **빌딩 블록 BT_patrol_sub ✅** |
| **Stubs (_stubs/)** | **1 / 2** | base ✅ · stub_follow 🟡 · stub_hideseek 🗑 (삭제 예정) |
| **Behaviors** | **15 / 29** | common 8/9 · navigation 4/8 · perception 0/4 · follow 1/4 · manual 1/1 · recovery 1/3 (check_task 삭제 반영) |
| **Infrastructure** | **40 / 42** | 🟡 2 (nav2 실물 localization-only / battery_publisher_node static placeholder). camera_pan_client 실 구현 포함 |
| **합계** | **70 / 88** | 평탄화 완료. TaskSelector/CheckTask 제거 → behavior count -2 |

---

## Trees

### MainTree — 10 / 10

모든 MainTree 는 `bt/trees/main_trees/_shell.py` 의 `build_active_main_tree()` helper 로 조립.
task state (GOTO/FOLLOW/LULLABY/HIDEANDSEEK) 는 `task_body=True`, 나머지는 `task_body=False`.

| 트리 | 상태 | 비고 |
|---|---|---|
| BT_charging_main | ✅ | `task_body=False`. Parallel(BatteryFullMonitor + MapBoundaryMonitor + HardwareHealthMonitor + CommandListener). 부팅 시 첫 tick 에 battery_full → IDLE 자동 전이 |
| BT_idle_main | ✅ | `task_body=False`. Parallel(BatteryLowMonitor + IdleTimeoutMonitor + MapBoundaryMonitor + HardwareHealthMonitor + CommandListener). docs — [trees/BT_idle_main.md](trees/BT_idle_main.md) |
| BT_goto_main | ✅ | `task_body=True`. Parallel(BatteryLowMonitor + MapBoundaryMonitor + HardwareHealthMonitor + CollisionMonitor + CommandListener + GotoSubTree). body SUCCESS → task_done → IDLE |
| BT_follow_main | ✅ | `task_body=True`. Parallel(BatteryLowMonitor + MapBoundaryMonitor + HardwareHealthMonitor + CommandListener + FollowSubTree(stub)). BT_follow_sub 미완성 — StubFollow 대체 |
| BT_lullaby_main | ✅ | `task_body=True`. Parallel(BatteryLowMonitor + MapBoundaryMonitor + HardwareHealthMonitor + CommandListener + LullabySubTree). body SUCCESS → task_done → IDLE |
| BT_hide_and_seek_main | ✅ | `task_body=True`. Parallel(BatteryLowMonitor + MapBoundaryMonitor + HardwareHealthMonitor + CollisionMonitor + CommandListener + HideAndSeekSubTree). body SUCCESS → task_done → IDLE |
| BT_manual_main | ✅ | `task_body=False`. Parallel(ManualTorqueHold + MapBoundaryMonitor + CommandListener). torque OFF/ON 라이프사이클 ✅. battery·HW·collision monitor 미배치 — 위치 안전(MapBoundary)만 예외적 배치. docs — [trees/BT_manual_main.md](trees/BT_manual_main.md) |
| BT_returning_main | ✅ | `task_body=False`. Parallel(BatteryLowMonitor + MapBoundaryMonitor + HardwareHealthMonitor + CollisionMonitor + CommandListener + ReturnSubTree). escalation — RETURNING 중 배터리 떨어지면 LOW_BATTERY_RETURNING. |
| BT_low_battery_returning_main | ✅ | `task_body=False`. Parallel(MapBoundaryMonitor + HardwareHealthMonitor + CollisionMonitor(→fault) + ReturnSubTree) — lockdown (CommandListener 없음, 사용자 명령 차단). ReturnSubTree 동일 (RETURNING 과 공유). docs — [trees/BT_low_battery_returning_main.md](trees/BT_low_battery_returning_main.md) |
| BT_error_main | ✅ | `task_body=False`. Parallel(StopAllMotors). 진입 즉시 cmd_vel=0 + torque OFF. terminal — 사람이 재시작. docs — [trees/BT_error_main.md](trees/BT_error_main.md) |

**삭제됨** (평탄화 리팩터링 2026-05-25):
- ~~BT_assist_main~~ — GOTO/FOLLOW/LULLABY 각 MainTree 로 분리
- ~~BT_play_main~~ — BT_hide_and_seek_main 으로 승격
- ~~TaskSelector~~ — 각 task state 가 독립 BT 를 가지므로 불필요
- ~~shell helper `_shell.py`~~ (신규 추가 ✅)

> **walking skeleton 단계**: 10 트리 골격 + CommandListener / 일부 monitor 동작. 진짜 SubTree 미완성분 (follow) 는 `_stubs/` 임시 placeholder. main.py 의 BT swap 루프가 FSM state 변화에 맞춰 트리를 교체 — 10 state 모두 진입/이탈 검증 가능 (force_state 디버그 포함).

### SubTree — 4 / 5 (+ 1 빌딩 블록)

| 트리 | 상태 | 비고 |
|---|---|---|
| BT_goto_sub | ✅ | Sequence(NavigateToVertex + UIPublish) — 단일 vertex 이동. 운반은 user 가 follow + goto chain | [trees/BT_goto_sub.md](trees/BT_goto_sub.md) |
| BT_follow_sub | ☐ | StubFollow 로 대체 중. 정상 ↔ Loss Recovery |
| BT_lullaby_sub | ✅ | [BT_lullaby_sub.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/trees/sub_trees/BT_lullaby_sub.py) — 단일 LullabyAudio leaf. initialise=lullaby_play event publish, update=RUNNING, terminate=lullaby_stop publish (idempotent). 빌더 2 + LullabyAudio 7 테스트 통과 |
| BT_hide_and_seek_sub | ✅ | [BT_hide_and_seek_sub.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/trees/sub_trees/BT_hide_and_seek_sub.py) — `build_hide_and_seek_sub(ctx)` 빌더. BB.search_waypoints 읽어 `build_patrol_sub(ctx, wps)` 반환. **patrol-only 첫 구현** — 진짜 hideseek (인식/FOUND) 확장 ☐. 5 빌더 테스트 통과 |
| BT_patrol_sub | ✅ | **빌딩 블록 (mode/task 단위 SubTree 아님)** — [BT_patrol_sub.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/trees/sub_trees/BT_patrol_sub.py). `build_patrol_sub(ctx, waypoints)` 로 vertex 마다 `FailureIsSuccess(Sequence(SelectVertex + NavigateToVertex + PanCameraSweep))` 동적 생성. 9 빌더 테스트 통과. 현재 어디에도 결선되지 않음 — 호출자가 사용 |
| BT_return_sub | ✅ | [BT_return_sub.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/trees/sub_trees/BT_return_sub.py) — OneShot(Sequence([NavigateToVertex("충전소입구"), AlignToDock, ReverseIntoDock, **VerifyDockingContact**])). 빌더가 waypoints.yaml 의 충전소입구 vertex.yaw 를 blackboard.CHARGING_DOCK_TARGET_YAW 로 자동 주입. ReverseIntoDock 완료 후 VerifyDockingContact 가 `docked` trigger 자동 발사 → CHARGING 전이. 6 빌더 테스트 통과 (tests/test_gogoping_return_subtree_builder.py). ⚠ **알려진 이슈** — RETURNING 중 cancel 시 robot 즉시 안 멈춤 + 경로 잔상 ([trees/BT_return_sub.md 의 "알려진 이슈" 섹션](trees/BT_return_sub.md#알려진-이슈--cancel-cleanup-2026-05-18) 참조) |

### Stub (_stubs/) — 1 / 3 (+ 2 🟡)

walking skeleton 단계의 임시 placeholder. 진짜 SubTree 작성 시 폴더째 삭제 + 사용처 (BT_assist_main / BT_play_main) 교체. `grep -rn "STUB:" controller/gogoping-controller/` 로 검색.

| 파일 | 상태 | 의미상 동등성 |
|---|---|---|
| `_stubs/_base.py` | ✅ | `StubRunningThenSuccess` (N tick → SUCCESS) + `StubInfiniteRunning` (항상 RUNNING) |
| `_stubs/stub_follow.py` | 🟡 | `StubInfiniteRunning`. 진짜 follow 의 "사람 보이는 한 RUNNING" 의미와 동등 |
| `_stubs/stub_hideseek.py` | 🗑 | **사용 안 함** — BT_play_main 이 `build_hide_and_seek_sub(ctx)` 호출하도록 교체됨. 파일은 잔존 (다른 stub 정리 시 함께 삭제 예정) |

---

## Behaviors

### common/ — 8 / 9

| Behavior | 상태 | 파일 |
|---|---|---|
| select_vertex | ✅ | [select_vertex.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/common/select_vertex.py) — 고정 vertex 이름을 BB.target_vertex_name 에 W 후 즉시 SUCCESS. NavigateToVertex 와 짝. 5 단위 테스트 통과 (tests/test_gogoping_select_vertex.py). Used in: BT_patrol_sub |
| battery_full_monitor | ✅ | [battery_full_monitor.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/common/battery_full_monitor.py) — BT_charging_main 에 배치, 부팅 시 CHARGING → IDLE 자동 전이 (BATTERY_LEVEL init=100.0 가정) |
| battery_low_monitor | ✅ | [battery_low_monitor.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/common/battery_low_monitor.py) — hysteresis 20% 진입 / 25% 진출, edge-triggered. BT_idle/goto/follow/lullaby/hideandseek/returning_main 6개 배치 (RETURNING 은 LOW_BATTERY_RETURNING escalation). 5 시나리오 통과 |
| idle_timeout_monitor | ✅ | [idle_timeout_monitor.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/common/idle_timeout_monitor.py) — IDLE 진입 후 ROS param `idle_timeout_seconds` (기본 60s) 경과 시 `idle_timeout` trigger. edge-triggered, `initialise()` 에서 timer 리셋. BT_idle_main 만 배치. 6 시나리오 통과 |
| hardware_health_monitor | ✅ | [hardware_health_monitor.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/common/hardware_health_monitor.py) — LIDAR `/gogoping/scan` + odom `/gogoping/odom` 두 토픽 직접 subscribe. 마지막 수신 시각 ROS param `hw_health_staleness_seconds` (기본 3.0s) 초과 시 `fault(reason="lidar_timeout" / "odom_timeout")` 발화. **8 트리 배치** (CHARGING/IDLE/GOTO/FOLLOW/LULLABY/HIDEANDSEEK/RETURNING/LOW_BATTERY_RETURNING — MANUAL/ERROR 제외). `initialise()` 가 _last_* 를 *현재 시각* 으로 초기화해 부팅 직후 grace period 보장 + edge-triggered (`_fired` 플래그). blackboard ERROR_REASON / ERROR_SOURCE W |
| collision_monitor (leaf) | ✅ | [collision_monitor.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/common/collision_monitor.py) — `collision_subscriber`(`/collision_monitor_state` → `COLLISION_STATE`)가 "stop" 인 상태 5분 지속 시 발화: LOW_BATTERY_RETURNING → `fault`(ERROR), 그 외(GOTO/RETURNING/HIDEANDSEEK) → `cancel`(IDLE). 데이터 plane nav2 `collision_monitor` 노드가 controller 출력(cmd_vel_nav)을 LiDAR stop zone 으로 gate. **4 트리 배치** (GOTO/RETURNING/LOW_BATTERY_RETURNING/HIDEANDSEEK — FOLLOW/LULLABY 제외). edge-triggered (`_fired`) |
| map_boundary_monitor | ✅ | [map_boundary_monitor.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/common/map_boundary_monitor.py) — blackboard.ROBOT_POSE 읽고 `map_cache.is_outside(x, y)` → 박스 밖 또는 unknown 셀이면 `fault(reason="out_of_map")` 발화. **9 트리 배치** (CHARGING/IDLE/GOTO/FOLLOW/LULLABY/HIDEANDSEEK/MANUAL/RETURNING/LOW_BATTERY_RETURNING, ERROR 만 제외). MANUAL 은 다른 monitor 와 달리 위치 안전 예외로 포함. 발화 시 blackboard.ERROR_REASON / ERROR_SOURCE 도 세팅. 7 시나리오 통과 |
| command_listener | ✅ | [command_listener.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/common/command_listener.py) — `SetGoal.srv` + `ForceState.srv` 2개 서버 호스팅. SetGoal → `goal_reconciler` 호출 (Goal.msg.target_state 단일 필드). ForceState → `fsm.force_state(target_state)`. Goal.msg.`search_waypoints` 도 dict 로 전달 → reconciler 가 hideseek 시 BB W. unit test 7 + reconciler 8 |
| docking_contact_check | ☐ | |
| ~~check_task~~ | 🗑 **삭제** | TaskSelector 제거로 불필요. 2026-05-25 평탄화 리팩터링 |
| ui_publish | ✅ | [ui_publish.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/common/ui_publish.py) — `message: dict` 1회 publish 후 즉시 SUCCESS. 5 단위 테스트 통과 |
| lullaby_audio | ✅ | [lullaby_audio.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/common/lullaby_audio.py) — initialise=play publish / update=RUNNING / terminate=stop publish (idempotent). BT_lullaby_sub 의 단일 leaf. 7 단위 테스트 통과 |

### navigation/ — 4 / 8

| Behavior | 상태 | 파일 |
|---|---|---|
| **navigate_to_vertex** | ✅ | [navigate_to_vertex.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/navigation/navigate_to_vertex.py) — graph_router action client. import 검증만, BT 통합 동작 검증 미실시 |
| navigate_to_pose | ☐ | |
| align_to_dock | ✅ | [align_to_dock.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/navigation/align_to_dock.py) — blackboard ROBOT_POSE.yaw vs CHARGING_DOCK_TARGET_YAW 비교 → cmd_vel.angular.z publish. 9 단위 테스트 통과 (tests/test_gogoping_align_to_dock.py) |
| reverse_into_dock | ✅ | [reverse_into_dock.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/navigation/reverse_into_dock.py) — N초 동안 cmd_vel.linear.x 후진 publish → SUCCESS. 명세상 `approach_dock` 자리 (디자인상 이름 변경). 8 단위 테스트 통과 (tests/test_gogoping_reverse_into_dock.py) |
| verify_docking_contact | ✅ | [verify_docking_contact.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/navigation/verify_docking_contact.py) — ReverseIntoDock 완료 후 `docked` trigger 1회 발사 → CHARGING 자동 전이. 자동 도킹 센서 미구현이라 현재 시간 기반 후진만으로 도킹 간주. 5 단위 테스트 통과 (tests/test_gogoping_verify_docking_contact.py) |
| stop_base | ☐ | |
| maintain_distance | ☐ | |
| check_arrival | ☐ | |

### perception/ — 0 / 4

| Behavior | 상태 |
|---|---|
| is_target_visible | ☐ |
| detect_target_person | ☐ |
| found_child | ☐ |
| child_face_tracker | ☐ |

### follow/ — 1 / 4

| Behavior | 상태 | 파일 |
|---|---|---|
| face_tracking | ☐ | |
| wait_for_reappear | ☐ | |
| raise_camera_pan | ☐ | |
| pan_camera_sweep | ✅ | [pan_camera_sweep.py](../../src/gogoping/gogoping_modes/gogoping_modes/bt/behaviors/follow/pan_camera_sweep.py) — 시간 기반 시퀀스 (90→30→150→90, 1.5s × 4). ctx.camera_pan.publish_pan() 호출. terminate(INVALID) 시 center() 1회. `now_fn` 주입형 시간 (테스트용). 13 단위 테스트 통과 (tests/test_gogoping_pan_camera_sweep.py). Used in: BT_patrol_sub |

### manual/ — 1 / 1

| Behavior | 상태 |
|---|---|
| manual_torque_hold | ✅ |

### recovery/ — 1 / 3

| Behavior | 상태 |
|---|---|
| stop_all_motors | ✅ |
| notify_admin_ui | ☐ |
| log_error_to_db | ☐ |

---

## 인프라 / 외부 시스템 — 40 / 42

| 항목 | 상태 | 비고 |
|---|---|---|
| FSM (robot_fsm.py) | ✅ | 10 state (IDLE/CHARGING/GOTO/FOLLOW/LULLABY/HIDEANDSEEK/MANUAL/RETURNING/**LOW_BATTERY_RETURNING**/ERROR) + 13 transition + `force_state(target)` debug API |
| FSM `force_state(target)` debug | ✅ | `fsm.machine.set_state()` + 수동 `_after_state_change()` 호출로 transition 우회. admin DebugStatePanel 진입점 |
| Goal 기반 reconciler (goal_reconciler.py) | ✅ | 순수 함수 — 현재 state ↔ Goal.target_state 차이 보고 적절한 trigger 매핑. ROS 의존성 0 → 단위 테스트 13 pass. ERROR / LOW_BATTERY_RETURNING lockdown 처리. ASSIST/PLAY 분기 → 10-state 직접 매핑으로 재작성 |
| Tree inspector (tree_inspector.py) | ✅ | `snapshot(fsm_state, root_tree)` → admin BTStateInline 호환 dict. **battery_level 키** 포함 (blackboard.BATTERY_LEVEL 읽음) |
| Context (context.py) | ✅ | `@dataclass(frozen=True)` — node / fsm / 6 interfaces (`ui_publisher` + `camera_pan_client` 실 구현, 나머지 4 stub). camera_pan_client 는 `/servo_bridge/cmd_pan` (Float32) publisher — PanCameraSweep behavior 가 사용 |
| shell helper `_shell.py` | ✅ | `bt/trees/main_trees/_shell.py` — `build_active_main_tree(body, task_body, ctx, monitors)`. task state (`task_body=True`) 는 `SuccessOnSelected=[body]`, 기타 (`task_body=False`) 는 `SuccessOnAll`. monitor Parallel 셸 조립 중복 코드 제거 |
| main.py BT swap | ✅ | `GogopingModes` 노드 — INITIAL_STATE="CHARGING", TICK_HZ=10, PUBLISH_HZ=1. state 변화 시 트리 swap + 이전 트리 `shutdown()`. `_on_tree_success()` — task state 4개 (GOTO/FOLLOW/LULLABY/HIDEANDSEEK) 에서 root SUCCESS 감지 시 `task_done` trigger (단일 trigger 로 통합) |
| blackboard.py 스키마 | ✅ | 24 Keys + `init_blackboard()`. Access 권한 (READ/WRITE) 등록. ASSIST_TASK / PLAY_TASK 삭제 (평탄화 리팩터링) |
| graph.py (다익스트라) | ✅ | 14 단위 테스트 pass |
| graph_router_node | ✅ | service + action server 노출 |
| nav2 stack (sim) | ✅ | sim_with_nav2.launch.xml |
| nav2 stack (실물) | 🟡 | localization 만 — map_server + AMCL + lifecycle_manager (`localization_real.launch.xml` + `nav2_params_real.yaml`). planner / controller / bt_navigator 는 추후 |
| `device-gogoping-laptop.sh` | ✅ | graph-router + **localization** + modes 3 window. nav2 navigation / vision 미포함 |
| `device-gogoping-sim.sh` | ✅ | gazebo + graph-router + modes + rviz self-contained |
| ROS msg/srv 계약 (gogoping_msgs) | ✅ | `Goal.msg` (target_state 단일 필드) / `GoalStatus.msg` / `SetGoal.srv` / `ForceState.srv` (target_state 단일 필드, sub_task 삭제) / `SetBatteryLevel.srv` / `SetRobotPose.srv` / `SetGazeboPose.srv` (CMakeLists 등록 완료) |
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
| robot-web 음성 → goto_vertex | ✅ | "X로 가" / "복귀" 인식 → FSM 거치는 경로. "X로 가" 는 `/api/gogoping/goto_vertex` (→ Goal(target_state="GOTO", destination_key=X) → SetGoal.srv → fsm.trigger("goto_request")). "복귀" 는 `/api/gogoping/mode {mode:'복귀'}` (→ Goal(target_state="RETURNING") → fsm.trigger("return_request")). 둘 다 robot 이동 + state 전이. 분류기는 [service/ai-service/ai_service/hub.py](../../../../service/ai-service/ai_service/hub.py) `_try_goto_vertex` / `_is_return_text` |
| Control Service `/api/gogoping/mode` | ✅ | state_to_goal.py 매핑 (대기/이동/추종/자장가/숨바꼭질/수동/복귀) + ros_bridge.send_goal_sync |
| Control Service `/api/gogoping/debug/force-state` | ✅ | DebugStatePanel → state_client → POST → ros_bridge.force_state_sync → `ForceState.srv` |
| Control Service `GogopingRosBridge` | ✅ | SetGoal + ForceState 클라이언트 + `/gogoping/state` 토픽 구독 |
| Control Service `/ws/robot-state` | ✅ | gogoping state WS fan-out |
| Admin UI BTStateInline | ✅ | 3 cell (state/main/sub) + 임베디드 DebugStatePanel |
| Admin UI DebugStatePanel | ✅ | 🛑 긴급정지 빨간 버튼 (별도 row, 확인 없이 즉시) + 빠른 토글 [수동]/[주행] + state combo + 적용 버튼. 10 state 목록 직접 선택 (sub combo 없음 — 평탄화 반영) |
| Control Service `/api/gogoping/emergency_stop` | ✅ | DebugStatePanel 의 e-stop 버튼 → state_client.post_emergency_stop → POST → ros_bridge.emergency_stop_sync → `/gogoping/emergency_stop` (std_srvs/Trigger) → command_listener._on_emergency_stop_request → fsm.force_state("ERROR") → BT_error_main 의 StopAllMotors (cmd_vel=0 + torque OFF) |
| Robot-web shared/robots.json | ✅ | gogoping 모드 — 대기 / 이동 / 추종 / 자장가 / 숨바꼭질 / 수동 / 복귀 (평탄화 반영, 보조/놀이 그룹 제거) |
| gogoping_camera_pan `servo_bridge` node | ✅ | [servo_bridge.py](../../src/gogoping/gogoping_camera_pan/gogoping_camera_pan/servo_bridge.py) + [firmware](../../src/gogoping/gogoping_camera_pan/firmware/servo_bridge/servo_bridge.ino) — Arduino Uno + MG995 ×2 (pan D9, tilt D10). 시리얼 (`/dev/arduino-camera`, 115200, `PT:`/`OK:` 라인) ↔ `~/cmd_pan`/`~/cmd_tilt` (Float32) 구독, `~/state` (JointState) publish. clamp (pan 5~175°, tilt 30~150°) + rate_limit + 20Hz state 재송신 (펌웨어 1000ms watchdog 대응). 패키지 문서 — [src/gogoping/gogoping_camera_pan/CLAUDE.md](../../src/gogoping/gogoping_camera_pan/CLAUDE.md) |
| gogoping_camera_pan `keyboard_teleop` node | ✅ | [keyboard_teleop.py](../../src/gogoping/gogoping_camera_pan/gogoping_camera_pan/keyboard_teleop.py) — 터미널 raw stdin teleop (a/d=pan, w/s=tilt, space=center, [/]=step 조절). TTY 필요해서 `ros2 run` 으로 실행. BT 통합 전 수동 보정용 |
| gogoping_camera_pan `pan_scanner` node | ✅ | [pan_scanner.py](../../src/gogoping/gogoping_camera_pan/gogoping_camera_pan/pan_scanner.py) — 자동 sin sweep (`/cmd_pan` publish). keyboard_teleop 과 동시 사용 X. BT 의 `pan_camera_sweep` behavior 와는 별도 (이쪽은 dev 도구) |
| Control Service `/api/camera_pan/cmd` + `/camera_pan/state` WS | ✅ | [service/control-service/control_service/camera_pan/{ros_bridge,router}.py](../../../../service/control-service/control_service/camera_pan/ros_bridge.py) — POST cmd → `~/cmd_pan`/`~/cmd_tilt` publish, WS `/camera_pan/state` 로 JointState fan-out. Admin UI 가 사용 |
| Admin UI CameraPanCard | ✅ | [widgets/camera_pan_card.py](../../../../app/admin-app/widgets/camera_pan_card.py) — 글로벌 단축키 W/A/S/D=pan·tilt±, C=center (text 입력 위젯 안에선 무시). 카드 포커스 시 화살표·Space 도 동작. 30Hz smooth tick. [services/camera_pan_client.py](../../../../app/admin-app/services/camera_pan_client.py) 가 control-service WS 와 통신 |

---

## 갱신 컨벤션

새 behavior/트리 코드 추가 시 본 파일의 ☐ 를 ✅ 또는 🟡 로 변경 + 같은 commit 으로 [README.md](README.md), file-structure.md, 카테고리 .md 와 함께 업데이트.
