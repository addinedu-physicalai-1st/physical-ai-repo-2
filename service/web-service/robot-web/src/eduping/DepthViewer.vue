<script setup lang="ts">
/**
 * EduPing 뎁스카메라 뷰 — D435 클라우드 + 하이파이브.
 *
 * D435 한 대로 두 입력 채널:
 *   - color (RGB): MediaPipe HandLandmarker 손 검출 → palm 안정 시 POST hand-target.
 *   - depth: point cloud 렌더 + 손 3D unproject + obstacle gate.
 *
 * 흐름 (face verification 우회 모드 — handEnabled 항상 true):
 *   1. 마운트 직후: 양팔 home 복귀 + 손 추적 활성.
 *   2. D435 color frame → HandLandmarker palm 검출.
 *   3. palm 안정 시 highfive scripted gesture 발사.
 *   4. unmount 시 양팔 home 복귀.
 *
 * 향후 등원 모드 이관 시 face verification 부활 — git history 의 setupFaceDetector
 * 패턴 복원.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import OpenarmViewer from './OpenarmViewer.vue';
import WarningModal from '@/common/WarningModal.vue';
import { useEdupingStateWs } from '@/composables/useEdupingStateWs';
import {
  HIGHFIVE_HEARTBEAT_INTERVAL_MS,
  HIGHFIVE_MAX_Z_M,
  HIGHFIVE_MIN_Z_M,
  HIGHFIVE_PALM_MOVE_M,
  HIGHFIVE_PALM_STABLE_EPS_M,
  HIGHFIVE_PALM_STABLE_FRAMES,
  HIGHFIVE_POST_INTERVAL_MS,
  isPalmFacingCamera,
  mirrorArmForHand,
  PalmOneEuro,
  palmDistanceM,
  palmFromFrame,
  type Palm3D,
  postHighfiveHandTarget,
  postReturnHomeSim,
} from './highfiveHandTarget';
import { useDepthStream, type DecodedDepthFrame } from './useDepthStream';
import { useHandTracker, type HandPoint } from './useHandTracker';
import type { HandBbox } from './useDepthCloudInScene';

const stream = useDepthStream('eduping');
const depthStatusLabel = computed(() => {
  switch (stream.status.value) {
    case 'streaming':
      return '뎁스 연결됨';
    case 'open':
      return waitingProducer.value ? '카메라 스트림 대기' : 'WS 연결 (프레임 대기)';
    case 'connecting':
      return '뎁스 연결 중…';
    default:
      return '뎁스 끊김';
  }
});
const waitingProducer = computed(() => {
  if (stream.status.value !== 'open') return false;
  const last = stream.lastFrameAtMs.value;
  return last === 0 || Date.now() - last > 3000;
});

const depthHint = computed(() => {
  if (stream.status.value === 'streaming') return '';
  if (stream.status.value === 'open') {
    if (waitingProducer.value) {
      return 'WS OK — D435 producer 없음: ros2 launch eduarm d435_depth.launch.py (또는 d435-streamer.service)';
    }
    return 'D435 streamer·USB 확인 (journalctl -u d435-streamer)';
  }
  return 'run_server.sh (streaming :8100) 확인 후 재시도';
});
const fps = ref<number>(0);
const nearestMeters = ref<number | null>(null);
const handMeters = ref<number | null>(null);
const handLoading = ref<boolean>(false);
const handBbox = ref<HandBbox | null>(null);
/** high-five arm command status (sim / real via control-service → highfive_node). */
const armStatus = ref<string>('');
// 실물 OpenArm 동기화 — RecorderControls 와 같은 /api/eduping/state WS 로 'real_active'
// 감지 + 별도 토글로 highfive trajectory 를 실제 follower 로 forward.
const stateWs = useEdupingStateWs();
const realActive = computed(() => stateWs.realActive.value);
const highfiveRealActiveServer = computed(() => stateWs.highfiveRealActive.value);
const liveHighfiveReal = ref(false);     // 토글 사용자 의도 (낙관적)
const highfiveSyncBusy = ref(false);     // 토글 POST 진행 중 잠금
const lastSyncError = ref<string>('');
const realConfirmOpen = ref(false);

// 실물 끊기면 자동 OFF (controller 가 사라져서 forward 의미 없어짐).
watch(realActive, (real) => {
  if (!real && liveHighfiveReal.value) {
    liveHighfiveReal.value = false;
  }
});
// 서버 상태가 OFF 로 바뀌면 (teleop 켜져서 자동 OFF 됐다든지) UI 도 OFF.
watch(highfiveRealActiveServer, (val) => {
  if (!val && liveHighfiveReal.value) {
    liveHighfiveReal.value = false;
  }
});

async function postHighfiveSync(enabled: boolean): Promise<void> {
  highfiveSyncBusy.value = true;
  try {
    const res = await fetch('/api/eduping/highfive/sync', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ enabled }),
    });
    const json = await res.json().catch(() => null);
    if (!res.ok || (json && json.switch === 'failed')) {
      lastSyncError.value = String(json?.hint ?? json?.detail ?? `동기화 ${enabled ? '켜기' : '끄기'} 실패`);
      liveHighfiveReal.value = !enabled;   // rollback
    } else {
      lastSyncError.value = '';
    }
  } catch (err) {
    lastSyncError.value = (err as Error).message;
    liveHighfiveReal.value = !enabled;
  } finally {
    highfiveSyncBusy.value = false;
  }
}

