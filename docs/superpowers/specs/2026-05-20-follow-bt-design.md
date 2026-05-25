# Follow BT — 추종 SubTree 디자인

날짜: 2026-05-20
브랜치: `kang/feat-BT-lullaby-carry` (자장가 BT 후속 — follow 도 같은 브랜치 또는 별도)
의존성 spec: `gogoping_msgs/TargetPerson.msg` + `FaceDetection.msg` (본 spec 에 포함)

## 1. 배경

ASSIST 의 3 task (carry / follow / lullaby) 중 **follow** = 교사를 1.5m 거리에서 추종.
현재 `_stubs/stub_follow.py` (StubInfiniteRunning) placeholder. ML vision (YOLO + ReID + face_recognition) 결과를 받아 cmd_vel 로 사람 추종 + 사람 잃으면 제자리에서 카메라 sweep + 못 찾으면 RETURNING 도피.

본 spec 은 **옵션 A — BT 골격 + behavior 단위 완성** 범위. ML 모델 / 실 vision 노드 자체는 별도 작업 (별도 패키지). 본 작업은:
1. vision 토픽 spec (gogoping_msgs/TargetPerson.msg, FaceDetection.msg) 정의
2. BT subscriber 작성 — vision publisher 가 같은 spec 으로 publish 만 하면 자동 연결
3. camera_pan_client 실 구현 (publish wrapper)
4. 9 behavior TDD 단위 구현
5. BT_follow_sub 빌더 + BT_assist_main 와이어

ML 모델 / 실 카메라 / sim 시연 (옵션 B/C) 은 후속 PR.

## 2. 목표 / 비목표

### 목표
- vision 토픽 publisher 가 `/gogoping/vision/target_person` + `/gogoping/vision/face_detection` 으로 publish 하면 BT 가 자동으로 사람을 추종 (cmd_vel publish + camera_pan 추적).
- 사람 잃으면 명세대로 3s 대기 → camera sweep → 7s 추가 대기 → 그래도 못 찾으면 FollowSubTree FAILURE → main.py 의 _on_tree_failure 가 return_request 발화 → RETURNING.
- 모든 cmd_vel publish 는 `terminate(INVALID)` 에서 cmd_vel=0 publish 보장 (자장가 BT 와 동일 cleanup 패턴, ManualTorqueHold 와 동일 BT swap 라이프사이클).
- camera_pan 은 follow 진입 시 살짝 위로 (사람 얼굴 높이) 올리고, lost 시 좌우 sweep, follow 종료 시 정면 (0°) 복원.

### 비목표
- gogoping_vision 패키지의 실 ML 노드 (YOLO/ReID/face_recognition) — 별도 PR.
- BT_carry_sub 의 follow mode 재사용 — memory: `carry: goto-only` 결정으로 carry 는 단순화됨, follow 재사용 폐기.
- Multi-target / 다인 추종 — 1인 (target_person_id) 만.
- BT 측 충돌 회피 — nav2 collision monitor / costmap 이 처리. 본 BT 는 단순 cmd_vel publish.
- 실 robot 검증 / sim 통합 시연 — 본 작업은 단위 테스트까지. 통합은 vision 노드 작성 후 별도.

## 3. 아키텍처 (decision summary)

