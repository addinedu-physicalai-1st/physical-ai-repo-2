# 컨벤션 (모든 main / sub 트리 공통)

- **Monitor / Guard behavior** (`battery_*_monitor`, `hardware_health_monitor`, `collision_event_handler`, `command_listener` 등):
  - 이벤트 감지 시 → blackboard 세팅 + `context.fsm.trigger(이벤트, **kwargs)` 호출 + **RUNNING 리턴**
  - 정상 시 → **RUNNING 유지** (SUCCESS / FAILURE 리턴 금지)
  - edge-triggered: 직전 값과 비교, 같은 trigger 를 매 tick 반복 호출하지 않음
- **Action behavior** (`navigate_to_pose`, `verify_docking_contact`, `enable_manual_control`, `ui_publish`, `pan_camera_sweep` 등):
  - 작업 완료 → SUCCESS, 실패 → FAILURE 리턴 (정상 BT 규약)
  - trigger 호출도 가능 (예: `verify_docking_contact` 가 `docked` trigger 발사 후 SUCCESS)
  - `terminate(new_status)` 는 **idempotent** — 진행 중 외부 작업 cancel
- **MainTree root SUCCESS** (ASSIST/PLAY 한정) = task 완료. `main.py` 의 spin 루프가 감지 후 `assist_done` / `play_done` trigger 발사 + 트리 swap.
  CHARGING / IDLE / RETURNING / LOW_BATTERY_RETURN / ERROR 의 MainTree 는 root SUCCESS 가 task 완료 의미 아님 — state 전이는 trigger 발화 (`battery_*` / `docked` / `fault` / `*_request`) 가 담당.
  ERROR / LOW_BATTERY_RETURN 은 lockdown — 사용자 명령 차단 (CommandListener 미배치). reset trigger 없음.
- **MainTree root FAILURE** → `main.py._on_tree_failure()` 가 `return_request` trigger 발사 → RETURNING 으로 도피 (예: FollowSubTree Loss Recovery 끝까지 실패)
- 자세한 trigger 이름·시그니처: [fsm-triggers.md](fsm-triggers.md)
- 자세한 blackboard 키: [blackboard-schema.md](blackboard-schema.md)
- **Active mode 직접 전이** — `assist_request` / `play_request` / `manual_request` 는 IDLE 뿐 아니라 *다른 active mode* 에서도 발화 가능 (예: ASSIST 중 PLAY 누르면 직접 PLAY 로). BT swap 1회로 처리되며 `terminate(INVALID)` 가 이전 트리의 시간-구속 cleanup 보장 (ManualTorqueHold 의 torque ON 복원, NavigateToPose 의 nav2 goal cancel 등). 따라서 모든 behavior 의 `terminate()` 는 **idempotent + cleanup-complete** 해야 함.

---

CHARGING
  main: Parallel
        ├─ BatteryFullMonitor     (✅ ≥ 70% → battery_full → IDLE)
        ├─ MapBoundaryMonitor     (✅ amcl 미스로컬라이즈 / 누군가 들고 옮긴 케이스 안전망)
        ├─ HardwareHealthMonitor  (✅ LIDAR/odom staleness → fault)
        ├─ DockingContactCheck    (추후)
        └─ CommandListener        (✅)
  sub: 없음


IDLE
  main: Parallel
        ├─ BatteryLowMonitor      (✅ — battery ≤ 20% → battery_low → RETURNING)
        ├─ IdleTimeoutMonitor     (✅ — idle_timeout_seconds 경과 → idle_timeout → RETURNING)
        ├─ MapBoundaryMonitor     (✅ — 비정상 pose 감지 → fault)
        ├─ HardwareHealthMonitor  (✅ LIDAR/odom staleness → fault)
        └─ CommandListener        (✅)
  sub: 없음


ASSIST
  main: Parallel (SuccessOnSelected=[TaskSelector])
        ├─ BatteryLowMonitor      (✅ ≤20% → battery_low → RETURNING)
        ├─ MapBoundaryMonitor     (✅ OccupancyGrid 기반 → fault(reason="out_of_map") → ERROR)
        ├─ HardwareHealthMonitor  (✅ LIDAR/odom staleness → fault)
        ├─ CollisionEventHandler  (추후)
        ├─ CommandListener        (✅)  ※ cancel 외 active mode 전이 (assist/play/manual_request) 도 가능
        │
        └─ TaskSelector (Selector, memory=False)
              ├─ Sequence: CheckTask("carry")   → CarrySubTree     (stub)
              ├─ Sequence: CheckTask("follow")  → FollowSubTree    (stub) ※ ASSIST 직속 단독 추종
              └─ Sequence: CheckTask("lullaby") → LullabySubTree   (✅) ※ 교사 명령 — ASSIST 에 분류
                                                                     (아이 자발적 놀이 = PLAY)