function onToggleHighfiveReal(): void {
  if (highfiveSyncBusy.value || !realActive.value) return;
  if (liveHighfiveReal.value) {
    // OFF — 확인 없이 즉시
    liveHighfiveReal.value = false;
    void postHighfiveSync(false);
  } else {
    // ON — 확인 모달
    realConfirmOpen.value = true;
  }
}
function onRealConfirmed(): void {
  liveHighfiveReal.value = true;
  void postHighfiveSync(true);
}

/** 현재 인식된 어린이 (DB 매칭). null = 카메라 앞에 등록 어린이 없음.
 * TODO: 현재는 face verification 우회 — hand 만 잡히면 high-five. 등원 모드 이관 시
 * currentKid 게이트 다시 활성화 (handEnabled = computed(() => currentKid.value !== null)). */
const currentKid = ref<{ id: number; name: string } | null>(null);
const kidExpireAt = ref<number>(0);
/** hand 항상 추적 — face verification 우회 모드. */
const handEnabled = computed(() => true);

let expireTimer: ReturnType<typeof setInterval> | null = null;
/** Picker 에서 선택한 카메라. 특수값 D435_WS_ID 면 streamer WS 의 color 사용 — D435 가
 *  pyrealsense2 에 점유돼 getUserMedia 로 접근 불가하므로 별도 source 로 노출. */
const D435_WS_ID = '__d435_ws__';
interface CameraOption { deviceId: string; label: string; }
const cameras = ref<CameraOption[]>([]);
const selectedDeviceId = ref<string>(D435_WS_ID);   // D435 default
let camStream: MediaStream | null = null;
const previewVideoRef = ref<HTMLVideoElement | null>(null);
/** D435 WS 모드 visible canvas — preview 용 (face_detection 우회 모드라 추가 컨슈머 없음). */
const d435DetectCanvasRef = ref<HTMLCanvasElement | null>(null);
// face verification 우회 모드 — latestColorBlob / FACE_DETECT 미사용.

/** Per-hand state — 양손 동시 high-five 지원. key 는 MediaPipe handedness ('Left'|
 *  'Right'). 각 손의 POST 타이밍·안정성·motion-busy 가 독립적이라 한 손이 추종 중
 *  이어도 다른 손이 동시에 별개 IK 발사 가능. */
interface HandSideState {
  lastPostAt: number;
  motionBusyUntil: number;
  stableFrames: number;
  lastSamplePalm: Palm3D | null;
  lastPostedPalm: Palm3D | null;
  /** One Euro low-pass on palm xyz — MediaPipe landmark jitter (±1cm) 가 IK
   *  재계산을 흔드는 걸 줄임. 손이 사라지면 reset. */
  filter: PalmOneEuro;
}
function newHandState(): HandSideState {
  return {
    lastPostAt: 0,
    motionBusyUntil: 0,
    stableFrames: 0,
    lastSamplePalm: null,
    lastPostedPalm: null,
    filter: new PalmOneEuro(),
  };
}
const handStates: Record<'Left' | 'Right' | 'Unknown', HandSideState> = {
  Left: newHandState(),
  Right: newHandState(),
  Unknown: newHandState(),
};
/** Hand 가 마지막으로 valid (in-box) 으로 잡힌 시각. 0 = 아직 한 번도 안 잡힘. */
let lastHandAtMs = 0;
/** Return-home 이 이미 발사된 상태. 손이 다시 in-box 로 나타나면 false 로 reset. */
let returnedHome = true;
/** Hand undetecting 빠른 return — 한두 frame blip 은 흡수 (7.5Hz detect 라
 *  1 frame ≈ 130ms), 실제 손 사라지면 1초 이내 home. */
const HAND_LOST_HOME_MS = 800;
/** Frustum far plane (m) — DepthViewer 의 OpenarmViewer 에 전달한 depth-frustum-far-m 과 일치.
 *  손이 이 거리보다 멀어지면 즉시 home (HAND_LOST_HOME_MS 안 기다림). */
const HAND_BEYOND_FRUSTUM_M = 0.55;
/** High-five gesture 1회 길이 (highfive_node 4-phase ≈ 8.6s) + 마진. hand-target 을
 *  POST 한 뒤 이 시간 동안은 home 복귀를 보내지 않는다 — 이미 red ball 을 향해 commit
 *  된 reach 를, 장애물이나 팔 자체가 손을 잠깐 가려 detection 이 끊겨도, 끝까지 진행한다.
 *  gesture 는 스스로 raise→tap→rebound→home 으로 마무리하므로 별도 복귀가 불필요.
 *  (사용자 요청: "장애물이 와도 red ball 로 가라, 그냥 돌아오지 마라".) */
const GESTURE_HOLD_MS = 9000;
/** 마지막 hand-target POST 시각 + GESTURE_HOLD_MS. 이 시각 전이면 maybeReturnHome 무시. */
let gestureHoldUntil = 0;

