# 하이파이브 출석 체크 (Depth Camera + OpenArm)

> 상태: **계획 단계** — Depth 카메라 미보유, 코드 미작성. 본 문서는 향후 구현을 위한 설계 스케치.

EduPing (OpenArm 양팔 7-DOF) 이 등원하는 아이의 손바닥을 depth 카메라로 검출해 한쪽 팔을 뻗어 **하이파이브** 로 출석을 확인하는 인터랙션. 기존 얼굴 인식 기반 출석 체크 (`AttendanceCamera.vue`) 와 보완 관계 — 얼굴 ID 매칭 후 "핑이랑 하이파이브 하자!" 음성 유도 → 손바닥 검출 → 팔 뻗음 → 접촉 감지 → 출석 마크.

## 동기

- 단순 얼굴 인식 출석은 **수동적** — 아이가 카메라 앞에 잠깐 비치기만 하면 끝. 신체 인터랙션이 없어 아이가 "로봇과 인사했다" 는 감각이 약함.
- 하이파이브는 **능동 참여** 가 필요한 의식 → 등원이라는 일과의 시작을 명확히 마킹하는 효과.
- OpenArm 양팔이 이미 갖춰져 있는데 등원·하원에서 안 쓰고 있어 활용도 낮음.

## 시나리오 (등원 흐름)

```
① 아이가 EduPing 앞으로 접근
② 얼굴 인식으로 출석 후보 ID 확정 (기존 등원 모드)
③ EduPing: "안녕 OO야! 핑이랑 하이파이브 하자!" (TTS + 화면 안내)
④ Depth 카메라가 아이 손바닥 검출 (MediaPipe Hands → palm 3D point)
⑤ 손바닥이 N 프레임 안정 → 팔이 천천히 뻗음 (Cartesian path, 0.15 m/s 이하)
⑥ 접촉 감지 (joint torque spike 또는 손목 FSR)
⑦ 접촉 확인 → 가벼운 retract + "출석 완료!" 음성 + DB 에 attendance 기록
⑧ 2 초 안에 접촉 없으면 timeout retract + 재시도 안내
```

하원도 동일 흐름, attendance type 만 OUT.

## 시스템 구성

