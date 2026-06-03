# pingdergarten · 사랑의 에듀핑 — 발표 대본

**총 49 슬라이드 · 약 20분 발표**

---

## HOOK (1-6) — 도입

### [1] 01-title.html — 핑더가든 (커버)
"안녕하세요. 저희는 ADDINEDU VLA 최종 프로젝트 팀 **'사랑의 에듀핑'** 입니다. 유치원에 활기를, 선생님께 여유를 드리기 위해 만든 교육보조로봇 3종, **pingdergarten** 을 소개하겠습니다."

### [2] 02-pov-video.html — POV 1인칭 영상
"먼저 유치원 선생님의 하루를 1인칭 시점으로 보겠습니다."
*(영상 재생)*

### [3] 02b-dev-question.html — 무엇을 만들어야 했나
"방금 보신 것처럼 유치원 선생님은 정말 바쁩니다. 그래서 저희는 선생님을 돕는 로봇을 만들기로 결정했습니다."

### [4] 03-want.html — 하고 싶었던 것
"선생님이 직면한 4가지 문제가 있습니다. 첫째, 놀이 시간에 여러 아이가 동시에 도움을 청하는데 손은 둘뿐. 둘째, 율동을 가르치며 아이들 모습을 촬영할 수 없음. 셋째, 무거운 교구를 혼자 나르기 힘듦. 넷째, 하루 일과 기록이 너무 바쁨. **이 문제들을 해결하기 위해 저희는 세 친구를 만들었습니다.**"

### [5] 04b-reveal.html — 핑더가든 reveal
"저희가 만든 것은 **EduPing**, **GogoPing**, 그리고 **NoriArm** 세 가지 로봇입니다. 이들이 유치원에서 어떻게 활약하는지 차례대로 보여드리겠습니다."

### [6] 05-toc.html — 목차
"오늘 발표는 총 6부로 나뉩니다. ① 시스템과 기술 스택, ② EduPing 양팔 로봇, ③ GogoPing 자율주행, ④ NoriArm 매니퓰레이터, ⑤ 프로젝트 프로세스, 마지막으로 ⑥ 팀 소개 및 Q&A."

---

## SETUP (7-12) — 시스템 구성

### [7] 04-need.html — 그래서 필요했던 것
"저희가 필요한 로봇은 세 가지. **선생님과 닮고 춤도 춰주는 친구 (EduPing)**, **선생님보다 힘 센 친구 (GogoPing)**, **아이들과 함께 놀고 배우는 친구 (NoriArm)**."

### [8] 04c-required.html — 필수 요건
"세 로봇 모두 공통 필수 요건이 있습니다. **선생님 일손을 덜고 아이들이 자연스럽게 다가갈 수 있어야** 하고, **교사가 직접 조작·명령할 수 있어야** 합니다."

### [9] 07b-hardware.html — 로봇 하드웨어
"하드웨어 구성입니다. **EduPing** 은 OpenArm 양팔과 D435 깊이 카메라. **GogoPing** 은 Vic Pinky 모바일 베이스, RPLiDAR C1, D435. **NoriArm** 은 교실 3대 — Dynamixel 6축 팔과 웹캠."

### [10] 06-system.html — 시스템 아키텍처 ★ 6 step 동적
**STEP 1 — APP**: "**학부모, 의사**는 Portal Browser 로, **운영자**는 Admin App 으로 시스템에 접속합니다."

**STEP 2 — SERVICE**: "모든 요청은 **Portal Web** 을 거쳐 핵심 허브인 **Control Service** 로 모입니다. **AI Service** 가 LLM·Vision 추론을, **DB** 가 세션·이벤트 기록을 담당합니다."

**STEP 3 — ROBOTS**: "각 로봇은 **자체 PC 와 UI 를 보유** — 아이는 로봇 화면을 직접 터치하거나 음성으로 명령할 수 있습니다."

**STEP 4 — 등하원 시나리오**: "아이가 등원하면 EduPing 카메라가 얼굴을 인식 (AI Service), 양팔로 하이파이브, 이벤트는 DB 에 기록, Portal Web 으로 학부모에게 등원 알림."

**STEP 5 — 자율주행 가이드**: "교사가 Admin 에서 강당 안내 요청 → Control → GogoPing 자율주행. 사람을 만나면 카메라 인식 (AI)·로그 저장 (DB) 으로 경로 재설정."

**STEP 6 — 놀이 (NoriArm)**: "아이가 NoriArm UI 에서 가게놀이 선택 → Control → AI Service LLM 으로 요청 분류 → NoriArm 이 ACT 학습 모델로 픽업. 결과는 DB 에 저장되고 Portal 로 학부모 보고서에 반영."