/** Detection downsample — 15Hz detection 이 main thread 점유 + Vue reactivity 폭발해
 *  카메라 lagging. N=2 (7.5Hz) 로 절반 → frame decode + cloud render 여유 ↑.
 *  POST throttle 150ms 와 결합해 손 움직임 반응성 여전히 충분. */
const DETECT_EVERY_N = 2;
/** bbox 패딩 (image 픽셀 비율) — 손 윤곽 + 손목 약간 더 포함. */
const HAND_BBOX_PAD = 0.08;
let detectCounter = 0;
let firstResultReceived = false;
let tracker: ReturnType<typeof useHandTracker> | null = null;

let frameCount = 0;
let fpsTimer: ReturnType<typeof setInterval> | null = null;
let lastFpsCheck = 0;

function handleFrame(frame: DecodedDepthFrame): void {
  frameCount++;
  nearestMeters.value = frame.depthMinMm > 0 ? frame.depthMinMm / 1000 : null;

  // D435 color frame 으로 hand detection — preview 카메라 선택과 무관.
  // palmFromFrame 이 depth 가 필요해서 (3D 언프로젝션) 어차피 D435 color 가 hand
  // detection 의 정확한 source. USB 카메라 선택 시에도 hand 추적은 D435 기준으로.
  // D435 WS 모드 (preview 도 D435) 인 경우엔 canvas 에 한 번 그려서 visual preview 유지.
  detectCounter = (detectCounter + 1) % DETECT_EVERY_N;
  const shouldDetectHand = handEnabled.value && tracker !== null && detectCounter === 0;
  // Preview 썸네일 JPEG decode 도 detection cadence (detectCounter===0, ~7.5Hz) 로만.
  // 예전엔 D435_WS 모드에서 매 frame (~15Hz) bitmap 을 디코드해 메인 스레드를 두 배로
  // 점유했다 (preview 썸네일은 7.5Hz 로 충분하고, hand detection 도 같은 bitmap 재사용).
  // depth cloud 렌더는 별도 composable 이라 영향 없음.
  const drawPreview = selectedDeviceId.value === D435_WS_ID && detectCounter === 0;
  const cvs = drawPreview ? d435DetectCanvasRef.value : null;
  const t = tracker;
  if (shouldDetectHand || drawPreview) {
    void createImageBitmap(frame.colorBlob).then((bm) => {
      if (cvs) {
        if (cvs.width !== bm.width) cvs.width = bm.width;
        if (cvs.height !== bm.height) cvs.height = bm.height;
        const ctx = cvs.getContext('2d');
        if (ctx) ctx.drawImage(bm, 0, 0);
      }
      if (shouldDetectHand && t) {
        // tasks-vision 의 detectForVideo 는 synchronous — return 후 즉시 bitmap 해제.
        t.detect(bm);
      }
      bm.close();
    }).catch((e) => { console.warn('[depth] preview/detect:', e); });
  }

  // 손 추적 결과 처리 (검출 호출은 위 WS 모드 블록에서 ImageBitmap 으로 수행).
  // getUserMedia 모드일 땐 hand 추적 미지원 (D435 WS 모드 전용). 추후 getUserMedia
  // 손 추적 필요 시 video element 경로 추가.
  if (handEnabled.value && tracker) {
    // MediaPipe 가 첫 onResults 를 한 번 부르면 트래커 자체는 살아있는 것 — 손이
    // 실제로 잡혔는지 (hand.value !== null) 와 무관하게 로딩 표시를 끈다.
    // 이전 로직은 손이 안 보이면 'loading…' 이 영원히 안 풀려 사용자가 혼란.
    if (!firstResultReceived && tracker.ready.value) {
      firstResultReceived = true;
      handLoading.value = false;
    }
    // 손 3D 거리 + bbox (cloud 필터링용). 양손 시 UNION bbox 로 둘 다 silhouette
    // 에 보이게 함.
    const allHands = tracker.hands.value;
    if (allHands.length === 0) {
      handMeters.value = null;
      handBbox.value = null;
    } else {
      // primary hand depth (UI HUD 용 — first hand)
      const h0 = allHands[0];
      const u0 = Math.round(Math.min(Math.max(h0.u, 0), frame.depthW - 1));
      const v0 = Math.round(Math.min(Math.max(h0.v, 0), frame.depthH - 1));
      const raw0 = frame.depth[v0 * frame.depthW + u0];
      handMeters.value = raw0 > 0 ? raw0 * frame.depthScale : null;
      // union bbox 계산 — 모든 detected hands 의 landmark 통합.
      let uMin = Infinity, uMax = -Infinity, vMin = Infinity, vMax = -Infinity;
      for (const h of allHands) {
        for (const lm of h.landmarks) {
          if (lm.u < uMin) uMin = lm.u;
          if (lm.u > uMax) uMax = lm.u;
          if (lm.v < vMin) vMin = lm.v;
          if (lm.v > vMax) vMax = lm.v;
        }
      }
      const padU = (uMax - uMin) * HAND_BBOX_PAD + 6;
      const padV = (vMax - vMin) * HAND_BBOX_PAD + 6;
      handBbox.value = {
        uMin: Math.max(0, uMin - padU),
        uMax: Math.min(frame.depthW - 1, uMax + padU),
        vMin: Math.max(0, vMin - padV),
        vMax: Math.min(frame.depthH - 1, vMax + padV),
      };
    }

    // 양손 모두 처리 (max 2). 각 손 → 독립 POST → highfive_node 가 world Y 기반
    // 으로 자동 arm 선택 (mirror).
    tryPostAllHands(frame);
    // 손 lost 또는 frustum 밖 → 일정 시간 후 home 복귀. 사용자가 손을 내리면
    // 팔도 home 으로 따라 내려가야 자연스럽다.
    maybeReturnHome();
  } else if (!handEnabled.value) {
    handMeters.value = null;
    handBbox.value = null;
    armStatus.value = '';
  }
}