| 결정 | 값 | 이유 |
|---|---|---|
| MaintainDistance 구현 | 직접 cmd_vel P 제어 (`ctx.cmd_vel_pub`) | RPP nav2 의 xy_goal_tolerance 0.3m / yaw 무시 정책상 1.5m 거리 유지 + 동적 추종 부적합. AlignToDock/ReverseIntoDock 의 검증된 cmd_vel 패턴 재사용 |
| P 게인 시작값 | `kp_linear=0.5`, `kp_angular=1.0` | 보수적 시작. ROS param 으로 노출, 실 검증 시 튜닝. linear_max=0.2 m/s (nav2 desired 와 일치) |
| Vic Pinky 회전 정책 | 직진+회전 동시 (제자리 회전 X) | URDF / nav2 의 `use_rotate_to_heading: false` 와 일치. MaintainDistance 가 linear=0 + angular!=0 publish 금지 — 최소 linear 0.05 동시 (또는 회전 자체 회피) |
| Vision 토픽 spec | `/gogoping/vision/target_person` (TargetPerson.msg) + `/gogoping/vision/face_detection` (FaceDetection.msg) | 신규 msg 2개. publisher 는 별도 PR. BT subscriber 가 spec 만으로 구독 가능 |
| Vision adapter 위치 | `interfaces/vision_subscriber.py` (신규) — HardwareHealthMonitor 패턴 적용 | behavior 가 ROS subscribe 직접 X. interface 가 blackboard W |
| DetectTargetPerson 의 의미 | "vision_subscriber 가 백그라운드로 blackboard 갱신" — behavior 는 단순 SUCCESS 리턴 (가독성용 placeholder) | 명세대로 두되 실 동작은 subscriber. behavior 자체는 noop. 단위 테스트는 update SUCCESS 만 |
| IsTargetVisible 의 의미 | Condition — `blackboard.target_visible == True` 면 SUCCESS, 아니면 FAILURE → Selector 가 Loss Recovery 진입 | CheckTask 패턴 재사용 |
| WaitForReappear timer | `time.monotonic()` 시작 시점 + ROS param `follow_loss_first_timeout_s` (기본 3.0), `follow_loss_second_timeout_s` (기본 7.0) | IdleTimeoutMonitor 패턴 |
| Camera raise 각도 | follow: tilt = `0.3 rad` (위로 ~17°, 사람 얼굴 높이 가정) — ROS param `follow_camera_tilt_rad` (기본 0.3) | 실 검증 시 튜닝 |
| Camera sweep 패턴 | pan ∈ [-1.0, +1.0 rad] sin sweep, period 4s, 1 cycle | `gogoping_camera_pan/pan_scanner.py` 참고하지만 BT 안에서 직접 구현 (외부 노드 의존 X) |
| Face tracking 게인 | bbox 중심 x-offset → pan delta. `kp_face_pan=0.001 rad/px` (1280px 가운데에서 ±10° 까지) | 보수적 시작. 실 검증 후 튜닝 |
| `interfaces/camera_pan_client.py` 실 구현 | `/gogoping/camera_pan/cmd_pan` + `/gogoping/camera_pan/cmd_tilt` Float32 publisher (이미 servo_bridge 가 구독 중) | servo_bridge 의 `~/cmd_pan`/`~/cmd_tilt` 는 namespace gogoping/camera_pan 으로 prefix |
| Loss recovery FAILURE 경로 | 명세대로 — Selector 의 끝 Failure 자식 → FollowSubTree FAILURE → main.py 의 `_on_tree_failure` 가 `return_request` 발화 → RETURNING | 이미 main.py 에 동작 중. 추가 작업 없음 |

## 4. 신규 ROS msg 정의

### 4.1 `gogoping_msgs/msg/TargetPerson.msg`

```
# YOLO + ReID 의 추적 결과 — 1명의 target person.
#
# publisher: gogoping_vision/person_tracker (별도 패키지, 별도 PR)
# subscriber: gogoping_modes/interfaces/vision_subscriber.py
# 주기: 10~30 Hz (vision 추론 속도)
#
# id 가 비어있으면 "추적 끊김" (사람은 frame 에 있지만 ReID 매칭 안 됨). 본 BT 는
# id == blackboard.target_person_id 인 경우만 따른다.

std_msgs/Header header           # frame_id = "camera_rgb_frame", stamp = capture 시각
string id                        # ReID person id (빈 문자열 = 매칭 실패)
float32 confidence               # 0.0~1.0
int32 bbox_x                     # 이미지 좌상단 기준 (px)
int32 bbox_y
int32 bbox_w
int32 bbox_h
geometry_msgs/Pose pose          # base_link frame — x=전방, y=좌, z=위
```

### 4.2 `gogoping_msgs/msg/FaceDetection.msg`

```
# face_recognition lib 의 얼굴 검출 결과 — 최근 가장 큰 얼굴 1개.
#
# publisher: gogoping_vision/face_tracker (별도 패키지)
# subscriber: gogoping_modes/bt/behaviors/follow/face_tracking.py 가 직접 구독
#   (간단한 흐름이라 별도 interface 안 두고 behavior 가 직접 — HardwareHealthMonitor 패턴)
# 주기: 10~30 Hz
#
# face_id 가 있으면 (face_recognition known face) 우선. 없어도 bbox 가 있으면 추적.

std_msgs/Header header           # frame_id = "camera_rgb_frame"
string face_id                   # known face id (빈 문자열 = 미식별)
int32 bbox_x
int32 bbox_y
int32 bbox_w
int32 bbox_h
```

## 5. 변경 범위 (Scope)

### 5.1 신규 / 수정 파일