### [11] 07-tech-stack.html — 기술 스택
"기술 스택은 5가지. **Robot 제어** ROS2 Jazzy + Nav2 + py_trees, **Vision** YOLOv8 + ByteTrack + InsightFace + MediaPipe, **모방학습** LeRobot ACT, **Voice·LLM** Web Speech + Ollama qwen2.5, **협업** GitHub + Confluence + Jira."

### [12] 07c-daily-scenario.html — 하루 일과 시나리오
"아이의 하루는 5단계. 등원 시 EduPing 인사·하이파이브 → 놀이 시간엔 세 로봇 함께 활동 → 낮잠 시간 GogoPing 자장가 → 오후 교사 보조 → 하원 시 다시 EduPing 인사. **상시 원격진찰도 가능**."

---

## EduPing (13-25) — 양팔 로봇

### [13] 08-eduping-section.html — PART 02 인트로
"이제 EduPing 을 상세히 소개합니다. 양팔 로봇으로 **등하원, 율동, 무궁화꽃, 원격진찰** 4가지 기능을 수행합니다."

### [14] 09-eduping-arrival-scenario.html — 등하원 시나리오
"등하원은 4단계. ① 카메라로 얼굴 인식 → ② 등록 정보 매칭 → ③ 손 탐색 → ④ 하이파이브."

### [15] 09-eduping-arrival.html — 등하원 영상
"실제 하이파이브 영상입니다."
*(영상 재생)*

### [16] 09b-eduping-arrival-content.html — 등하원 기술
"기술적으로, **D435 깊이 카메라로 손의 3D 좌표를 역투영** → 로봇 목표점으로 변환. **IK→FK 폐쇄 루프**로 오차를 **20cm → 2cm** 로 줄였습니다. MuJoCo 디지털 트윈에서 먼저 검증한 뒤 실물 OpenArm 시연."

### [17] 10-eduping-dance-scenario.html — 율동 시나리오
"율동은 3단계. ① 선생님이 팔을 직접 움직여 녹화 → ② 키프레임 추출 → ③ 재생 으로 EduPing 이 같은 율동 반복."

### [18] 10-eduping-dance.html — 율동 영상
"율동 재현 영상입니다."
*(영상 재생)*

### [19] 10b-eduping-dance-content.html — 율동 기술
"선생님이 팔을 움직이면 **16개 모터 각도를 50Hz 로 샘플링** 해 motion.yaml 저장. 시간·관절 라디안 키프레임은 선형 보간으로 부드럽게 이동. **WebSocket 한 채널** 로 같은 시간에 동작과 음악이 정확히 동기."

### [20] 11-eduping-hibiscus-scenario.html — 무궁화꽃 시나리오
"무궁화꽃이 피었습니다는 5단계. 아이 진입 → 준비 자세 → 노래 시작 → 움직임 관찰 → 움직인 아이 탈락."

### [21] 11-eduping-hibiscus.html — 무궁화꽃 영상
"게임 진행 영상입니다."
*(영상 재생)*

### [22] 11b-eduping-hibiscus-content.html — 무궁화꽃 기술
"핵심은 **`audio.currentTime` 단일 시계** 로 노래·팔 동작·움직임 관찰을 동기화. **MediaPipe + InsightFace** 로 여러 아이 동시 인식. **SAD 이미지 차이 + 2단 임계값** 으로 움직임을 정교하게 판정."

### [23] 12-eduping-doctor-preview.html — 원격진찰 개요
"원격진찰은 의사와 환자를 실시간으로 연결합니다. 좌측 의사 Leader UI, 우측 환자 UI. **의사 팔 움직임이 로봇에 직결**, **깊이 카메라 3D 점구름이 의사 화면 전송**."

### [24] 12-eduping-doctor.html — 원격진찰 영상
"4분할 화면 — 의사 UI / 환자 UI / 의사 실사 / 환자 실사."
*(영상 재생)*

### [25] 12b-eduping-doctor-content.html — 원격진찰 기술
"**의사 → 로봇**: Leader Teleop 으로 팔 관절각 직결. **로봇 → 의사**: D435 깊이 영상 1m 필터 + 3D 점구름 전송. **의사 ↔ 환자**: WebRTC P2P 로 영상·음성 브라우저 직통, 제어 서버는 신호만 중계. **FSR 청진 센서** 데이터도 의사에게."

---

## GogoPing (26-36) — 자율주행

