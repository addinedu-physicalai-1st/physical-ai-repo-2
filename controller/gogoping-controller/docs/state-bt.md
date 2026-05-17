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
  CHARGING / IDLE / RETURNING / ERROR 의 MainTree 는 root SUCCESS 가 task 완료 의미 아님 — state 전이는 trigger 발화 (`battery_*` / `docked` / `fault` / `reset` / `*_command`) 가 담당.
- **MainTree root FAILURE** → `main.py._on_tree_failure()` 가 `return_command` trigger 발사 → RETURNING 으로 도피 (예: FollowSubTree Loss Recovery 끝까지 실패)
- 자세한 trigger 이름·시그니처: [fsm-triggers.md](fsm-triggers.md)
- 자세한 blackboard 키: [blackboard-schema.md](blackboard-schema.md)

---

CHARGING
  main: Parallel
        ├─ BatteryFullMonitor
        ├─ HardwareHealthMonitor
        └─ DockingContactCheck
  sub: 없음


IDLE
  main: Parallel
        ├─ BatteryLowMonitor
        ├─ HardwareHealthMonitor
        └─ CommandListener
  sub: 없음


ASSIST
  main: Parallel (SuccessOnSelected=[TaskSelector])
        ├─ BatteryLowMonitor
        ├─ HardwareHealthMonitor
        ├─ CollisionEventHandler
        ├─ MapBoundaryMonitor           ※ 맵 밖 이탈 시 fault(reason="out_of_map")
        ├─ CommandListener              ※ 수신: cancel 만 유효
        │                                  (assist/play/return_command 은 IDLE 에서만)
        │
        └─ TaskSelector (Selector, memory=False)
              ├─ Sequence: CheckTask("carry")   → CarrySubTree
              ├─ Sequence: CheckTask("follow")  → FollowSubTree    ※ ASSIST 직속 단독 추종
              └─ Sequence: CheckTask("lullaby") → LullabySubTree   ※ 교사 명령 — ASSIST 에 분류
                                                                     (아이 자발적 놀이 = PLAY)


PLAY
  main: Parallel (SuccessOnSelected=[TaskSelector])
        ├─ BatteryLowMonitor
        ├─ HardwareHealthMonitor
        ├─ CollisionEventHandler
        ├─ MapBoundaryMonitor           ※ 맵 밖 이탈 시 fault(reason="out_of_map")
        ├─ CommandListener              ※ 수신: cancel 만 유효
        │
        └─ TaskSelector (Selector, memory=False)
              └─ Sequence: CheckTask("hideseek") → HideAndSeekSubTree   ※ 1회 실행 후 종료


MANUAL
  main: Parallel
        ├─ ManualTorqueHold        ※ initialise() 에서 torque OFF service 호출,
        │                            terminate() 에서 torque ON 복원. 매 tick RUNNING 유지.
        └─ CommandListener         ※ 수신: cancel / return_command 만 유효
                                      (assist/play/manual_command 은 IDLE 에서만)
  sub: 없음

  ※ MANUAL 은 task 가 없는 *상태* — 로봇이 가만히 서있고 torque 만 풀려 있음.
    의도적으로 *모든 자동 감지 monitor 미배치* — 사용자가 직접 제어:
      - BatteryLowMonitor 없음 (battery_low → MANUAL 무효) — 자동 빼앗김 방지
      - HardwareHealthMonitor 없음 (fault → MANUAL 무효) — 토크 OFF 라 의미 약함
      - CollisionEventHandler 없음 — 토크 OFF 라 자율 충돌 위험 없음
    이탈 경로는 오직 사용자 명시 명령 (cancel / return_command) 만.
    cancel / return_command 시 ManualTorqueHold.terminate() 가 torque ON 복원.


RETURNING
  main: Parallel (SuccessOnSelected=[ReturnSubTree])
        ├─ HardwareHealthMonitor
        ├─ CollisionEventHandler
        └─ MapBoundaryMonitor           ※ 도크 복귀 중 맵 밖 이탈 시 fault(reason="out_of_map")

  sub: ReturnSubTree (Sequence, memory=True)
        ├─ NavigateToPose(charging_dock_approach_key)
        ├─ AlignToDock                       [스켈레톤 — 발표는 수동 도킹]
        ├─ ApproachDock                      [스켈레톤]
        └─ VerifyDockingContact              [스켈레톤]


ERROR
  main: Parallel
        ├─ Sequence (StopAllMotors → NotifyAdminUI → LogErrorToDB)
        └─ CommandListener              ※ 수신: reset 만 유효
  sub: 없음

  ※ Sequence 가 1회 실행 후 SUCCESS 되어도 CommandListener 가 RUNNING 유지 →
    트리 전체는 RUNNING 으로 reset 명령 대기. reset trigger 시 main.py 가
    state 전이 + 트리 swap → IDLE 복귀. (시연 여부는 별도 결정 — 발표 1주 전)