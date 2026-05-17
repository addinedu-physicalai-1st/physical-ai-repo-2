controller/gogoping-controller/src/gogoping/
├── gogoping_bringup/
│   ├── launch/
│   │   ├── pi.launch.py                  # 라즈베리파이 (vicpinky_bringup + sllidar + camera + battery_publisher_node)
│   │   └── laptop.launch.py              # 노트북 (Nav2 + modes + vision)
│   └── gogoping_bringup/
│       ├── sim_status_publisher.py       # sim 활성 신호 1Hz (Bool /gogoping/sim_active)
│       ├── sim_battery_node.py           # sim 전용 — /gogoping/battery + SetBatteryLevel.srv
│       └── battery_publisher_node.py     # Pi 운영용 — /gogoping/battery (source: static/sysfs/uart)
│                                         #   하드웨어 spec 확정 후 source=sysfs/uart 로 전환
│
├── gogoping_camera/                      # USB 카메라 → UDP MJPEG 송출
├── gogoping_camera_pan/                  # Arduino 서보 (pyserial, UI/BT 양쪽 사용, 우선순위 토픽 분리)
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
        │   ├── blackboard.py             # 공유 변수 스키마 + 초기값 (Keys 상수, 권한 등록)
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
        │   │   │   │                                 #   Used in: BT_assist/play/returning_main (MANUAL 제외)
        │   │   │   ├── hardware_health_monitor.[py|/] # 센서/모터 응답 끊김 감지 → "fault" trigger
        │   │   │   │                                 #   Used in: BT_charging_main, BT_idle_main, BT_assist_main,
        │   │   │   │                                 #            BT_play_main, BT_returning_main
        │   │   │   ├── collision_event_handler.[py|/] # Nav2 Collision Monitor 비정상 상태 → "fault" trigger
        │   │   │   │                                 #   Used in: BT_assist_main, BT_play_main, BT_returning_main
        │   │   │   ├── command_listener.[py|/]       # 외부 명령 수신 → blackboard 세팅 + fsm.trigger 호출
        │   │   │   │                                 #   Used in: BT_idle_main, BT_assist_main, BT_play_main
        │   │   │   ├── docking_contact_check.[py|/]  # 도킹 접점 전류 흐름 감시, 끊김 시 fault
        │   │   │   │                                 #   Used in: BT_charging_main
        │   │   │   ├── check_task.[py|/]             # blackboard.assist_task/play_task 값 비교
        │   │   │   │                                 #   Used in: BT_assist_main, BT_play_main (TaskSelector 분기)
        │   │   │   ├── check_carry_mode.[py|/]       # blackboard.carry_mode 값 비교 (manual/goto/follow)
        │   │   │   │                                 #   Used in: BT_carry_sub (CarryCore 분기)
        │   │   │   └── ui_publish.[py|/]             # 범용 UI 알림 publish (announce / countdown_start 등)
        │   │   │                                     # message dict 만 다르게 전달, 즉시 SUCCESS
        │   │   │                                     #   Used in: BT_hide_and_seek_sub, BT_carry_sub (goto/manual), BT_lullaby_sub
        │   │   │
        │   │   ├── navigation/
        │   │   │   ├── __init__.py
        │   │   │   ├── navigate_to_pose.[py|/]       # Nav2 navigate_to_pose 액션 클라이언트 (target_key 인자)
        │   │   │   │                                 #   Used in: BT_carry_sub, BT_hide_and_seek_sub, BT_return_sub
        │   │   │   ├── navigate_to_vertex.py         # graph_router NavigateToVertex 액션 호출 (target_vertex_name 인자)
        │   │   │   │                                 #   다익스트라 lane 따라 이동. 자세한 설계: docs/graph-routing.md
        │   │   │   │                                 #   Used in: BT_carry_sub (goto), BT_assist_main 의 named-pose 이동
        │   │   │   ├── align_to_dock.[py|/]          # 도킹 정면 정렬 [스켈레톤]
        │   │   │   │                                 #   Used in: BT_return_sub
        │   │   │   ├── approach_dock.[py|/]          # 저속 직진으로 도킹 진입 [스켈레톤]
        │   │   │   │                                 #   Used in: BT_return_sub
        │   │   │   ├── verify_docking_contact.[py|/] # 도킹 접점 확인 → "docked" trigger [스켈레톤]
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
        │   │   │   └── load_stability_check.[py|/]   # 짐 떨어짐 감지 (manual 모드일 때 비활성)
        │   │   │                                     #   Used in: BT_carry_sub
        │   │   │
        │   │   ├── follow/               # 카메라 pan 제어 + 추종 관련
        │   │   │   ├── __init__.py
        │   │   │   ├── face_tracking.[py|/]          # 얼굴 좌표 → 카메라 pan 각도 계산 (gogoping_camera_pan 호출)
        │   │   │   │                                 #   Used in: BT_follow_sub
        │   │   │   ├── wait_for_reappear.[py|/]      # target_visible = True 될 때까지 timeout 까지 RUNNING
        │   │   │   │                                 #   Used in: BT_follow_sub
        │   │   │   ├── raise_camera_pan.[py|/]       # 카메라 각도 올림 (carry/follow 시작 시)
        │   │   │   │                                 #   Used in: BT_carry_sub (goto mode), BT_follow_sub
        │   │   │   └── pan_camera_sweep.[py|/]       # 카메라 pan 좌우 sweep (탐색용)
        │   │   │                                     #   Used in: BT_follow_sub, BT_hide_and_seek_sub
        │   │   │
        │   │   ├── manual/
        │   │   │   ├── __init__.py
        │   │   │   ├── enable_manual_control.[py|/]  # camera_pan 우선순위 manual 전환 (terminate 시 auto 복원)
        │   │   │   │                                 #   Used in: BT_carry_sub (manual mode)
        │   │   │   └── wait_for_exit.[py|/]          # carry_mode 변경 / cancel 명령까지 RUNNING
        │   │   │                                     #   Used in: BT_carry_sub (manual mode)
        │   │   │
        │   │   ├── recovery/
        │   │   │   ├── __init__.py
        │   │   │   ├── stop_all_motors.[py|/]        # cmd_vel = 0 (안전 정지)
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
        │   │       ├── stub_carry.py                # BT_carry_sub 자리 — 30 tick stub (carry+goto 목적지 도달 SUCCESS 의미)
        │   │       ├── stub_follow.py               # BT_follow_sub 자리 — 무한 RUNNING (사람 보이는 한 RUNNING 의미)
        │   │       ├── stub_lullaby.py              # BT_lullaby_sub 자리 — 무한 RUNNING (사용자 stop 까지 RUNNING 의미)
        │   │       └── stub_hideseek.py             # BT_hide_and_seek_sub 자리 — 30 tick stub (1회 사이클 SUCCESS 의미)
        │   │
        │   └── trees/                    # BT 트리 조립 (한 파일 = 한 트리 전체)
        │       ├── __init__.py
        │       │
        │       ├── main_trees/           # FSM state 별 MainTree (총 8개)
        │       │   ├── __init__.py                       # build_main_tree(state, ctx) dispatcher
        │       │   ├── BT_charging_main.py               # CHARGING — BatteryFullMonitor + CommandListener
        │       │   ├── BT_idle_main.py                   # IDLE — CommandListener
        │       │   ├── BT_assist_main.py                 # ASSIST — CommandListener + TaskSelector(carry/follow/lullaby stubs)
        │       │   ├── BT_play_main.py                   # PLAY — CommandListener + TaskSelector(hideseek stub)
        │       │   ├── BT_manual_main.py                 # MANUAL — CommandListener (torque off 는 추후)
        │       │   ├── BT_returning_main.py              # RETURNING — CommandListener
        │       │   ├── BT_low_battery_return_main.py    # LOW_BATTERY_RETURN — 빈 lockdown (CommandListener 없음)
        │       │   └── BT_error_main.py                  # ERROR — 빈 terminal (reset 없음)
        │       │
        │       └── sub_trees/            # 작업별 SubTree (총 5개)
        │           ├── __init__.py
        │           ├── BT_carry_sub.py           # 운반 — 3가지 서브모드 (manual/goto/follow)
        │           ├── BT_follow_sub.py          # 추종 — 정상 ↔ Loss Recovery (제자리 탐색)
        │           ├── BT_lullaby_sub.py         # 자장가 — WaitForExit (UI 가 mp3 재생)
        │           ├── BT_hide_and_seek_sub.py   # 숨바꼭질 (1회 실행) — 숨기 → 카운트 → 탐색 → 복귀
        │           └── BT_return_sub.py          # 도킹 복귀 시퀀스 (NavTo → Align → Approach → Verify)
        │
        ├── interfaces/                   # 외부 HW / ROS action·service·topic 호출 래퍼
        │   ├── __init__.py
        │   ├── nav2_client.py            # Nav2 NavigateToPose 액션 클라이언트  (stub)
        │   ├── camera_pan_client.py      # gogoping_camera_pan 토픽 publish 래퍼 (/camera_pan/auto)  (stub)
        │   ├── ui_publisher.py           # robot-web / admin-app 로 상태 publish  (✅ 실 구현 — `/gogoping/state` 1Hz)
        │   ├── battery_subscriber.py     # /gogoping/battery 구독 (sensor_msgs/BatteryState)
        │   │                             #   → blackboard.BATTERY_LEVEL 갱신 (✅)
        │   ├── odom_subscriber.py        # /gogoping/odom 구독 (nav_msgs/Odometry)
        │   │                             #   → blackboard.ROBOT_POSE {x, y, yaw} (✅)
        │   ├── map_cache.py              # /map 구독 (OccupancyGrid, transient_local QoS, 절대경로)
        │   │                             #   is_outside(x, y) 메서드 노출 (✅)
        │   ├── collision_subscriber.py   # Collision Monitor 상태 토픽 구독  (stub)
        │   └── db_logger.py              # error_log 테이블 INSERT  (stub)
        │
        └── utils/                        # 공통 helper / 순수 함수
            ├── __init__.py
            ├── waypoints_client.py       # control-server REST 에서 patrol 가져오기 (hide-and-seek 등)
            ├── goal_reconciler.py        # SetGoal Goal → 적절한 FSM trigger 매핑 (순수 함수,
            │                             #   command_listener 가 import. ROS 의존성 0 → 단위 테스트 13 pass)
            └── tree_inspector.py         # snapshot(fsm_state, root_tree) → admin BTStateInline 호환 dict
            
            
            
fsm/states/        → bt/trees/main_trees/
main_trees/        → bt/trees/sub_trees/, bt/behaviors/
sub_trees/         → bt/trees/sub_trees/ (재사용), bt/behaviors/
behaviors/         → interfaces/, bt/blackboard.py
interfaces/        → rclpy + ROS 토픽/액션/서비스    
            
            