| 파일 | 변경 | 책임 |
|---|---|---|
| `gogoping_msgs/msg/TargetPerson.msg` | **신규** | YOLO+ReID 추적 결과 spec |
| `gogoping_msgs/msg/FaceDetection.msg` | **신규** | 얼굴 검출 결과 spec |
| `gogoping_msgs/CMakeLists.txt` | **수정** | 두 msg 등록 |
| `interfaces/camera_pan_client.py` | **수정** (stub → 실 구현) | `set_pan(rad)`, `set_tilt(rad)`, `center()`, `sweep_step(t)` |
| `interfaces/vision_subscriber.py` | **신규** | `/gogoping/vision/target_person` 구독 → blackboard.TARGET_VISIBLE/TARGET_POSE/TARGET_PERSON_ID/TARGET_SEEN_AT W. id 매칭 필터 |
| `bt/behaviors/navigation/stop_base.py` | **신규** | cmd_vel=0 publish, 즉시 SUCCESS |
| `bt/behaviors/navigation/maintain_distance.py` | **신규** | TARGET_POSE → P 제어 → cmd_vel. 영구 RUNNING (외부 trigger 가 종료). terminate=0 publish |
| `bt/behaviors/navigation/check_arrival.py` | **신규** | 추종 종료 조건 (사용자 cancel 은 외부 처리이므로 본 behavior 는 거의 항상 FAILURE — 명세상 자리만) |
| `bt/behaviors/perception/is_target_visible.py` | **신규** | blackboard.TARGET_VISIBLE 비교 (CheckTask 패턴) |
| `bt/behaviors/perception/detect_target_person.py` | **신규** | 단순 SUCCESS — 실 동작은 vision_subscriber 가 백그라운드 |
| `bt/behaviors/follow/raise_camera_pan.py` | **신규** | `ctx.camera_pan.set_tilt(rad)` 1회 호출 후 SUCCESS |
| `bt/behaviors/follow/face_tracking.py` | **신규** | `/gogoping/vision/face_detection` 직접 구독, bbox x-offset → camera_pan delta. 매 tick RUNNING (Parallel 자식) |
| `bt/behaviors/follow/wait_for_reappear.py` | **신규** | TARGET_VISIBLE polling + timeout. SUCCESS (재발견) / FAILURE (timeout) / RUNNING (대기 중) |
| `bt/behaviors/follow/pan_camera_sweep.py` | **신규** | `ctx.camera_pan.sweep_step(t)` 매 tick 호출. SUCCESS=cycle 완료, RUNNING=진행 중 |
| `bt/trees/sub_trees/BT_follow_sub.py` | **신규** | `build_follow_subtree(ctx)` — Parallel(FaceTracking, FollowCore(Sequence(RaiseCameraPan, FollowLoop))) |
| `bt/trees/main_trees/BT_assist_main.py` | **수정** | `StubFollow()` → `build_follow_subtree(ctx)` 교체 |
| `bt/behaviors/_stubs/stub_follow.py` | **삭제** | |
| `bt/behaviors/_stubs/__init__.py` | **수정** | `StubFollow` export 제거 |
| `bt/blackboard.py` | **수정** (해당없음 — 모두 기존 키 사용) | TARGET_VISIBLE/TARGET_POSE/TARGET_PERSON_ID/TARGET_SEEN_AT 이미 정의됨 |
| `context.py` | **수정** | `camera_pan` interface 활성 (이미 필드 있음) — main.py 가 실 CameraPanClient 주입 |

### 5.2 테스트 (각 behavior 단위 + builder + interface)

| 파일 | 시나리오 수 | 핵심 검증 |
|---|---|---|
| `tests/test_gogoping_camera_pan_client.py` | 4 | publish_pan/tilt/center/sweep_step — Fake node + publisher 검증 |
| `tests/test_gogoping_vision_subscriber.py` | 5 | TargetPerson 메시지 수신 → blackboard W, id 매칭 필터, stale 처리 |
| `tests/test_gogoping_stop_base.py` | 3 | cmd_vel=0 publish, SUCCESS, terminate idempotent |
| `tests/test_gogoping_maintain_distance.py` | 7 | P 제어 (가까이/멀리/정면/좌/우), terminate cleanup, ROS param 적용, target_pose 없을 때 |
| `tests/test_gogoping_check_arrival.py` | 2 | 명세상 자리만 — 항상 FAILURE 또는 외부 신호 기반 |
| `tests/test_gogoping_is_target_visible.py` | 3 | True/False/missing key |
| `tests/test_gogoping_detect_target_person.py` | 1 | update SUCCESS (noop) |
| `tests/test_gogoping_raise_camera_pan.py` | 3 | set_tilt 호출 1회, SUCCESS, param 적용 |
| `tests/test_gogoping_face_tracking.py` | 5 | bbox 중앙/좌/우 → camera_pan delta, stale 메시지, no face |
| `tests/test_gogoping_wait_for_reappear.py` | 5 | TARGET_VISIBLE True → SUCCESS, timeout → FAILURE, 중간 변경, ROS param |
| `tests/test_gogoping_pan_camera_sweep.py` | 4 | sweep step 진행, cycle 완료 SUCCESS, 중단 시 cleanup |
| `tests/test_gogoping_follow_subtree_builder.py` | 4 | 빌더 구조 (Parallel + FollowCore + FollowLoop), 자식 타입 검증 |