/** Arm 이 hand state 를 그대로 반영:
 *  - 손 box 안 → tryPostHighfive 가 gesture 발사 (정상 추종)
 *  - 손이 box 뒤쪽 으로 빠짐 (z > HAND_BEYOND_FRUSTUM_M) → 즉시 home 복귀
 *  - 손 detection 끊김 OR z < NEAR → HAND_LOST_HOME_MS 후 home 복귀
 *    (짧은 detection blip 으로 home 가지 않게 grace period)
 *  손이 box 에 다시 들어오면 reset, 다음 in-box 동안 다시 follow. */
function maybeReturnHome(): void {
  if (!tracker) return;
  const h = tracker.hand.value;
  const z = handMeters.value;
  const handValid =
    h !== null && z !== null
    && z >= HIGHFIVE_MIN_Z_M && z <= HAND_BEYOND_FRUSTUM_M;
  const now = Date.now();
  if (handValid) {
    lastHandAtMs = now;
    returnedHome = false;
    return;
  }
  // Gesture 진행 중이면 home 으로 yank 하지 않는다 — red ball 로 commit 된 reach 를
  // 끝까지. 장애물/팔이 손을 잠깐 가려 detection 이 끊겨도 gesture 가 스스로 마무리한다.
  if (now < gestureHoldUntil) return;
  if (returnedHome) return;
  const beyond = z !== null && z > HAND_BEYOND_FRUSTUM_M;
  const lostFor = lastHandAtMs === 0 ? Infinity : now - lastHandAtMs;
  // 뒤로 빠짐 (명시적) → 즉시. 그 외 (detection lost) → grace 후.
  if (!beyond && lostFor < HAND_LOST_HOME_MS) return;
  returnedHome = true;
  // reset per-hand state (양쪽 다)
  for (const side of ['Left', 'Right', 'Unknown'] as const) {
    handStates[side] = newHandState();
  }
  armStatus.value = beyond ? '팔: 손 뒤로 — home 복귀' : '팔: 손 사라짐 — home 복귀';
  void postReturnHomeSim();
}

/** Process ALL detected hands (max 2) — each goes through filters + POSTs
 *  independently with its own per-side state. */
function tryPostAllHands(frame: DecodedDepthFrame): void {
  if (!tracker) return;
  const list = tracker.hands.value;
  if (list.length === 0) {
    armStatus.value = '팔: 손 찾는 중…';
    return;
  }
  const statuses: string[] = [];
  for (const h of list) {
    const s = tryPostHighfive(frame, h);
    statuses.push(s);
  }
  armStatus.value = statuses.join(' | ');
}