```
┌──────────────────────────────────────────────────────────────┐
│  EduPing 노트북                                                │
│                                                                │
│  ┌─────────────┐    ┌──────────────────┐    ┌──────────────┐ │
│  │ Depth cam   │──▶ │ hand_detect_node │──▶ │ highfive_    │ │
│  │ (RealSense) │    │ (MediaPipe →     │    │ planner_node │ │
│  │             │    │  palm 3D point)  │    │ (IK + safety)│ │
│  └─────────────┘    └──────────────────┘    └──────┬───────┘ │
│                              │                      │         │
│                       /highfive/                    │         │
│                       palm_target                   ▼         │
│                       (geometry_msgs/             OpenArm     │
│                        PointStamped)              follower    │
│                                                   (기존 ros2_  │
│                                                    control)   │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ control-service /eduping/attendance/highfive          │    │
│  │  (POST: success/timeout, FastAPI)                     │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

- **`hand_detect_node`** — RGB-D 입력, 손바닥 keypoint 검출 (MediaPipe Hands 의 #9 middle MCP), depth 로 unproject. `/highfive/palm_target` 으로 카메라 좌표계의 3D point publish.
- **`highfive_planner_node`** — palm_target 구독, debounce 후 카메라 → `openarm_right_base` TF 변환, MoveIt Cartesian path 계산, FollowJointTrajectory action 으로 follower 에 전달. 접촉 감지 로직 포함.
- **얼굴 인식 출석 흐름과의 연동** — control-service 의 등원 모드 라우터가 얼굴 매칭 후 hand_detect 활성화 신호를 보내고, planner 의 접촉 콜백을 받아 attendance 기록.

## 파이프라인 단계

| 단계 | 입력 | 출력 | 도구 / 비고 |
|---|---|---|---|
| 1. RGB-D capture | RealSense 토픽 | `sensor_msgs/Image` (color) + `Image` (depth, aligned) | realsense2_camera ROS pkg, `align_depth.enable=true` 필수 |
| 2. 손 keypoint | color image | 21 keypoints (2D 픽셀) | MediaPipe Hands (CPU, 30fps) — Python 노드, rclpy |
| 3. Palm 3D unproject | keypoint #9 픽셀 + depth | 카메라 좌표계 (x,y,z) | 5×5 patch median 으로 depth noise 완화 |
| 4. Debounce | 연속 프레임 palm 3D | 안정 target | 표준편차 < 1cm 가 10 프레임 (≈ 0.3s) 지속 |
| 5. Frame transform | 카메라 좌표계 point | `openarm_right_base` 좌표계 point | `tf2_ros` — 카메라 ↔ base TF 는 hand-eye calibration |
| 6. Safety check | 변환된 target | 통과 / reject | workspace AABB + 얼굴 keypoint Z 보다 위면 reject |
| 7. IK & path plan | target pose | JointTrajectory | MoveIt Cartesian path, max_vel_scaling=0.2 |
| 8. Execute | trajectory | (motion) | 기존 follower (`right_joint_trajectory_controller`) 사용 |
| 9. Contact detect | joint efforts | spike or timeout | joint4 (팔꿈치) torque > 임계 OR `wrist_fsr` reading > 임계 |
| 10. Retract + attendance | contact event | DB write | 안전 zone 으로 복귀 + attendance API POST |

## 좌표계 & calibration

- **카메라 mount** — eye-to-hand (EduPing 챠시 또는 머리에 고정). eye-in-hand (팔에 부착) 은 진찰 시나리오에서 따로 고려 — 본 기능은 고정형이 단순.
- **Hand-eye calibration** — ArUco 마커 + `easy_handeye2` 류 ROS 패키지로 1 회 셋업, `static_transform_publisher` 로 `camera_color_optical_frame ↔ openarm_right_base` TF publish.
- 카메라 위치 바뀌면 재 calibration 필요 — checklist 에 포함.

## 안전 가드 (최우선)

| 가드 | 값 | 이유 |
|---|---|---|
| Cartesian velocity cap | 0.15 m/s | 아이 손까지 1초 안에 도달, 충격 미미 |
| Workspace AABB | x∈[0.2, 0.6], y∈[-0.4, 0.4], z∈[0.4, 1.3] (m, base 기준) | 아이의 몸 / 얼굴 / 발 영역 회피 |
| 얼굴 회피 | palm.z 가 face.z + 0.15m 보다 위면 reject | 손이 얼굴 가까이 있으면 동작 안 함 |
| Debounce | palm 검출 10 frame stable | 떨림·noise 추적 방지 |
| 접촉 timeout | 2.0s | 손이 빠지면 자동 retract |
| 양팔 동시 동작 | **금지** (single-arm only) | 충돌 & 안전 review 단순화 |
| Admittance | 모든 동작에서 ON | `controller/eduping-controller/CLAUDE.md` 의 "EE teleop + admittance" 인프라 재사용. 충돌 시 yield. |
| E-stop | 기존 emergency_stop 서비스 (gogoping 패턴) 와 동일 — 모드 진입 시 항상 활성 | UI 상단 빨간 버튼 |

## MVP 단계 (depth 카메라 입수 후)

1. **무하드웨어 시뮬레이션** — `fake_hardware` follower + RealSense 단독 (no 팔). `hand_detect_node` 가 palm_target 만 publish, RViz 로 시각 검증.
2. **단일 팔 sim → 실물** — `openarm_bimanual_moveit_config` 의 single-arm group 으로 IK + Cartesian path 검증. 사람 손 대신 스티로폼 손 모형 향해 접근, torque spike retract 확인. **사람 미사용**.
3. **사람 손 실험** — 안전 review 통과 후 어른 손 (성인) 으로 1차 테스트. 접촉 후 retract 만 검증, 출석 흐름 미연동.
4. **얼굴 출석 연동** — 등원 모드 흐름에 통합. 얼굴 ID 매칭 → hand_detect 활성화 → contact → attendance 기록 → 정식 SR 으로 승격.
5. **양팔 옵션** (장기) — 양쪽 모두에서 손 검출 시 가까운 쪽 팔 사용. 동시 양팔은 안 함.

## 하드웨어 요구

- **Depth 카메라** — **현재 미보유**. 후보:
  | 모델 | 가격 | 측정 범위 | 비고 |
  |---|---|---|---|
  | Intel RealSense D435 | $300~ | 0.3–3m | 단종, 재고만. 본 프로젝트 적정. |
  | Intel RealSense D435i | $360~ | 0.3–3m | IMU 포함, IMU 본 기능에 불필요. |
  | Intel RealSense D455 | $440~ | 0.6–6m | 베이스라인 길어 원거리 정밀도 ↑, 근거리 (< 0.5m) 는 D435 가 유리. |
  | Orbbec Astra Pro Plus | $200~ | 0.6–8m | 가성비, ROS2 드라이버 별도 확인 필요 |
  | Azure Kinect DK | $400~ | 0.5–5m | 단종, EOL 주의 |

  **추천**: D435 — 손이 0.5–1.5m 거리에 올 거라 sweet spot 정확히 맞음. `realsense2_camera` ROS2 jazzy 패키지 공식 지원.

- **선택 — 손목 FSR** — 접촉 감지를 torque 만으로 하면 false-positive 위험 (소맷자락 스침 등). 손목에 작은 FSR (Force Sensitive Resistor) 두면 명확함. `controller/eduping-controller/CLAUDE.md` 의 "TOF/FSR Arduino bridge" 인프라 재사용.

## 소프트웨어 의존성 (추가될 것)

- `mediapipe` (pip) — 손 keypoint 검출
- `realsense2_camera` (apt: `ros-jazzy-realsense2-camera`) — RealSense ROS2 노드
- `tf_transformations` 또는 `transforms3d` (이미 ROS2 표준)
- `easy_handeye2` (선택) — calibration 도구
- 새 ament_python 패키지 `eduping_highfive` — `controller/eduping-controller/src/eduping_highfive/` 위치 예정
  - 노드: `hand_detect_node`, `highfive_planner_node`
- control-service 에 `eduping/attendance/highfive` API 추가 — FastAPI 라우터

## 데이터 흐름 (등원 모드 통합 시)

```
얼굴 인식 (AttendanceCamera.vue)
  └─▶ face match: child_id 확정
       └─▶ control-service POST /api/eduping/attendance/highfive/start
              └─▶ highfive_planner_node 활성화 신호 (rclpy service call)
                   └─▶ hand_detect → planner → arm execute → contact
                        └─▶ planner publish /highfive/result {child_id, contact, t}
                             └─▶ control-service 가 구독, DB attendance INSERT
                                  └─▶ WS broadcast → 화면에 "OO 출석 완료!"