PLAY
  main: Parallel (SuccessOnSelected=[TaskSelector])
        ├─ BatteryLowMonitor      (✅)
        ├─ MapBoundaryMonitor     (✅)
        ├─ HardwareHealthMonitor  (✅ LIDAR/odom staleness → fault)
        ├─ CollisionEventHandler  (추후)
        ├─ CommandListener        (✅)  ※ cancel / 다른 active mode 전이
        │
        └─ TaskSelector (Selector, memory=False)
              └─ Sequence: CheckTask("hideseek") → HideAndSeekSubTree (stub) ※ 1회 실행 후 종료


MANUAL
  main: Parallel
        ├─ ManualTorqueHold        (✅ initialise=torque OFF service 호출, terminate=torque ON 복원)
        ├─ MapBoundaryMonitor      (✅ — 위치 안전 예외)
        └─ CommandListener         (✅ — cancel / return_request / 다른 *_request)
  sub: 없음

  ※ MANUAL 은 task 가 없는 *상태* — 로봇이 가만히 서있고 torque 만 풀려 있음.
    의도적으로 *대부분의 자동 감지 monitor 미배치* — 사용자가 직접 제어:
      - BatteryLowMonitor 없음 (battery_low → MANUAL 무효) — 자동 빼앗김 방지
      - HardwareHealthMonitor 없음 (fault 의미 약함) — 토크 OFF
      - CollisionEventHandler 없음 — 토크 OFF 라 자율 충돌 위험 없음
    예외 — **MapBoundaryMonitor 만 배치**:
      사용자가 들고 옮기다 맵 경계 넘으면 nav2 가 path planning 불가하므로 즉시 ERROR 알림.
    이탈 경로:
      - 사용자 명시 명령: cancel / return_request / 다른 *_request
      - 자동 fault: MapBoundaryMonitor 발화 (out_of_map)
    cancel / return_request / fault 시 ManualTorqueHold.terminate() 가 torque ON 복원.


RETURNING
  main: Parallel (SuccessOnSelected=[ReturnSubTree])
        ├─ BatteryLowMonitor      (✅ — escalation: 또 떨어지면 LOW_BATTERY_RETURN)
        ├─ MapBoundaryMonitor     (✅ — 도크 복귀 중 맵 밖 이탈 시 fault(reason="out_of_map"))
        ├─ HardwareHealthMonitor  (✅ LIDAR/odom staleness → fault)
        ├─ CollisionEventHandler  (추후)
        ├─ CommandListener        (✅ — 사용자 cancel / *_request)
        └─ ReturnSubTree          (✅ — OneShot(Sequence))

  sub: ReturnSubTree = OneShot(ON_COMPLETION) of:
        Sequence (memory=True)
          ├─ NavigateToVertex("충전소입구")  (✅ — graph_router 액션)
          ├─ AlignToDock                     (✅ — CHARGING_DOCK_TARGET_YAW 까지 제자리 회전)
          ├─ ReverseIntoDock                  (✅ — N초 cmd_vel.linear.x 후진)
          └─ VerifyDockingContact             (✅ — docked trigger 자동 발사 → CHARGING)


LOW_BATTERY_RETURN
  main: Parallel(SuccessOnAll)
        ├─ MapBoundaryMonitor     (✅ — 도크 복귀 중 맵 경계 이탈 시 fault)
        ├─ HardwareHealthMonitor  (✅ LIDAR/odom staleness → fault)
        ├─ CollisionEventHandler  (추후)
        └─ ReturnSubTree          (✅ — RETURNING 과 동일 SubTree 재사용)
  sub: ReturnSubTree (✅ — 위 RETURNING sub 와 동일)

  ※ lockdown 정책 정확히:
      - *사용자 명령* 차단 (CommandListener 미배치 — SetGoal 거부)
      - *안전 monitor* 는 정상 배치 (자율 ERROR 전이 가능)
    이탈 경로: docked → CHARGING / fault → ERROR 만.
    battery_low escalation 진입 — RETURNING 도중 배터리 떨어져도 본 state 로 강제 전환.


ERROR
  main: Parallel(SuccessOnAll)
        └─ StopAllMotors          (✅ initialise=cmd_vel=0 + release_torque, 1 tick SUCCESS)
  sub: 없음

  ※ ERROR 는 terminal — reset trigger 없음. 사람이 robot 재시작해야 복구.
    NotifyAdminUI / LogErrorToDB 는 추후 — Sequence 로 확장 예정.
    Emergency Stop 진입 경로: `/gogoping/emergency_stop` (std_srvs/Trigger) →
    command_listener → fsm.force_state("ERROR") → BT_error_main 빌드 →
    StopAllMotors.initialise() 가 cmd_vel=0 + torque OFF 즉시 실행.