/** Process a single hand. Returns a short status string for the HUD. */
function tryPostHighfive(frame: DecodedDepthFrame, h: HandPoint): string {
  const side = h.handedness; // 'Left' | 'Right' | 'Unknown'
  const tag = side === 'Left' ? 'L' : side === 'Right' ? 'R' : '?';
  const st = handStates[side];
  const palmResult = palmFromFrame(frame, h);
  if (!palmResult.ok) {
    st.stableFrames = 0;
    st.lastSamplePalm = null;
    st.filter.reset();
    return palmResult.reason === 'no_depth'
      ? `${tag}: depth 없음`
      : `${tag}: 범위 밖`;
  }
  // 손이 처음 보였거나 lost-recover 한 직후엔 filter prev 이 null 이라 첫 값
  // 그대로 통과 — 이후엔 jitter 만 흡수, 진짜 wave 동작 lag 없음.
  const palm = st.filter.step(palmResult.palm, Date.now());
  // ── precision filter 1: handedness confidence ─────────────────────────────
  // MediaPipe 의 LEFT 손 handedness 분류는 RIGHT 보다 평균 score 가 낮아 0.88 임계는
  // LEFT 만 자주 reject (왼손 detection rate 낮은 원인). 0.70 으로 낮추면서 palm
  // geometry + depth consistency + palm-facing 의 후속 필터가 false positive 차단.
  if (h.score < 0.70) {
    st.stableFrames = 0;
    st.lastSamplePalm = null;
    return `${tag}: 신뢰도 ${h.score.toFixed(2)}`;
  }
  // ── precision filter 2: bbox size ─────────────────────────────────────────
  const HAND_REAL_WIDTH_M = 0.09;
  const expectedPxW = (HAND_REAL_WIDTH_M * frame.fx) / palm.z;
  let lmUMin = Infinity, lmUMax = -Infinity, lmVMin = Infinity, lmVMax = -Infinity;
  for (const lm of h.landmarks) {
    if (lm.u < lmUMin) lmUMin = lm.u;
    if (lm.u > lmUMax) lmUMax = lm.u;
    if (lm.v < lmVMin) lmVMin = lm.v;
    if (lm.v > lmVMax) lmVMax = lm.v;
  }
  const bboxMax = Math.max(lmUMax - lmUMin, lmVMax - lmVMin);
  if (bboxMax < expectedPxW * 0.3) {
    st.stableFrames = 0;
    st.lastSamplePalm = null;
    return `${tag}: bbox ${Math.round(bboxMax)}px`;
  }
  // ── precision filter 3: palm geometry ─────────────────────────────────────
  // 실제 손바닥 길이 (wrist landmark 0 → middle MCP landmark 9) ≈ 8~11cm.
  // pixel size = REAL_M * fx / z. z=0.4m, fx=606 면 121~166px. 절반 미만이면
  // 가짜 landmark 분포 (얼굴/팔뚝 등) 로 간주.
  const wrist = h.landmarks[0];
  const midMcp = h.landmarks[9];
  if (wrist === undefined || midMcp === undefined) {
    st.stableFrames = 0; st.lastSamplePalm = null;
    return `${tag}: landmark 부족`;
  }
  const palmPx = Math.sqrt(
    (wrist.u - midMcp.u) ** 2 + (wrist.v - midMcp.v) ** 2,
  );
  const expectedPalmPx = (0.09 * frame.fx) / palm.z; // 9cm palm
  if (palmPx < expectedPalmPx * 0.4) {
    st.stableFrames = 0; st.lastSamplePalm = null;
    return `${tag}: palm ${Math.round(palmPx)}px (예상 ${Math.round(expectedPalmPx)}px)`;
  }
  // ── precision filter 4: depth consistency ─────────────────────────────────
  const SAMPLE_LANDMARKS = [0, 4, 8, 12, 20];
  const depths: number[] = [];
  for (const idx of SAMPLE_LANDMARKS) {
    const lm = h.landmarks[idx];
    if (lm === undefined) continue;
    const u = Math.round(Math.min(Math.max(lm.u, 0), frame.depthW - 1));
    const v = Math.round(Math.min(Math.max(lm.v, 0), frame.depthH - 1));
    const raw = frame.depth[v * frame.depthW + u];
    if (raw > 0) depths.push(raw * frame.depthScale);
  }
  if (depths.length < 3) {
    st.stableFrames = 0;
    st.lastSamplePalm = null;
    return `${tag}: depth sample 부족`;
  }
  const meanDepth = depths.reduce((a, b) => a + b, 0) / depths.length;
  let maxDev = 0;
  for (const d of depths) {
    const dev = Math.abs(d - meanDepth);
    if (dev > maxDev) maxDev = dev;
  }
  // 0.12 → 0.08 — 실제 손은 두께 5-7cm, 8cm 면 안전 마진. ear+face 같이 분산된
  // landmark 는 10cm+ 편차로 더 잘 걸림.
  if (maxDev > 0.08) {
    st.stableFrames = 0;
    st.lastSamplePalm = null;
    return `${tag}: depth ${(maxDev * 100).toFixed(0)}cm`;
  }
  // ── precision filter 5: palm orientation ──────────────────────────────────
  // High-five 는 palm 제스처 — backhand / 옆면 (profile) 은 reject. 손이 살짝
  // 기울면 detection threshold 가 0.35 라 detection 자체는 유지되지만 palm 판정은
  // PALM_FACING_DEADBAND (sin ≈ 0.35) 안쪽이면 ambiguous 로 통과시킴 (highfiveHandTarget
  // 의 deadband 가 backhand vs 옆면 vs palm 구분).
  if (!isPalmFacingCamera(h)) {
    st.stableFrames = 0;
    st.lastSamplePalm = null;
    return `${tag}: 손등 (✋ 보여주세요)`;
  }
  // ── stability + post throttle ─────────────────────────────────────────────
  if (st.lastSamplePalm !== null
    && palmDistanceM(palm, st.lastSamplePalm) < HIGHFIVE_PALM_STABLE_EPS_M) {
    st.stableFrames += 1;
  } else {
    st.stableFrames = 1;
  }
  st.lastSamplePalm = palm;

  const now = Date.now();
  if (now < st.motionBusyUntil) return `${tag}: 도달중`;
  if (st.stableFrames < HIGHFIVE_PALM_STABLE_FRAMES) {
    return `${tag}: 고정중`;
  }
  if (st.lastPostedPalm !== null
    && palmDistanceM(palm, st.lastPostedPalm) < HIGHFIVE_PALM_MOVE_M) {
    // 손이 정지해 있어도 heartbeat 로 server 의 hand-lost 타이머 (1.2s) 가 만료
    // 되지 않게 한다. 400ms 마다 같은 좌표로 POST — 새 gesture 는 cooldown 으로
    // 막혀 trigger 안 되고, last_hand_seen_at_s 만 refresh 됨.
    if (now - st.lastPostAt < HIGHFIVE_HEARTBEAT_INTERVAL_MS) {
      return `${tag}: 유지 ✋ ${palm.z.toFixed(2)}m`;
    }
    // fall through — heartbeat POST 발사 (lastPostedPalm 갱신 안 함, 다음 비교 유효)
  }
  if (now - st.lastPostAt < HIGHFIVE_POST_INTERVAL_MS) {
    return `${tag}: 보내는중`;
  }
  st.lastPostAt = now;
  // 이 POST 가 gesture 를 fire 하면 ~8.6s 동안 reach 가 진행된다 — 그 동안 손이 가려져도
  // home 복귀를 막기 위해 hold 창을 갱신 (maybeReturnHome 가 이 시각까지 무시).
  gestureHoldUntil = now + GESTURE_HOLD_MS;
  // arm hint = MediaPipe handedness 기반 mirror — server 가 world Y 추측 대신
  // browser 가 명시적으로 알려줌. 사용자 LEFT 손 → robot RIGHT 팔.
  const armHint = mirrorArmForHand(side);
  void postHighfiveHandTarget(palm, armHint).then((ok) => {
    if (!ok) return;
    st.lastPostedPalm = palm;
    st.motionBusyUntil = Date.now() + HIGHFIVE_POST_INTERVAL_MS;
  }).catch(() => { /* swallow */ });
  const armLabel = armHint === 'left' ? '←L' : armHint === 'right' ? 'R→' : '?';
  return `${tag}${armLabel}: ${palm.z.toFixed(2)}m`;
}