**총: 약 46 시나리오**

### 5.3 문서 갱신

| 문서 | 변경 |
|---|---|
| `docs/bt/trees/BT_follow_sub.md` | placeholder → 완전 채움 (root composite + Loss recovery + trigger) |
| `docs/bt/behaviors/perception.md` | is_target_visible / detect_target_person 구현 섹션 |
| `docs/bt/behaviors/follow.md` | face_tracking / wait_for_reappear / raise_camera_pan / pan_camera_sweep 4개 구현 섹션 |
| `docs/bt/behaviors/navigation.md` | stop_base / maintain_distance / check_arrival 3개 구현 섹션 |
| `docs/bt/status.md` | Trees / Behaviors / Stubs 카운트 갱신 |
| `docs/gogoping-file-structure.md` | (✅) 마커 9개 추가 |
| `docs/blackboard-schema.md` | TARGET_* 키들의 W 컬럼 갱신 (vision_subscriber 추가) |

## 6. 컴포넌트 상세

### 6.1 `interfaces/camera_pan_client.py` (실 구현)

```python
"""gogoping_camera_pan/servo_bridge 의 cmd_pan/cmd_tilt 토픽 publish wrapper.

토픽 (절대 경로):
- /gogoping/camera_pan/cmd_pan (std_msgs/Float32, rad)
- /gogoping/camera_pan/cmd_tilt (std_msgs/Float32, rad)

servo_bridge 가 ~/cmd_pan / ~/cmd_tilt 로 구독 (namespace "gogoping/camera_pan").
clamp 범위: pan 5~175° = -85°~+85° 가운데? servo_bridge 가 5~175° 표기인지 확인.
일단 ±1.0 rad ≈ ±57° 안에서 동작 (안전 영역).
"""
from std_msgs.msg import Float32

class CameraPanClient:
    TOPIC_PAN = "/gogoping/camera_pan/cmd_pan"
    TOPIC_TILT = "/gogoping/camera_pan/cmd_tilt"

    def __init__(self, node):
        self.node = node
        self._pan_pub = node.create_publisher(Float32, self.TOPIC_PAN, 10)
        self._tilt_pub = node.create_publisher(Float32, self.TOPIC_TILT, 10)
        self._current_pan = 0.0
        self._current_tilt = 0.0
        self._sweep_t0 = None

    def set_pan(self, rad: float) -> None:
        rad = max(-1.0, min(1.0, rad))
        self._pan_pub.publish(Float32(data=rad))
        self._current_pan = rad

    def set_tilt(self, rad: float) -> None:
        rad = max(-0.5, min(0.5, rad))
        self._tilt_pub.publish(Float32(data=rad))
        self._current_tilt = rad

    def delta_pan(self, drad: float) -> None:
        self.set_pan(self._current_pan + drad)

    def center(self) -> None:
        self.set_pan(0.0)
        self.set_tilt(0.0)

    def sweep_step(self, period_sec: float = 4.0, amplitude_rad: float = 1.0) -> bool:
        """sin sweep 한 step — pan 만 (tilt 유지). 1 cycle 완료 시 True 리턴."""
        import math, time
        if self._sweep_t0 is None:
            self._sweep_t0 = time.monotonic()
        t = time.monotonic() - self._sweep_t0
        self.set_pan(amplitude_rad * math.sin(2 * math.pi * t / period_sec))
        if t >= period_sec:
            self._sweep_t0 = None
            return True  # cycle 완료
        return False

    def reset_sweep(self) -> None:
        self._sweep_t0 = None
```

### 6.2 `interfaces/vision_subscriber.py`

