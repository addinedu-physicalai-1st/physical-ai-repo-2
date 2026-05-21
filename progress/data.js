// 핑더가든 구현 진척도 데이터. progress.html / detail.html 양쪽에서 로딩.
//
// 각 카드(UI 1개)는 features (메뉴/모드 단위) 를 가지고, feature 는 subs (세부 SR) 를 가진다.
// feature 의 image 는 detail 페이지의 데모 사진 (선택적).
window.PINGDER_DATA = (() => {
  const D = 'done', P = 'partial', X = 'planned';

  const robot = [
    {
      id: 'gogoping',
      title: 'GogoPing + Admin UI',
      sub: 'Vic Pinky — 보조 · 숨바꼭질 · 자장가 / PyQt5 관제 데스크톱',
      hero: 'demo/gogoping.png',
      features: [
        {
          name: '자장가 모드',
          image: 'demo/gogoping/자장가.png',
          subs: [
            { name: 'mp3 1곡 재생 (lullaby.mp3)', s: D, id: 'SR-NAP-001' },
            { name: '낮잠 시작·종료 시각 기록', s: X, id: 'SR-NAP-002' },
          ],
        },
        {
          name: '보조 모드 (교사 추종 · 운반)',
          image: 'demo/gogoping/보조.png',
          subs: [
            { name: '추종 대상 확인 (얼굴 매칭 + 확인 모달)', s: X, id: 'SR-CAR-001' },
            { name: '교사 추종 (ReID + LiDAR 거리)', s: X, id: 'SR-CAR-002' },
            { name: '정지 · 대기 입력 (UI/음성)', s: X, id: 'SR-CAR-003' },
            { name: '운반 요청 수신 (지도 클릭 → named pose)', s: X, id: 'SR-CAR-004' },
            { name: '자율 주행', s: D, id: 'SR-CAR-005' },
            { name: '도착 알림 (TTS + 토스트)', s: X, id: 'SR-CAR-006' },
            { name: '운반 후 대기 전이', s: X, id: 'SR-CAR-007' },
            { name: '추종 거리 유지 (LiDAR 임계)', s: X, id: 'SR-SAF-006' },
            { name: '보조 모드 음성 입력 제한 (정지만)', s: X, id: 'SR-OPS-013' },
          ],
        },
        {
          name: '숨바꼭질 모드',
          image: 'demo/gogoping/숨바꼭질.png',
          subs: [
            { name: '위치 이동 (play_area)', s: X, id: 'SR-PLAY-007' },
            { name: '참가자 확정 (얼굴 매칭, 최대 5명)', s: X, id: 'SR-PLAY-007' },
            { name: '카운트다운 (눈 가리기 + TTS 30s)', s: X, id: 'SR-PLAY-007' },
            { name: '순찰 (patrol_* named pose)', s: X, id: 'SR-PLAY-007' },
            { name: '호명 (얼굴 인식 시 이름 호출)', s: X, id: 'SR-PLAY-007' },
          ],
        },
        {
          name: '대기 모드 (공통 기반)',
          image: 'demo/gogoping/대기.png',
          subs: [
            { name: '표정 상시 표시', s: D, id: 'SR-UI-001' },
            { name: '호출어 · STT · TTS · 의도 분류', s: D, id: 'SR-VOICE-007/002/005/003' },
            { name: '모드 전환 (latched 토픽)', s: P, id: 'SR-OPS-001' },
          ],
        },
        {
          name: 'Admin UI — 관제',
          image: 'demo/gogoping-admin.png',
          subs: [
            { name: '로봇 상태 실시간 모니터링 (`/ws/robot-state`)', s: X, id: 'SR-ADM-001' },
            { name: '추종 대상 확정 UI', s: X, id: 'SR-ADM-002' },
            { name: '정지 · 재개 입력 버튼', s: X, id: 'SR-ADM-003' },
            { name: '지도 기반 목적지 지정 (Waypoint 위젯)', s: D, id: 'SR-ADM-004' },
            { name: '도착 알림 수신 토스트', s: X, id: 'SR-ADM-005' },
          ],
        },
        {
          name: '카메라 스트리밍',
          subs: [
            { name: 'Pi 측 송출 (MJPEG UDP, default ON)', s: P, id: 'SR-CAM-001' },
            { name: 'Control Server WS 게이트웨이', s: P, id: 'SR-CAM-002' },
            { name: '다중 클라이언트 / 다중 로봇 구독', s: P, id: 'SR-CAM-003' },
            { name: 'Admin UI 카메라 위젯', s: P, id: 'SR-CAM-004' },
            { name: '수동 admin STOP/START', s: X, id: 'SR-CAM-005' },
          ],
        },
        {
          name: '주행 안전 / 자가관리',
          subs: [
            { name: '사람 · 장애물 감지 (LiDAR + vision)', s: X, id: 'SR-SAF-001' },
            { name: '충돌 회피 (동적 장애물)', s: X, id: 'SR-SAF-002' },
            { name: '사람 근접 시 감속', s: X, id: 'SR-SAF-005' },
            { name: '배터리 저하 시 충전소 복귀', s: X, id: 'SR-REL-004' },
          ],
        },
      ],
    },
    {
      id: 'eduping',
      title: 'EduPing',
      sub: 'OpenArm — 정문 등하원 · 율동 · 무궁화꽃이 피었습니다',
      hero: 'demo/eduping.png',
      features: [
        {
          name: '대기 모드 (공통 기반)',
          image: 'demo/eduping/대기.png',
          subs: [
            { name: '표정 상시 표시 (셰이더 9종)', s: D, id: 'SR-UI-001' },
            { name: '호출어 감지', s: D, id: 'SR-VOICE-007' },
            { name: '음성 인식 (STT)', s: D, id: 'SR-VOICE-002' },
            { name: '음성 출력 (TTS)', s: D, id: 'SR-VOICE-005' },
            { name: '의도 분류 LLM', s: D, id: 'SR-VOICE-003' },
            { name: '잡담 응답', s: D, id: 'SR-VOICE-004' },
            { name: '모드 전환 (latched 토픽)', s: P, id: 'SR-OPS-001' },
            { name: '모드 내 자연어 명령 라우팅', s: P, id: 'SR-OPS-011' },
            { name: '음성 ↔ 타이핑 토글 + Siri 블롭', s: P, id: 'SR-UI-003' },
            { name: 'UI 모드·명령 클릭 선택', s: P, id: 'SR-UI-002' },
          ],
        },
        {
          name: '등원 모드',
          image: 'demo/eduping/등원.png',
          subs: [
            { name: '얼굴 캡처 (등록 얼굴 등장 시)', s: D, id: 'SR-IN-001' },
            { name: '얼굴 식별 (다중 임베딩 매칭)', s: D, id: 'SR-IN-002' },
            { name: '환영 인사 출력 (TTS)', s: D, id: 'SR-IN-003' },
            { name: '환영 모션 (OpenArm trajectory)', s: P, id: 'SR-IN-004' },
            { name: '등원 시각 기록 (DB attendance INSERT)', s: D, id: 'SR-IN-006' },
          ],
        },
        {
          name: '하원 모드',
          image: 'demo/eduping/하원.png',
          subs: [
            { name: '얼굴 캡처', s: D, id: 'SR-OUT-001' },
            { name: '얼굴 식별', s: D, id: 'SR-OUT-002' },
            { name: '작별 인사 출력 (TTS)', s: D, id: 'SR-OUT-003' },
            { name: '작별 모션', s: P, id: 'SR-OUT-004' },
            { name: '하원 시각 기록 + 보고서 enqueue', s: P, id: 'SR-OUT-006' },
          ],
        },
        {
          name: '율동 모드',
          image: 'demo/eduping/아기상어.png',
          subs: [
            { name: '동요 리스트 (dance_songs.json)', s: P, id: 'SR-PLAY-002' },
            { name: 'mp3 + trajectory 동기 시작', s: P, id: 'SR-PLAY-002' },
            { name: '율동 trajectory 녹화 도구', s: P, id: '(녹화 워크플로우)' },
          ],
        },
        {
          name: '무궁화꽃이 피었습니다',
          image: 'demo/eduping/무궁화꽃이-피었습니다.png',
          subs: [
            { name: '진입 단계 — 참가 아이 확정 (얼굴 + ByteTrack)', s: X, id: 'SR-PLAY-004' },
            { name: '준비 단계 — 거리 안내', s: X, id: 'SR-PLAY-004' },
            { name: '노래 단계 — mp3 + 눈 가리기 모션', s: X, id: 'SR-PLAY-004' },
            { name: '관찰 단계 — 다중 자세 인식 + 탈락 판정', s: X, id: 'SR-PLAY-004' },
            { name: '탈락 대기 / 종료 단계', s: X, id: 'SR-PLAY-004' },
          ],
        },
      ],
    },
    {
      id: 'noriarm',
      title: 'NoriArm',
      sub: 'OMX — 블럭쌓기 · OX 퀴즈 · 가게놀이',
      hero: 'demo/noriarm.png',
      features: [
        {
          name: '대기 모드',
          image: 'demo/noriarm/대기.png',
          subs: [
            { name: '표정 상시 표시', s: D, id: 'SR-UI-001' },
            { name: '호출어 · STT · TTS · 의도 분류', s: D, id: 'SR-VOICE-007/002/005/003' },
          ],
        },
        {
          name: '블럭쌓기 모드',
          image: 'demo/noriarm/블럭쌓기.png',
          subs: [
            { name: '참가자 확정 (얼굴 인식 1명)', s: X, id: 'SR-PLAY-003' },
            { name: '시작 안내 + 5개 블럭 ROI 사전 배치', s: X, id: 'SR-PLAY-003' },
            { name: 'ACT 모방학습 정책 진행', s: X, id: 'SR-PLAY-003' },
            { name: 'Top + Gripper 카메라 검증', s: X, id: 'SR-PLAY-003' },
          ],
        },
        {
          name: 'OX 퀴즈 모드',
          image: 'demo/noriarm/OX-퀴즈.png',
          subs: [
            { name: 'UI · vision 프리뷰 · URDF 뷰어', s: D, id: 'SR-PLAY-010' },
            { name: '문제 추출 + 5초 카운트다운', s: D, id: 'SR-PLAY-010' },
            { name: '손 터치 검출 (mediapipe Hands)', s: D, id: 'SR-PLAY-011' },
            { name: '정답 trajectory 재생 (rule_based)', s: D, id: 'SR-PLAY-010' },
            { name: '세션 API + 이벤트 SSE', s: X, id: 'SR-PLAY-013' },
            { name: 'smolVLA 대안 정책', s: X, id: 'SR-PLAY-012' },
          ],
        },
        {
          name: '가게놀이 모드',
          subs: [
            { name: '진입 + 모형 3종 ROI 검증', s: X, id: 'SR-PLAY-009' },
            { name: '요청 대기 (TTS "뭐 줄까?")', s: X, id: 'SR-PLAY-009' },
            { name: '요청 수신 (STT + 의도 분류)', s: X, id: 'SR-PLAY-009' },
            { name: '픽업 (Top + Gripper 검증 + 정책)', s: X, id: 'SR-PLAY-009' },
            { name: '전달 + ROI 비어있음 검출', s: X, id: 'SR-PLAY-009' },
          ],
        },
        {
          name: '게임 프레임워크 (공통 기반)',
          subs: [
            { name: '게임 매니페스트 (game.yaml)', s: X, id: 'SR-NORI-001' },
            { name: '정책 인터페이스 (rule_based / smolvla)', s: X, id: 'SR-NORI-002' },
            { name: '런처 CLI (`run --game --target`)', s: X, id: 'SR-NORI-003' },
            { name: '하드웨어 가용성 검증', s: X, id: 'SR-NORI-004' },
            { name: '동적 launch 생성 (sim/real)', s: X, id: 'SR-NORI-005' },
            { name: '타깃 자동 감지 (`/api/noriarm/health`)', s: X, id: 'SR-NORI-006' },
            { name: '세션 라이프사이클 (SSE)', s: X, id: 'SR-NORI-007' },
            { name: '수동 target override', s: X, id: 'SR-NORI-008' },
          ],
        },
      ],
    },
  ];

  const portal = [
    {
      id: 'parent',
      title: 'Parent',
      sub: '학부모용 — 로그인 · 자녀 · 등하원 · 메뉴 · 사진 · 보고서',
      hero: 'demo/parent.png',
      features: [
        { name: '로그인 · 계정', image: 'demo/parent/login.png', subs: [
          { name: '이메일 + 비밀번호 로그인', s: D, id: 'SR-PAR-006' },
          { name: '비밀번호 변경', s: D, id: 'SR-PAR-007' },
        ]},
        { name: '자녀 선택', image: 'demo/parent/home.png', subs: [
          { name: '매핑된 자녀 리스트 + 선택', s: D, id: 'SR-PAR-008' },
        ]},
        { name: '등 · 하원 조회', image: 'demo/parent/attendance.png', subs: [
          { name: '선택 자녀의 등 · 하원 상태 표시', s: D, id: 'SR-PAR-001' },
        ]},
        { name: '점심메뉴 (달력)', image: 'demo/parent/menu.png', subs: [
          { name: '월간 달력 · day-of-month 매칭', s: D, id: 'SR-PAR-004' },
        ]},
        { name: '사진첩', image: 'demo/parent/photos.png', subs: [
          { name: '자녀 포함 사진 리스트 · 다운로드', s: D, id: 'SR-PHOTO-003' },
        ]},
        { name: '일과 보고서', image: 'demo/parent/report.png', subs: [
          { name: '자녀별 일자별 보고서 조회', s: D, id: 'SR-RPT-002' },
        ]},
      ],
    },
    {
      id: 'teacher',
      title: 'Teacher',
      sub: '교사용 — 등록 · 출결 · 자녀 정보 · 보고서 · 메뉴',
      hero: 'demo/teacher.png',
      features: [
        { name: '로그인', image: 'demo/teacher/login.png', subs: [
          { name: '교사 계정 로그인 (세션 쿠키)', s: D, id: 'SR-REG-008' },
        ]},
        { name: '아이 · 학부모 등록', image: 'demo/teacher/children-new.png', subs: [
          { name: '자녀 정보 입력 (이름·생년월일·반)', s: D, id: 'SR-REG-001' },
          { name: '학부모 정보 입력 + 계정 발급', s: D, id: 'SR-REG-002' },
          { name: '입력 검증 (클라이언트 + Pydantic)', s: D, id: 'SR-REG-003' },
          { name: '얼굴 캡처 — 15장 다각도', s: D, id: 'SR-REG-005' },
          { name: '얼굴 캡처 — anti-spoofing (liveness)', s: X, id: 'SR-REG-010' },
          { name: '얼굴 임베딩 저장 (DB BLOB)', s: D, id: 'SR-REG-006' },
        ]},
        { name: '출결 보드', image: 'demo/teacher/dashboard.png', subs: [
          { name: '실시간 출결 표시', s: D, id: 'SR-OPS-002' },
        ]},
        { name: '자녀 정보 보기', image: 'demo/teacher/children.png', subs: [
          { name: '자녀 기본 정보 표시', s: P, id: 'SR-OPS-015' },
          { name: '학부모 정보 보기', s: D, id: 'SR-OPS-016' },
          { name: '등록 사진 presigned URL', s: X, id: 'SR-OPS-015' },
        ]},
        { name: '일과 보고서', image: 'demo/teacher/reports.png', subs: [
          { name: '자녀별 일자별 보고서 조회', s: D, id: 'SR-OPS-017' },
          { name: '보고서 인라인 편집', s: D, id: 'SR-OPS-018' },
        ]},
        { name: '점심메뉴 (달력)', image: 'demo/teacher/menu.png', subs: [
          { name: '월간 달력 표시', s: D, id: 'SR-OPS-014' },
        ]},
      ],
    },
    {
      id: 'doctor',
      title: 'Doctor',
      sub: '의사용 — 원격 진찰 (요구사항 미정의)',
      features: [
        { name: '로그인 · 계정', subs: [
          { name: '의사 계정 정의 · 권한', s: X, id: '(미정의)' },
        ]},
        { name: '원격 진찰', subs: [
          { name: '화상 연결 · 진료 세션', s: X, id: '(미정의)' },
          { name: '카메라 스트리밍 (EduPing)', s: X, id: '(미정의)' },
        ]},
        { name: '건강 기록', subs: [
          { name: '아이별 건강 기록 조회', s: X, id: '(미정의)' },
          { name: '처방 · 메모 작성', s: X, id: '(미정의)' },
        ]},
      ],
    },
  ];

  return { robot, portal };
})();

// 공통 헬퍼 (양쪽 페이지에서 재사용)
window.PINGDER_UTIL = {
  LABEL: { done: 'DONE', partial: 'PARTIAL', planned: 'PLANNED' },
  tally(subs) {
    const t = { done: 0, partial: 0, planned: 0 };
    for (const s of subs) t[s.s]++;
    return t;
  },
  pct(t) {
    const total = t.done + t.partial + t.planned;
    if (!total) return { done: 0, partial: 0, planned: 0, total: 0 };
    return {
      done: (t.done / total) * 100,
      partial: (t.partial / total) * 100,
      planned: (t.planned / total) * 100,
      total,
    };
  },
  rollup(t) {
    if (t.done === 0 && t.partial === 0) return 'planned';
    if (t.partial === 0 && t.planned === 0) return 'done';
    return 'partial';
  },
};