/** currentKid 가 비-null 로 바뀔 때 호출 — 손 추적기 초기화·상태 reset. */
function activateHandTracking(): void {
  if (tracker === null) tracker = useHandTracker();
  detectCounter = DETECT_EVERY_N - 1;
  handLoading.value = !firstResultReceived;
  for (const side of ['Left', 'Right', 'Unknown'] as const) {
    handStates[side] = newHandState();
  }
}

/** currentKid 가 null 로 바뀔 때 호출 — 손 상태 cleanup + 양팔 home 복귀.
 * 진행 중 highfive trajectory 가 있으면 끝날 때까지 기다린 후 return-home 발사 —
 * sim_twin 의 trajectory 교체로 인한 mid-motion "jump" 방지. */
function deactivateHandTracking(): void {
  handMeters.value = null;
  handBbox.value = null;
  handLoading.value = false;
  armStatus.value = '';
  // 가장 늦은 motionBusyUntil 까지 기다림 (둘 중 큰 값).
  let maxBusy = 0;
  for (const side of ['Left', 'Right', 'Unknown'] as const) {
    if (handStates[side].motionBusyUntil > maxBusy) {
      maxBusy = handStates[side].motionBusyUntil;
    }
    handStates[side] = newHandState();
  }
  const waitMs = Math.max(0, maxBusy - Date.now());
  setTimeout(() => { void postReturnHomeSim(); }, waitMs);
}

async function listCameras(): Promise<void> {
  let devs = await navigator.mediaDevices.enumerateDevices();
  if (devs.filter((d) => d.kind === 'videoinput').every((d) => !d.label)) {
    try {
      const tmp = await navigator.mediaDevices.getUserMedia({ video: true });
      tmp.getTracks().forEach((t) => t.stop());
      devs = await navigator.mediaDevices.enumerateDevices();
    } catch { /* ignore */ }
  }
  const usbCams: CameraOption[] = devs
    .filter((d) => d.kind === 'videoinput')
    .map((d) => ({ deviceId: d.deviceId, label: d.label || `Camera ${d.deviceId.slice(0, 6)}` }));
  // D435 streamer pseudo-device 항상 첫 번째 + 라벨 명확화. high-five 추적의 정식
  // 입력 (palm 3D 언프로젝션이 depth 가 필요) — USB 카메라는 보조 face preview 용도.
  cameras.value = [
    { deviceId: D435_WS_ID, label: 'D435 RGB (하이파이브 입력)' },
    ...usbCams,
  ];
  // localStorage 에 마지막 선택 저장 → 새로고침 후에도 동일 카메라. 없으면 D435 default.
  const remembered = (() => {
    try { return localStorage.getItem('depth-viewer-cam') ?? ''; } catch { return ''; }
  })();
  if (remembered && cameras.value.some((c) => c.deviceId === remembered)) {
    selectedDeviceId.value = remembered;
  }
}

function stopGetUserMediaStream(): void {
  if (camStream) {
    camStream.getTracks().forEach((t) => t.stop());
    camStream = null;
  }
  const v = previewVideoRef.value;
  if (v) v.srcObject = null;
}

async function setupCamera(): Promise<void> {
  // D435 WS 모드: getUserMedia 안 씀. handleFrame 이 img + face_detection 갱신.
  if (selectedDeviceId.value === D435_WS_ID) {
    stopGetUserMediaStream();
    return;
  }
  stopGetUserMediaStream();
  camStream = await navigator.mediaDevices.getUserMedia({
    video: {
      deviceId: { exact: selectedDeviceId.value },
      width: { ideal: 640 },
      height: { ideal: 480 },
    },
    audio: false,
  });
  const v = previewVideoRef.value;
  if (v) {
    v.srcObject = camStream;
    await v.play().catch(() => { /* autoplay race */ });
  }
  // face_detection 우회 모드 — getUserMedia 모드의 rAF tick 는 dead. hand 추적은
  // handleFrame 에서 D435 color 로 통일 처리. 등원 모드 이관 시 face_detection 부활
  // 하려면 useFaceDetector import + tick rAF 복구.
}