```

## 미해결 질문

- [ ] **카메라 mount 위치** — 머리(눈 위치)? 가슴? 모니터 위? 아이 키 (90–130cm) 와 카메라 화각 고려해 결정 필요.
- [ ] **양손 다 보일 때** — 가까운 쪽? 오른손? UX 정책 결정.
- [ ] **접촉 안 됨 재시도** — 1 회 timeout 후 자동 재시도 vs 음성 안내만 vs 출석 fail.
- [ ] **속도** — 0.15 m/s 가 정말 안전한지 안전 review 필요. 어린이 반응 속도 (~250ms) 대비 정지 거리 < 4cm 면 안전 마진 OK.
- [ ] **신장 작은 아이** — 키 80cm 이하면 손이 base z 보다 너무 낮을 수 있음 — 화면 안내 ("손을 어깨 높이까지 올려줘") 또는 동작 reject.
- [ ] **여러 명 동시** — 검출된 손 2 개 이상이면? 가장 가까운 쪽만? 줄 세우기?
- [ ] **카메라 단독 실패** — RGB 만 정상, depth 누락 (반사 표면 등) 시 fallback. RGB-only keypoint + 어깨 keypoint 까지의 추정 거리?
- [ ] **출석 인터랙션 시간 예산** — 등원 피크 시간 (07:30~08:30) 에 아이 한 명당 < 5초 처리 가능해야 줄이 안 밀림. 검출 1s + 동작 2s + retract 1s = 4s — 빡빡함.

## 관련 SR / 문서

- 추가 예정: `SR-IN-XXX` (등원), `SR-OUT-XXX` (하원) — `docs/system-requirements.md` 에 등록 후 `docs/implementation-plan.md` 에 본 README 링크.
- 참고:
  - [`docs/robots/openarm.md`](../robots/openarm.md) — OpenArm 사양
  - [`controller/eduping-controller/CLAUDE.md`](../../controller/eduping-controller/CLAUDE.md) — admittance 인프라
  - [`app/admin-app/widgets/`](../../app/admin-app/widgets/) — Attendance UI

## 진행 트리거

본 계획은 다음 조건 충족 시 구현 단계로 진입:

1. Depth 카메라 입수 + RealSense ROS2 드라이버 호스트 설치 확인
2. EduPing 노트북에서 `realsense2_camera` launch 로 `/camera/color/image_raw` + `/camera/aligned_depth_to_color/image_raw` publish 확인
3. Hand-eye calibration 1 회 완료 (TF 영구 등록)
4. 안전 review 통과 (속도·workspace·timeout 파라미터 확정)