```python
"""/gogoping/vision/target_person 구독 → blackboard 갱신.

publisher (별도 패키지): gogoping_vision/person_tracker
주기: 10~30 Hz

수신 메시지의 id 가 blackboard.TARGET_PERSON_ID 와 일치 + confidence >= threshold 면:
- TARGET_VISIBLE = True
- TARGET_POSE = msg.pose dict
- TARGET_SEEN_AT = msg.header.stamp epoch

stale 검출: 별도 timer 가 매 0.5s 마다 TARGET_SEEN_AT 검사 → 0.5s 넘으면
TARGET_VISIBLE = False. 단순 timeout (별도 monitor behavior 안 만들고 subscriber 안에).
"""
```

(생략 — 자세한 구현은 plan 에서)

### 6.3 BT 구조

```python
def build_follow_subtree(ctx):
    # FollowLoop — 정상 ↔ Loss Recovery Selector
    normal_follow = Sequence("NormalFollow", memory=True, children=[
        IsTargetVisible("IsTargetVisible", ctx),
        DetectTargetPerson("DetectTargetPerson", ctx),     # noop SUCCESS
        MaintainDistance("MaintainDistance", ctx),         # RUNNING + cmd_vel
        CheckArrival("CheckArrival", ctx),
    ])

    find_target = Selector("FindTarget", memory=False, children=[
        WaitForReappear("WaitForReappearShort", ctx, timeout_param="follow_loss_first_timeout_s"),
        Sequence("SweepAndWait", memory=True, children=[
            PanCameraSweep("PanCameraSweep", ctx),
            WaitForReappear("WaitForReappearLong", ctx, timeout_param="follow_loss_second_timeout_s"),
        ]),
        Failure("LossRecoveryFailed"),  # py_trees.behaviours.Failure
    ])

    loss_recovery = Sequence("LossRecovery", memory=True, children=[
        StopBase("StopBase", ctx),
        find_target,
    ])

    follow_loop = Selector("FollowLoop", memory=False, children=[
        normal_follow,
        loss_recovery,
    ])

    follow_core = Sequence("FollowCore", memory=True, children=[
        RaiseCameraPan("RaiseCameraPan", ctx),
        follow_loop,
    ])

    return Parallel(
        name="BT_follow_sub",
        policy=ParallelPolicy.SuccessOnSelected(children=[follow_core]),
        children=[
            FaceTracking("FaceTracking", ctx),
            follow_core,
        ],
    )
```

이름 `BT_follow_sub` — tree_inspector 매칭으로 admin UI BT SUB 영역 표시.

## 7. Data flow

```
사용자 robot-web "추종" 클릭 또는 음성 "추종해줘"
  ↓ setMode + postModeClick → SetGoal(mode=ASSIST, task=follow)
control-service → ROS bridge → command_listener._on_set_goal_request
  ↓ reconciler
  ├─ blackboard.assist_task = "follow"
  └─ fsm.trigger("assist_request", task="follow")
FSM → ASSIST → BT swap
  ↓
BT_assist_main → TaskSelector → follow_branch → CheckTask SUCCESS → build_follow_subtree(ctx)
  ↓
BT_follow_sub initialise()
  └─ Parallel: FaceTracking + FollowCore 동시 시작
       FollowCore.Sequence:
         1. RaiseCameraPan: ctx.camera_pan.set_tilt(0.3) → SUCCESS
         2. FollowLoop.Selector:
              2.1 NormalFollow.Sequence:
                  - IsTargetVisible (TARGET_VISIBLE True?)
                      └─ if False → Sequence FAILURE → Selector 다음 시도
                  - DetectTargetPerson (noop SUCCESS)
                  - MaintainDistance (RUNNING + cmd_vel publish 매 tick)
                  - CheckArrival (FAILURE 그대로 또는 추후 종료 조건)
              2.2 LossRecovery.Sequence:
                  - StopBase: cmd_vel=0 publish, SUCCESS
                  - FindTarget.Selector:
                      - WaitForReappear(3s): TARGET_VISIBLE True 되면 SUCCESS, timeout 이면 FAILURE
                      - Sequence(PanCameraSweep + WaitForReappear(7s))
                      - Failure leaf → Selector 전체 FAILURE → LossRecovery FAILURE → FollowLoop FAILURE
       ↓ Parallel 가 FollowCore FAILURE 면 root FAILURE
       ↓ main.py._on_tree_failure → fsm.trigger("return_request") → RETURNING

[parallel 로 매 tick]
FaceTracking
  └─ /gogoping/vision/face_detection 구독 → bbox 중심 x-offset → camera_pan.delta_pan(dx)
     매 tick RUNNING

[백그라운드]
vision_subscriber
  └─ /gogoping/vision/target_person 구독 → id 매칭 + confidence 검사 → blackboard.TARGET_*
     매 0.5s stale 검사 → TARGET_VISIBLE 자동 False
```