async function onCameraChange(): Promise<void> {
  // 선택 카메라 기억 — 새로고침 시 listCameras 가 복원.
  try { localStorage.setItem('depth-viewer-cam', selectedDeviceId.value); } catch { /* private mode */ }
  try {
    await setupCamera();
  } catch (e) {
    console.warn('camera switch failed:', e);
  }
}

// 자동 라이프사이클 — DepthViewer mount 시 backend 가 d435_camera + streamer +
// highfive_sim subprocess 띄움. unmount 시 SIGTERM. UI 가 뜨면 카메라 자동 ON,
// 페이지 닫으면 자동 OFF — D435 USB 점유 + ROS launch 부하 둘 다 자동 정리.
async function startDepthSession(): Promise<void> {
  try {
    const res = await fetch('/api/eduping/depth/session/start', { method: 'POST' });
    if (!res.ok) console.warn('[depth] session/start non-OK:', res.status);
    else console.info('[depth] session/start ok:', await res.json());
  } catch (e) {
    console.warn('[depth] session/start failed:', e);
  }
}
async function stopDepthSession(): Promise<void> {
  try {
    // sendBeacon — 페이지 닫힘 도중에도 reliable. fetch 는 unmount 후 abort 될 수 있음.
    const blob = new Blob([''], { type: 'application/json' });
    const sent = navigator.sendBeacon?.('/api/eduping/depth/session/stop', blob);
    if (!sent) await fetch('/api/eduping/depth/session/stop', { method: 'POST' });
  } catch (e) {
    console.warn('[depth] session/stop failed:', e);
  }
}

onMounted(() => {
  void startDepthSession();
  stream.onFrame(handleFrame);
  lastFpsCheck = performance.now();
  fpsTimer = setInterval(() => {
    const now = performance.now();
    const elapsed = (now - lastFpsCheck) / 1000;
    fps.value = Math.round(frameCount / elapsed);
    frameCount = 0;
    lastFpsCheck = now;
  }, 1000);
  void (async () => {
    await listCameras();
    await setupCamera().catch((e) => console.warn('initial camera setup:', e));
  })();
  expireTimer = setInterval(() => {
    if (currentKid.value !== null && Date.now() > kidExpireAt.value) {
      currentKid.value = null;
      deactivateHandTracking();
    }
  }, 500);
  // 부팅 자세 — 양팔 home (모든 joint 0).
  void postReturnHomeSim();
  // face verification 우회 모드 — handEnabled 가 항상 true 라 tracker 즉시 초기화.
  activateHandTracking();
  // 실물 sync 상태 WS 구독 시작.
  stateWs.start();
});

onBeforeUnmount(() => {
  if (fpsTimer) clearInterval(fpsTimer);
  if (expireTimer) clearInterval(expireTimer);
  stopGetUserMediaStream();
  stream.stop();
  // bypass 모드는 currentKid 가 항상 null 이라 위 게이트로는 home 복귀가 안 됨 —
  // 무조건 한 번 post 해서 unmount 시 안전한 자세로 되돌린다.
  void postReturnHomeSim();
  if (tracker) void tracker.close();
  void stopDepthSession();
  // unmount 시 실물 동기화도 자동 OFF — 사용자 시야 떠나 있는 동안 실물 잘못 따라가지 않게.
  if (highfiveRealActiveServer.value) {
    void fetch('/api/eduping/highfive/sync', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ enabled: false }),
    }).catch(() => { /* swallow */ });
  }
  stateWs.stop();
});
// 탭/창 닫힘 — Vue unmount 안 타는 케이스. sendBeacon 으로 stop 신호.
window.addEventListener('beforeunload', () => { void stopDepthSession(); });
</script>

