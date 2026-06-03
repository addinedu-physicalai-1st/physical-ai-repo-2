controller/gogoping-controller/src/gogoping/
├── gogoping_bringup/
│   ├── launch/
│   │   ├── pi.launch.py                  # 라즈베리파이 (vicpinky_bringup + sllidar + camera + battery_publisher_node)
│   │   └── laptop.launch.py              # 노트북 (placeholder — device-gogoping-laptop.sh 가 직접 ros2 launch)
│   └── gogoping_bringup/
│       ├── sim_status_publisher.py       # sim 활성 신호 1Hz (Bool /gogoping/sim_active) (✅)
│       ├── sim_battery_node.py           # sim 전용 — /gogoping/battery + SetBatteryLevel.srv (✅)
│       ├── sim_teleport_node.py          # sim 전용 — /gogoping/sim/teleport_pose srv + (✅)
│       │                                 #   /initialpose 토픽 sub. subprocess gz set_pose
│       │                                 #   호출. admin UI 적용 버튼 / 맵 Shift+클릭 /
│       │                                 #   RViz 2D Pose Estimate 모두 자동 Gazebo 동기화
│       └── battery_publisher_node.py     # Pi 운영용 — /gogoping/battery (source: static/sysfs/uart) (🟡)
│                                         #   현재 source=static (placeholder 100%). 하드웨어 spec 확정 후 source=sysfs/uart 로 전환
│
├── gogoping_camera/                      # USB 카메라 → UDP MJPEG 송출
├── gogoping_camera_pan/                  # Arduino Uno + MG995 ×2 pan/tilt 서보 (pyserial, ~/cmd_pan·~/cmd_tilt Float32,
│                                         #   ~/state JointState). servo_bridge / keyboard_teleop / pan_scanner 3노드.
│                                         #   상세 — src/gogoping/gogoping_camera_pan/CLAUDE.md
├── gogoping_navigation/                  # Nav2 wrapper (params + maps + launch)
├── gogoping_vision/                      # YOLO / ReID(Deep SORT, OSNet) / face_recognition
├── gogoping_msgs/                        # .msg / .srv / .action 정의
│
└── gogoping_modes/                       # FSM + BT 통합 패키지
    ├── package.xml
    ├── setup.py
    │
    └── gogoping_modes/
        ├── __init__.py
        ├── main.py                       # rclpy.init + Node + FSM 인스턴스화 + spin
        ├── context.py                    # 공유 객체 저장소 (blackboard, interfaces, fsm 핸들)
        │
        ├── fsm/                          # 상태머신
        │   ├── __init__.py
        │   └── robot_fsm.py              # 8 states + 12 transition + force_state debug API
        │
        ├── bt/                           # Behavior Tree
        │   ├── __init__.py
        │   ├── blackboard.py             # 공유 변수 스키마 + 초기값 (Keys 상수, 권한 등록) (✅)
        │   ├── tree_inspector.py         # snapshot(fsm_state, root_tree) → admin BTStateInline 호환 dict (✅)
        │   │                             #   battery_level + robot_pose + in_map 포함. main.py 가 1Hz publish 시 호출
        │   │
        │   ├── behaviors/                # 개별 BT 노드 (Action / Condition)
        │   │   │                         # ※ 각 노드는 기본 .py 단일 파일, 복잡해지면 폴더로 전환 가능
        │   │   │                         #   (컨벤션 섹션 참조)
        │   │   ├── __init__.py
        │   │   │
        │   │   ├── common/
        │   │   │   ├── __init__.py
        │   │   │   ├── battery_full_monitor.[py|/]   # 배터리 ≥ 70% 감지 → "battery_full" trigger (✅)
        │   │   │   │                                 #   Used in: BT_charging_main
        │   │   │   ├── battery_low_monitor.[py|/]    # 배터리 ≤ 20% 감지 → "battery_low" trigger (✅)
        │   │   │   │                                 #   hysteresis 20/25, edge-triggered.
        │   │   │   │                                 #   Used in: BT_idle/assist/play/returning_main
        │   │   │   ├── idle_timeout_monitor.[py|/]   # IDLE N초 무명령 → "idle_timeout" trigger (✅)
        │   │   │   │                                 #   ROS param idle_timeout_seconds (기본 60s).
        │   │   │   │                                 #   Used in: BT_idle_main 만
        │   │   │   ├── map_boundary_monitor.[py|/]   # 로봇 pose 가 맵 영역 밖 → "fault" (✅)
        │   │   │   │                                 #   MapCache.is_outside(x,y) — 격자 박스 + unknown 셀 체크.
        │   │   │   │                                 #   Used in: 9 트리 (ERROR 만 제외 — CHARGING/IDLE/GOTO/FOLLOW/
        │   │   │   │                                 #            LULLABY/HIDEANDSEEK/MANUAL/RETURNING/LOW_BATTERY_RETURNING)
        │   │   │   ├── hardware_health_monitor.py    # LIDAR/odom staleness → "fault" trigger (✅)
        │   │   │   │                                 #   /gogoping/scan + /gogoping/odom 직접 sub.
        │   │   │   │                                 #   ROS param hw_health_staleness_seconds (기본 3.0s).
        │   │   │   │                                 #   Used in: 8 트리 (CHARGING/IDLE/GOTO/FOLLOW/LULLABY/
        │   │   │   │                                 #            HIDEANDSEEK/RETURNING/LOW_BATTERY_RETURNING — MANUAL/ERROR 제외)
        │   │   │   ├── collision_monitor.[py|/]       # COLLISION_STATE "stop" 5분 지속 → cancel(IDLE)/fault(ERROR). nav2 collision_monitor 노드 + collision_subscriber 연동 (✅)
        │   │   │   │                                 #   Used in (정책 ON): GOTO/FOLLOW/LULLABY/HIDEANDSEEK/RETURNING/LOW_BATTERY_RETURNING
        │   │   │   ├── command_listener.[py|/]       # 외부 명령 수신 → reconciler 호출 → fsm.trigger 자체 발화 (✅)
        │   │   │   │                                 #   SetGoal + ForceState + SetRobotPose + emergency_stop 4 server.
        │   │   │   │                                 #   Used in: CHARGING/IDLE/GOTO/FOLLOW/LULLABY/HIDEANDSEEK/MANUAL/RETURNING
        │   │   │   │                                 #   (LOW_BATTERY_RETURNING / ERROR 만 제외 — lockdown)
        │   │   │   ├── docking_contact_check.[py|/]  # 도킹 접점 전류 흐름 감시, 끊김 시 fault
        │   │   │   │                                 #   Used in: BT_charging_main
        │   │   │   └── ui_publish.[py|/]             # 범용 UI 알림 publish (announce / countdown_start 등) (✅)
        │   │   │                                     # message dict 1회 publish 후 즉시 SUCCESS
        │   │   │                                     #   Used in: BT_goto_sub (AnnounceArrival), BT_hide_and_seek_sub
        │   │   │
        │   │   ├── navigation/
        │   │   │   ├── __init__.py
        │   │   │   ├── navigate_to_pose.[py|/]       # Nav2 navigate_to_pose 액션 클라이언트 (target_key 인자)
        │   │   │   │                                 #   Used in: BT_hide_and_seek_sub, BT_return_sub
        │   │   │   ├── navigate_to_vertex.py         # graph_router NavigateToVertex 액션 호출 (target_vertex_name 인자) (✅)
        │   │   │   │                                 #   다익스트라 lane 따라 이동. 자세한 설계: docs/graph-routing.md
        │   │   │   │                                 #   Used in: BT_goto_sub, BT_return_sub, BT_patrol_sub
        │   │   │   ├── align_to_dock.py              # blackboard target yaw 까지 cmd_vel.angular.z 로 제자리 회전 (✅) → docs/bt/behaviors/navigation.md#align_to_dock
        │   │   │   │                                 #   Used in: BT_return_sub
        │   │   │   ├── reverse_into_dock.py          # N초 동안 cmd_vel.linear.x 음수 publish (후진 진입) (✅) → docs/bt/behaviors/navigation.md#reverse_into_dock
        │   │   │   │                                 #   Used in: BT_return_sub
        │   │   │   ├── verify_docking_contact.py    # ReverseIntoDock 완료 후 "docked" trigger 1회 발사 → CHARGING 전이 (접점 센서 미통합) (✅) → docs/bt/behaviors/navigation.md#verify_docking_contact
        │   │   │   │                                 #   Used in: BT_return_sub
        │   │   │   ├── stop_base.[py|/]              # cmd_vel = 0 publish (모바일 베이스 즉시 정지)
        │   │   │   │                                 #   Used in: BT_follow_sub
        │   │   │   ├── maintain_distance.[py|/]      # 목표 거리(1.5m) 유지 PD 컨트롤러 (cmd_vel + LiDAR fusion)
        │   │   │   │                                 #   Used in: BT_follow_sub
        │   │   │   └── check_arrival.[py|/]          # 추종 종료 조건 확인 (사용자 정지 / 목적지 도착)
        │   │   │                                     #   Used in: BT_follow_sub
        │   │   │
        │   │   ├── perception/           # gogoping_vision 토픽 → blackboard 어댑터 (이어주는 역할)
        │   │   │   ├── __init__.py
        │   │   │   ├── is_target_visible.[py|/]      # blackboard.target_visible 값 확인 (가벼운 Condition)
        │   │   │   │                                 #   Used in: BT_follow_sub
        │   │   │   ├── detect_target_person.[py|/]   # YOLO + ReID 추론 결과 구독, blackboard 업데이트
        │   │   │   │                                 #   Used in: BT_follow_sub
        │   │   │   ├── found_child.[py|/]            # blackboard.found 값 확인 (가벼운 Condition)
        │   │   │   │                                 #   Used in: BT_hide_and_seek_sub
        │   │   │   ├── child_face_tracker.[py|/]     # 놀이 상대 아이 얼굴 발견 시 blackboard.found = True
        │   │   │   │                                 #   Used in: BT_hide_and_seek_sub
        │   │   │
        │   │   ├── hide_and_seek/        # HIDEANDSEEK(숨바꼭질) 모드 전용 leaf
        │   │   │   ├── __init__.py
        │   │   │   ├── set_destination_key.py        # BB.DESTINATION_KEY = key 후 SUCCESS (✅)
        │   │   │   │                                 #   Used in: BT_hide_and_seek_sub
        │   │   │   ├── set_hideseek_phase.py         # BB.HIDESEEK_PHASE = phase 후 SUCCESS (✅)
        │   │   │   │                                 #   Used in: BT_hide_and_seek_sub
        │   │   │   ├── await_recruit_complete.py     # HIDESEEK_REGISTERED_IDS 비어있으면 RUNNING (✅)
        │   │   │   │                                 #   Used in: BT_hide_and_seek_sub 의 recruit step
        │   │   │   ├── countdown.py                  # N초 RUNNING 후 SUCCESS — 순수 시간 게이트 (✅)
        │   │   │   │                                 #   Used in: BT_hide_and_seek_sub 의 countdown step
        │   │   │   └── hide_seek_caught_monitor.py   # registered_ids ⊆ caught_ids 이면 SUCCESS (✅)
        │   │   │                                     #   Used in: BT_hide_and_seek_sub patrol/return parallel
        │   │   │
        │   │   ├── lullaby/              # LULLABY(자장가) 모드 전용 leaf
        │   │   │   ├── __init__.py
        │   │   │   └── lullaby_audio.py              # initialise=play publish, update=RUNNING (영구), terminate=stop publish (✅)
        │   │   │                                     #   /gogoping/ui_event 에 lullaby_play / lullaby_stop publish. idempotent.
        │   │   │                                     #   Used in: BT_lullaby_sub 만
        │   │   │
        │   │   ├── patrol/               # PATROL(순찰 빌딩블록) 전용 leaf
        │   │   │   ├── __init__.py
        │   │   │   └── select_vertex.py              # 고정 vertex 이름을 BB.target_vertex_name 에 W 후 SUCCESS (✅)
        │   │   │                                     #   NavigateToVertex 와 짝 — Sequence(SelectVertex + NavigateToVertex) 패턴
        │   │   │                                     #   Used in: BT_patrol_sub
        │   │   │
        │   │   ├── follow/               # 카메라 pan 제어 + 추종 관련
        │   │   │   ├── __init__.py
        │   │   │   ├── face_tracking.[py|/]          # 얼굴 좌표 → 카메라 pan 각도 계산 (gogoping_camera_pan 호출)
        │   │   │   │                                 #   Used in: BT_follow_sub
        │   │   │   ├── wait_for_reappear.[py|/]      # target_visible = True 될 때까지 timeout 까지 RUNNING
        │   │   │   │                                 #   Used in: BT_follow_sub
        │   │   │   ├── raise_camera_pan.[py|/]       # 카메라 각도 올림 (follow 시작 시)
        │   │   │   │                                 #   Used in: BT_follow_sub
        │   │   │   └── pan_camera_sweep.py           # 카메라 pan 시간 기반 시퀀스: 90→30→150→90 (1.5s × 4). terminate(INVALID) 시 90 복귀. ctx.camera_pan.publish_pan() 사용 (✅) → docs/bt/behaviors/follow.md#pan_camera_sweep
        │   │   │                                     #   Used in: BT_patrol_sub, BT_follow_sub (예정), BT_hide_and_seek_sub (예정)
        │   │   │
        │   │   ├── manual/
        │   │   │   ├── __init__.py
        │   │   │   ├── manual_torque_hold.[py|/]     # MANUAL 진입 시 motor torque OFF → 사용자 직접 밀기 가능 (✅)
        │   │   │   │                                 #   initialise=release, terminate=enable. blackboard MANUAL_TORQUE_ACTIVE W.
        │   │   │   │                                 #   ctx.base_driver (BaseDriverClient → /gogoping/set_torque) 사용.
        │   │   │   │                                 #   Used in: BT_manual_main 만
        │   │   │
        │   │   ├── recovery/
        │   │   │   ├── __init__.py
        │   │   │   ├── stop_all_motors.[py|/]        # cmd_vel=0 + torque OFF (긴급정지) (✅)
        │   │   │   │                                 #   ctx.cmd_vel_pub + ctx.base_driver 사용.
        │   │   │   │                                 #   /gogoping/emergency_stop (Trigger srv) →
        │   │   │   │                                 #   fsm.force_state("ERROR") → BT_error_main 빌드 →
        │   │   │   │                                 #   initialise 1회.
        │   │   │   │                                 #   Used in: BT_error_main
        │   │   │   ├── notify_admin_ui.[py|/]        # WebSocket 으로 에러 alert publish
        │   │   │   │                                 #   Used in: BT_error_main
        │   │   │   └── log_error_to_db.[py|/]        # error_log 테이블 INSERT (디버깅용)
        │   │   │                                     #   Used in: BT_error_main
        │   │   │
        │   │   └── _stubs/               # ★ walking skeleton 임시 placeholder.
        │   │       │                     #   진짜 SubTree 작성 후 폴더째 삭제.
        │   │       │                     #   grep -rn "STUB:" controller/gogoping-controller/ 로 검색.
        │   │       ├── __init__.py
        │   │       ├── _base.py                     # StubRunningThenSuccess (30 tick → SUCCESS) + StubInfiniteRunning (항상 RUNNING)
        │   │       ├── stub_follow.py               # ★ 사용 안 함(legacy) — FOLLOW body 는 FollowTrack(perception) 으로 대체됨. 파일만 잔존
        │   │       └── stub_hideseek.py             # ★ 사용 안 함(legacy) — BT_hide_and_seek_main 이 build_hide_and_seek_sub(ctx) 호출. 파일만 잔존
        │   │
        │   └── trees/                    # BT 트리 조립 (한 파일 = 한 트리 전체)
        │       ├── __init__.py
        │       │
        │       ├── main_trees/           # FSM state 별 MainTree (총 10개) — 모두 _shell.py 의 build_active_main_tree() 사용 (ERROR 만 예외)
        │       │   ├── __init__.py                       # build_main_tree(state, ctx) dispatcher — 10 state 매핑
        │       │   ├── _shell.py                         # build_active_main_tree(name, ctx, body, **flags) — monitor 셸 조립 helper (✅)
        │       │   ├── BT_charging_main.py               # CHARGING — BatteryFullMonitor + MapBoundary + HW + CommandListener (✅)
        │       │   ├── BT_idle_main.py                   # IDLE — BatteryLow + IdleTimeout + MapBoundary + HW + CommandListener (✅)
        │       │   ├── BT_goto_main.py                   # GOTO — task_body=True. body=BT_goto_sub (✅)
        │       │   ├── BT_follow_main.py                 # FOLLOW — task_body=True. body=FollowTrack (perception leaf, SubTree 아님) (✅)
        │       │   ├── BT_lullaby_main.py                # LULLABY — task_body=True. body=BT_lullaby_sub (LullabyAudio leaf, 영구 RUNNING) (✅)
        │       │   ├── BT_hide_and_seek_main.py          # HIDEANDSEEK — task_body=True. body=BT_hide_and_seek_sub (patrol-only) (✅)
        │       │   ├── BT_manual_main.py                 # MANUAL — Parallel(ManualTorqueHold + MapBoundaryMonitor + CommandListener). 자동 monitor 미배치 ✅
        │       │   ├── BT_returning_main.py              # RETURNING — BatteryLow + MapBoundary + HW + CommandListener + BT_return_sub (✅)
        │       │   ├── BT_low_battery_returning_main.py  # LOW_BATTERY_RETURNING — MapBoundary + HW + BT_return_sub. lockdown (CommandListener 없음) (✅)
        │       │   └── BT_error_main.py                  # ERROR — Parallel(StopAllMotors). 진입 즉시 cmd_vel=0 + torque OFF. terminal — 재시작만 회복 ✅
        │       │
        │       └── sub_trees/            # SubTree (실제 파일 5개: goto·hide_and_seek·lullaby·patrol·return). FOLLOW 은 SubTree 없음(FollowTrack leaf)
        │           ├── __init__.py
        │           ├── BT_goto_sub.py            # 이동 — Sequence(NavigateToVertex + UIPublish)
        │           ├── BT_lullaby_sub.py         # 자장가 — LullabyAudio 단일 leaf (UI 가 mp3 재생, BT 는 publish only) (✅)
        │           ├── BT_hide_and_seek_sub.py   # 숨바꼭질 — build_hide_and_seek_sub(ctx) (✅ patrol-only 첫 구현. BB.search_waypoints 읽어 build_patrol_sub 호출. 빈 리스트 Failure leaf). 진짜 hideseek (인식/FOUND) 확장 ☐ → docs/bt/trees/BT_hide_and_seek_sub.md
        │           ├── BT_patrol_sub.py          # ★ 빌딩 블록 (mode/task 단위 아님) — build_patrol_sub(ctx, waypoints) 로 vertex 마다 Sequence(SelectVertex + NavigateToVertex + PanCameraSweep) 동적 생성 + FailureIsSuccess 로 감싸 skip-on-failure (✅) → docs/bt/trees/BT_patrol_sub.md
        │           └── BT_return_sub.py          # 도킹 복귀 — OneShot(Sequence(NavTo "충전소입구" → AlignToDock → ReverseIntoDock → VerifyDockingContact)). 마지막 단계가 docked trigger 자동 발사 → CHARGING. 빌더가 yaml 의 vertex.yaw 를 blackboard.CHARGING_DOCK_TARGET_YAW 주입 → docs/bt/trees/BT_return_sub.md
        │
        ├── interfaces/                   # 외부 HW / ROS action·service·topic 호출 래퍼
        │   ├── __init__.py
        │   ├── nav2_client.py            # Nav2 NavigateToPose 액션 클라이언트  (stub)
        │   ├── camera_pan_client.py      # gogoping_camera_pan 토픽 publish 래퍼 — /servo_bridge/cmd_pan (Float32 deg) publisher. publish_pan(deg) clamp 5~175°, center() = 90°. PanCameraSweep behavior 가 사용 (✅)
        │   ├── ui_publisher.py           # robot-web / admin-app 로 상태 publish  (✅ 실 구현 — `/gogoping/state` 1Hz)
        │   ├── base_driver_client.py     # vic_pinky_bringup 의 /gogoping/set_torque (SetBool) 클라이언트
        │   │                             #   release_torque() / enable_torque() — ManualTorqueHold 가 사용 (✅)
        │   ├── battery_subscriber.py     # /gogoping/battery 구독 (sensor_msgs/BatteryState)
        │   │                             #   → blackboard.BATTERY_LEVEL 갱신 (✅)
        │   ├── pose_subscriber.py       # /amcl_pose 구독 (geometry_msgs/PoseWithCovarianceStamped, map frame)
        │   │                             #   → blackboard.ROBOT_POSE {x, y, yaw} (✅)
        │   ├── map_cache.py              # /map 구독 (OccupancyGrid, transient_local QoS, 절대경로)
        │   │                             #   is_outside(x, y) 메서드 노출 (✅)
        │   ├── collision_subscriber.py   # Collision Monitor 상태 토픽 구독  (stub)
        │   └── db_logger.py              # error_log 테이블 INSERT  (stub)
        │
        └── utils/                        # 공통 helper / 순수 함수
            ├── __init__.py
            ├── safety_flags.py           # 시연/디버그 안전 토글(disable_*_safety 등) 읽기 helper — 6곳에서 사용 (✅)
            ├── goal_reconciler.py        # SetGoal Goal → 적절한 FSM trigger 매핑 (순수 함수) (✅ command_listener 사용)
            └── waypoints_client.py       # ⚠️ orphan(미사용) — repo 어디서도 import 안 됨. control-server REST patrol 가져오기용으로 작성됐으나 현재 미연결
                                          #   command_listener 가 import. ROS 의존성 0 → 단위 테스트 13 pass
            
            
            
fsm/states/        → bt/trees/main_trees/
main_trees/        → bt/trees/sub_trees/, bt/behaviors/
sub_trees/         → bt/trees/sub_trees/ (재사용), bt/behaviors/
behaviors/         → interfaces/, bt/blackboard.py
interfaces/        → rclpy + ROS 토픽/액션/서비스    
            
            