### [26] 13-gogoping-section.html — PART 03 인트로
"이제 GogoPing 을 소개합니다. 자율주행 로봇으로 **교사 추종, 가이드, 숨바꼭질** 게임을 진행합니다."

### [27] 14-gogoping-follow-scenario.html — 교사 추종 시나리오
"교사 추종은 6단계. 음성 명령 시작 → 교사 얼굴 인식 → 객체 등록 → 추적 → 음성 정지 → 대기."

### [28] 14-gogoping-follow.html — 추종 영상
"실제 추종 영상입니다."
*(영상 재생)*

### [29] 14b-gogoping-follow-content.html — 추종 기술
"**InsightFace** 로 교사 얼굴 등록, **OSNet 신체 임베딩** 누적. **YOLO 검출 + ByteTrack 추적**, 매 프레임 OSNet 유사도 최대 궤적 재선택. **외형 유사도 + RPLiDAR 거리 연속성 이중 게이트**로 닮은 사람 제외. 포즈 랜드마크로 사람 아닌 물체 필터링."

### [30] 14c-gogoping-guide-map.html — 가이드 지도
"가이드는 시뮬과 운영이 동일한 지도. 좌측 **Gazebo 3D 시뮬** (Nav2·AMCL 검증). 우측 **Admin App vertex 그래프** — 놀이방, 수면실, 통로, 충전소."

### [31] 14c-gogoping-guide-scenario.html — 가이드 시나리오
"가이드는 6단계. 음성·UI 목적지 명령 → 현재 위치에서 출발 vertex 확정 → 경로 생성 → 아이 데려가기 → 도착 → 대기."

### [32] 14c-gogoping-guide.html — 가이드 영상
"vertex 그래프 따라 자율주행 영상입니다."
*(영상 재생)*

### [33] 14d-gogoping-guide-content.html — 가이드 기술
"의미로 명령하는 **vertex 기반 그래프** — '놀이방으로 가' 라고 말하면 이동. **Nav2 NavigateToPose** 액션 + costmap 으로 장애물 회피. **Heading-aware Dijkstra** 로 135° 이상 급선회 제외, **회전은 5개 화이트리스트 지점에서만**. 사람이 앞에 나타나면 깊이 센서 근접도 감지로 긴급 정지."

### [34] 15-gogoping-hideseek-scenario.html — 숨바꼭질 시나리오
"숨바꼭질은 6단계. 놀이구역 이동 → 아이 등록 → 30초 카운트다운 → 정해진 지점 순찰 → 카메라로 아이 탐색 → 복귀."

### [35] 15-gogoping-hideseek.html — 숨바꼭질 영상
"순찰·탐색 영상입니다."
*(영상 재생)*

### [36] 15b-gogoping-hideseek-content.html — 숨바꼭질 기술
"매판 다른 동선 — **그룹 셔플 + 최근접 이웃 알고리즘** 으로 순찰 순서 정함. 장애물 시 **BehaviorTree 제어 하 Nav2 실시간 재계획**. 정지 후 **카메라만 좌우 26초 스윕** 으로 얼굴 탐색. **InsightFace ArcFace 512차원 임베딩** 으로 등록된 아이만 정답 인정."

---

## NoriArm (37-46) — 매니퓰레이터

### [37] 18-noriarm-section.html — PART 04 인트로
"이제 NoriArm 을 소개합니다. 교실 3대 작은 매니퓰레이터로 **블럭쌓기, OX 퀴즈, 가게놀이** 진행."

### [38] 19-noriarm-blocks-scenario.html — 블럭쌓기 시나리오
"블럭쌓기는 3단계 파이프라인. ① 리드암으로 611 에피소드 직접 녹화 → ② ACT 모방학습 → ③ 실시간 폐쇄 루프에서 자율 픽업·적재."

### [39] 19-noriarm-blocks.html — 블럭쌓기 영상
"사람·로봇 번갈아 쌓는 영상입니다."
*(영상 재생)*

### [40] 19b-noriarm-blocks-content.html — 블럭쌓기 기술
"**611 에피소드**, 사람·로봇 4턴 반복. **LeRobot ACT 누적 197만 스텝 학습**. OMX-F 5축 팔 부족분 보완. 좁은 박스 → 전체 작업 영역 확대. 회귀 시 **재학습 없이 HSV 색상 마스킹 ROI 보완**."

### [41] 20-noriarm-oxquiz-scenario.html — OX 퀴즈 시나리오
"OX 퀴즈는 4단계. NoriArm 문제 제시 → 아이 손 표시 → 위치 판정 → 정답·오답 표시."