<template>
  <div class="depth-viewer">
    <OpenarmViewer
      source="follower"
      :show-depth-cloud="true"
      :show-depth-voxels="false"
      :depth-stream="stream"
      :depth-point-size="9.0"
      :depth-stride="2"
      :depth-max-m="2.0"
      :depth-frustum-near-m="HIGHFIVE_MIN_Z_M"
      :depth-frustum-far-m="HIGHFIVE_MAX_Z_M"
      depth-color-mode="silhouette"
      :depth-band-min-m="HIGHFIVE_MIN_Z_M"
      :depth-band-max-m="HIGHFIVE_MAX_Z_M"
      :depth-world-bound-xz="2.0"
      :hand-bbox="handBbox"
      render-lite
    />
    <!-- 실물 OpenArm 동기화 토글 — 실물 bringup 떠 있을 때만 visible. -->
    <button
      v-if="realActive"
      type="button"
      class="real-sync-toggle"
      :class="{ active: liveHighfiveReal }"
      :disabled="highfiveSyncBusy"
      @click="onToggleHighfiveReal"
    >
      <span class="real-sync-dot" />
      {{ highfiveSyncBusy
          ? '전환 중…'
          : (liveHighfiveReal ? '실물 동기화 ON · ✋' : '실물 동기화 OFF') }}
    </button>
    <div v-if="lastSyncError" class="real-sync-err">{{ lastSyncError }}</div>
    <WarningModal
      v-model:open="realConfirmOpen"
      title="실물 OpenArm 이 손바닥을 따라갑니다"
      :message="'High-five 제스처가 실물 양팔로 전달됩니다.\n주변에 사람이나 장애물이 없는지 확인해주세요.\n\n계속하시겠습니까?'"
      okText="계속"
      cancelText="취소"
      @ok="onRealConfirmed"
    />
    <div class="hud">
      <span class="status" :data-status="stream.status.value" :title="depthHint">
        {{ depthStatusLabel }}
      </span>
      <span v-if="fps > 0" class="fps">{{ fps }} fps</span>
      <span v-if="handMeters !== null" class="hand">
        손 {{ handMeters.toFixed(2) }} m
      </span>
      <span v-else-if="nearestMeters !== null" class="nearest">
        최근접 {{ nearestMeters.toFixed(2) }} m
      </span>
      <span v-if="armStatus" class="arm">{{ armStatus }}</span>
      <span class="kid" :data-active="true">
        {{ handLoading
          ? '손 추적 시작 중…'
          : (handMeters !== null
              ? `손 ${handMeters.toFixed(2)}m · 하이파이브 ✋`
              : '얼굴 검증 우회 · 손 대기 중') }}
      </span>
    </div>
    <!-- 좌측 하단 — 얼굴 인식용 카메라 picker + 미리보기. -->
    <div class="cam-panel">
      <select class="cam-select" v-model="selectedDeviceId" @change="onCameraChange">
        <option v-for="c in cameras" :key="c.deviceId" :value="c.deviceId">
          {{ c.label }}
        </option>
      </select>
      <!-- D435 WS 모드: 같은 canvas 가 preview + face_detection 입력. 그 외: video. -->
      <canvas v-show="selectedDeviceId === D435_WS_ID" ref="d435DetectCanvasRef" class="preview" />
      <video v-show="selectedDeviceId !== D435_WS_ID" ref="previewVideoRef" class="preview" autoplay muted playsinline />
    </div>
  </div>
</template>

<style scoped>
.depth-viewer {
  position: absolute;
  inset: 0;
}
.hud {
  position: absolute;
  top: calc(env(safe-area-inset-top, 0px) + 12px);
  right: 16px;
  display: flex;
  gap: 8px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.85);
  pointer-events: none;
  z-index: 50;
}
.real-sync-toggle {
  position: absolute;
  top: calc(env(safe-area-inset-top, 0px) + 12px);
  left: 16px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  border: 1px solid rgba(255, 255, 255, 0.3);
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.55);
  color: rgba(255, 255, 255, 0.92);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.3px;
  cursor: pointer;
  z-index: 60;
  backdrop-filter: blur(4px);
}
.real-sync-toggle:hover:not(:disabled) {
  background: rgba(0, 0, 0, 0.75);
}
.real-sync-toggle:disabled { opacity: 0.6; cursor: not-allowed; }
.real-sync-toggle.active {
  background: rgba(220, 38, 38, 0.85);
  border-color: rgba(255, 255, 255, 0.55);
  color: #fff;
}
.real-sync-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.4);
}
.real-sync-toggle.active .real-sync-dot {
  background: #fff;
  box-shadow: 0 0 8px rgba(255, 255, 255, 0.9);
  animation: real-sync-pulse 1.2s infinite;
}
@keyframes real-sync-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.55; }
}
.real-sync-err {
  position: absolute;
  top: calc(env(safe-area-inset-top, 0px) + 48px);
  left: 16px;
  padding: 6px 10px;
  border-radius: 6px;
  background: rgba(220, 38, 38, 0.85);
  color: #fff;
  font-size: 11px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  z-index: 60;
}
.status,
.fps,
.nearest,
.hand {
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.55);
}
.status[data-status='streaming'] { background: rgba(34, 197, 94, 0.75); }
.status[data-status='connecting'] { background: rgba(234, 179, 8, 0.75); }
.status[data-status='closed'] { background: rgba(220, 38, 38, 0.75); }
.nearest {
  background: rgba(59, 130, 246, 0.75);
  font-weight: 600;
}
.hand {
  background: rgba(34, 197, 94, 0.85);
  font-weight: 700;
}
.arm {
  background: rgba(168, 85, 247, 0.85);
  font-weight: 600;
  max-width: 42vw;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.kid {
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.55);
  font-weight: 600;
}
.kid[data-active='true'] {
  background: rgba(34, 197, 94, 0.85);
  color: white;
}
.cam-panel {
  position: absolute;
  left: 16px;
  bottom: 16px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  z-index: 50;
}
.cam-select {
  width: 240px;
  padding: 4px 8px;
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.3);
  background: rgba(0, 0, 0, 0.65);
  color: white;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  cursor: pointer;
}
.preview {
  width: 240px;
  height: 136px;
  object-fit: cover;
  border-radius: 8px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  background: rgba(0, 0, 0, 0.5);
}
</style>