## 8. 종료 경로

| 시나리오 | 발화 trigger | BT 종료 | cmd_vel cleanup |
|---|---|---|---|
| 사용자 "대기" | cancel | BT swap → terminate(INVALID) 전파 | MaintainDistance/StopBase 의 terminate 가 cmd_vel=0 |
| 사용자 다른 모드 (carry/lullaby) | assist_task 갱신 → TaskSelector 다른 branch | follow_branch RUNNING 끊김 → terminate(INVALID) | 동일 |
| 사용자 "복귀" | return_request | BT swap (ASSIST → RETURNING) | 동일 |
| 배터리 ≤20% | battery_low | BT swap (ASSIST → LOW_BATTERY_RETURNING) | 동일 |
| HW fault | fault | BT swap (ASSIST → ERROR) | 동일. ERROR 의 StopAllMotors 가 cmd_vel=0 + torque OFF 또 publish |
| **Loss recovery 실패** | (BT 자체) FollowSubTree FAILURE → main.py._on_tree_failure → return_request | BT swap (ASSIST → RETURNING) | 동일 |

모든 경로에서 cmd_vel=0 publish 보장 (AlignToDock/ReverseIntoDock 와 동일 메커니즘).

## 9. Testing 전략

### 9.1 단위 테스트 (MagicMock 사용)

각 behavior 가 `ctx.cmd_vel_pub` / `ctx.camera_pan` 을 MagicMock 으로 받아 호출 검증.
TDD 강제 — test 먼저 실패 확인 후 구현.

### 9.2 통합 — 본 spec 범위 외

`gogoping_vision/person_tracker` 가 publish 되면 자동 검증 가능. 본 spec 은 단위까지.

## 10. 위험 / 트레이드오프

| 위험 | 완화책 |
|---|---|
| vision publisher 미존재 → TARGET_VISIBLE 영구 False → 즉시 Loss Recovery → 7+3s 후 FAILURE → RETURNING | 의도된 동작. vision 없이 follow 진입 시 자동 도크 복귀로 안전 fallback |
| MaintainDistance P 게인이 너무 큼 → robot 진동 | 보수적 시작값. ROS param 으로 노출, 실 검증 시 튜닝 |
| Vic Pinky 제자리 회전 금지 — angular 만 publish 시 robot 안 움직임 | MaintainDistance 가 angular!=0 이면 최소 linear (0.05) 동시 publish |
| Face tracking 의 jitter → camera 진동 | delta_pan 에 deadzone (bbox 중심 ±20px 안이면 무시) |
| TARGET_POSE 가 base_link frame 으로 publish 됐는지 검증 | TargetPerson.msg 명세에 frame_id 명시 — `camera_rgb_frame` 에서 base_link 로 TF transform 은 vision_subscriber 가 처리 (또는 publisher 가 base_link 로 직접 변환) |
| Camera pan 의 servo_bridge 가 watchdog (1s) 가짐 — publish 안 하면 정지 | FaceTracking 이 매 tick RUNNING + publish → 10Hz 유지 OK |
| Loss recovery 의 3s/7s 가 너무 짧음/김 | ROS param 으로 노출. 실 검증 후 튜닝 |
| `BT_follow_sub` 가 SUCCESS 안 함 → ASSIST root 도 SUCCESS 안 함 → IDLE 복귀 안 됨 | 사용자가 명시적 cancel 또는 다른 모드 변경 필요. lullaby 와 동일 패턴 (외부 trigger 만 종료) |

## 11. 추후 작업 (본 spec 밖)

- `gogoping_vision` 패키지 — YOLO + ReID + face_recognition 노드 (별도 PR)
- `gogoping_vision/mock_target_publisher.py` — sim 데모용 가짜 사람 publish
- 실 robot 검증 + PD 게인 튜닝
- BT_carry_sub 의 단순화 (memory: goto-only) — 별도 spec
- BT_hide_and_seek_sub — 별도 spec, follow 의 PanCameraSweep 재사용

## 12. 다음 단계

본 spec 의 사용자 review → 수정사항 반영 → plan 작성 → implementer subagent 시퀀스.