### [42] 20-noriarm-oxquiz.html — OX 퀴즈 영상
"문제 제시·손 추적 영상입니다."
*(영상 재생)*

### [43] 20b-noriarm-oxquiz-content.html — OX 퀴즈 기술
"**상단 카메라 + YOLO-World** 로 OX 보드 검출, 색깔로 영역 분할. **MediaPipe Hands** 로 손끝 추적, **한 영역 위 1.5초 머물면 확정 판정**. **ROS2 JointTrajectory** 로 5축 팔·그리퍼 독립 제어, 정답 방향만 가리키는 rule-based 정책 재생."

### [44] 21-noriarm-shop-scenario.html — 가게놀이 시나리오
"가게놀이는 4단계 파이프라인. 625 에피소드 ACT 학습 → 음성 의도 분류 → YOLO ROI 마스킹 → 실시간 추론 픽업."

### [45] 21-noriarm-shop.html — 가게놀이 영상
"과일 요청·픽업 영상입니다."
*(영상 재생)*

### [46] 21b-noriarm-shop-content.html — 가게놀이 기술
"SmolVLA 는 prompt 무반응 60% 정확도. 비전 ablation MSE 0.08% → **로봇이 시각을 거의 안 보고 음성·상태로 외운다** 는 뜻. 그래서 **YOLO ROI 마스킹** 으로 대상 과일만 남기고 나머지 검정 처리 → **정확도 0.999 (TP 840 / FP 1)**. **LeRobot ACT 채택**, MAE 0.69 (baseline 1.91), **208Hz 실시간 성능**."

---

## CLOSING (47-55)

### [47] 22b-portal-report.html — 일과 보고서
"Portal Web 에서 학부모가 **자녀 일과를 자연어 보고서** 로 받아봅니다. 시간대별 활동 사진 + 교사 편집 내용을 한 화면에서 확인. 하원 시점에 **qwen2.5:7b LLM** 이 사진 메타·모드 이력·점심 메뉴를 통합해 자동 요약."

### [48] 22c-process-section.html — PART 05 Process 인트로
"이제 저희 프로젝트 진행 과정을 소개합니다. **7주 동안 7개 스프린트** 로 완성했습니다."

### [49] 22-sprint-jira.html — 스프린트 타임라인
"S1 주제 정하기 2일 → S2 상세 설계·Vic Pinky 셋업 6일 → S3 scaffold·놀이 설계 6일 → S4 등하원·율동·OX·블럭 7일 → S5 무궁화꽃·LLM·OpenArm·가이드 7일 → S6 테스트·데모 7일 → S7 발표 준비 5일. **6주 6일 모든 스프린트 완주**."

### [50] 22a-jira-gantt.html — Jira 진행
"Jira FN-5 **구현 Epic 35개 이슈 모두 완료**. 의존성을 가진 작업들이 일정에 맞게 완성됐습니다."

### [51] 22d-team-section.html — PART 06 Team 인트로
"이제 저희 **'사랑의 에듀핑'** 팀 6명을 소개합니다."

### [52] 23a-team-eduping.html — EduPing 팀
"EduPing 팀입니다. **박우림 리더** 가 EduPing 의 **율동, 원격진찰, 호출어 (STT·TTS)** 를 담당했습니다. **이정우** 는 **등하원/하이파이브, 무궁화꽃이 피었습니다, 일과 보고서** 를 구현했습니다."

### [53] 23b-team-gogoping.html — GogoPing 팀
"GogoPing 팀입니다. **노영주** 는 **추종 기능, 사람 인식 (YOLO·ReID), WebRTC 영상 송출** 을 담당했습니다. **이강택** 은 **Nav2 자율주행 가이드, 숨바꼭질, 사람 인식 경로 재설정** 을 구현했습니다."

### [54] 23c-team-noriarm.html — NoriArm 팀
"NoriArm 팀입니다. **이지수** 는 **ACT 블럭쌓기, HSV 추론, OX 퀴즈** 를 담당했습니다. **최민성** 은 **ACT 가게놀이, YOLO ROI 마스킹, 그리고 오늘 발표** 를 맡았습니다."

### [55] 24-ending.html — Q&A
"이상으로 **pingdergarten 프로젝트 발표** 를 마칩니다. 더 알고 싶으신 점이 있으시면 Q&A 버튼을 클릭하시면 각 기능별 상세 설명을 보실 수 있습니다. **감사합니다**."

---

**예상 발표 시간**: 약 20분
