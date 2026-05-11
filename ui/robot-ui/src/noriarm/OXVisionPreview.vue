<script setup lang="ts">
/**
 * OX 보드 인식 미리보기 — 브라우저 카메라 + AI Hub YOLO + 브라우저 mediapipe Hands.
 *
 * 두 추론 파이프라인이 같은 <video> 공유:
 *   1. AI Hub YOLO (서버) — 200ms 마다 WebSocket → bbox (O/X 영역)
 *   2. mediapipe Hands (브라우저) — 매 프레임 → 검지 tip 좌표
 *
 * armed=true 일 때 손가락이 한 영역에 LOCK_DURATION_MS 머물면 `select` emit.
 * 영역에서 한 번 떠나야 같은 영역에서 재발사 가능 (오발사 방지).
 *
 * 좌표:
 *   - YOLO bbox: frame_size 픽셀 (640×480 다운스케일)
 *   - mediapipe: normalized 0-1
 *   - overlay canvas: video 표시 픽셀
 *   - contains 검사는 frame_size 공간 (mp.x × frame_w, mp.y × frame_h)
 */
import { Hands, type Results as HandResults } from '@mediapipe/hands';
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';

const props = withDefaults(
  defineProps<{
    /** true 일 때만 락인 카운트다운이 진행됨. 질문 phase 동안 true 유지. */
    armed?: boolean;
  }>(),
  { armed: true },
);

const emit = defineEmits<{
  select: [region: 'O' | 'X'];
}>();

const LOCK_DURATION_MS = 1500;

interface Detection {
  score: number;
  bbox: [number, number, number, number];
  parts?: {
    O: [number, number, number, number];
    X: [number, number, number, number];
  };
  label?: string;
}

interface InferResponse {
  boxes: Detection[];
  inference_ms: number;
  frame_size: [number, number];
}

const JPEG_QUALITY = 0.6;
const SEND_W = 480; // 추론 보내기 전 다운스케일 (보드는 작으니 480 으로 충분)
const VISION_WS_PATH = '/api/noriarm/vision/ox-board/infer';
// mediapipe Hands 호출 최소 간격 — 매 RAF (60Hz) 돌리면 메인 스레드 잠식해서 WS round-trip 이 느려짐.
// 손 추적은 ~15 FPS 면 충분 (사람 손 움직임 속도).
const HANDS_MIN_INTERVAL_MS = 66;
// YOLO 추론 최소 간격 — 보드는 자주 안 움직이므로 5 FPS 면 충분. 서버/네트워크 부하 감소.
const INFER_MIN_INTERVAL_MS = 200;

const cameras = ref<MediaDeviceInfo[]>([]);
const selectedDeviceId = ref<string>('');
const error = ref<string | null>(null);
const fps = ref<number>(0);
const inferenceMs = ref<number>(0);
const currentRegion = ref<'O' | 'X' | null>(null);
const handDetected = ref<boolean>(false);

const videoRef = ref<HTMLVideoElement | null>(null);
const overlayRef = ref<HTMLCanvasElement | null>(null);

let stream: MediaStream | null = null;
let captureCanvas: HTMLCanvasElement | null = null;
let ws: WebSocket | null = null;
let stopRequested = false;
let frameCount = 0;
let lastFpsT = 0;
let lastInferSentAt = 0;
let pendingSendTimer: number | null = null;

// MediaPipe Hands 상태 — 한 번만 setup, 매 프레임 send
let hands: Hands | null = null;
let handsBusy = false;
let handsRafId: number | null = null;
// 검지 tip 좌표 (normalized 0-1, video 기준)
let fingertip: { x: number; y: number } | null = null;
// 가장 최근 YOLO 응답 — hands 결과와 매칭하기 위해 캐시
let lastInfer: InferResponse | null = null;

// 락인 상태 — armed=true 일 때만 진행
let lockedRegion: 'O' | 'X' | null = null;
let lockStartT = 0;
// 한 영역에서 emit 한 후엔 lockedFiredFor 로 마킹 — 손가락이 영역에서 한 번 떠나야 해제
let lockedFiredFor: 'O' | 'X' | null = null;
const lockProgress = ref<number>(0);

const hasCameras = computed(() => cameras.value.length > 0);

async function listCameras(): Promise<void> {
  error.value = null;
  try {
    // device label 을 받으려면 권한이 한 번은 필요 — 임시 스트림으로 권한 트리거
    if (cameras.value.every((c) => !c.label)) {
      try {
        const tmp = await navigator.mediaDevices.getUserMedia({ video: true });
        tmp.getTracks().forEach((t) => t.stop());
      } catch {
        /* 권한 거부해도 enumerate 는 동작 (label 빈 채로) */
      }
    }
    const devs = await navigator.mediaDevices.enumerateDevices();
    cameras.value = devs.filter((d) => d.kind === 'videoinput');
    if (!selectedDeviceId.value && cameras.value.length) {
      // USB 추천: label 에 'usb' 포함 우선, 없으면 첫번째
      const usb = cameras.value.find((c) => /usb/i.test(c.label));
      selectedDeviceId.value = (usb ?? cameras.value[0]).deviceId;
      await startStream();
    }
  } catch (e) {
    error.value = `카메라 목록 실패: ${e instanceof Error ? e.message : String(e)}`;
  }
}

async function startStream(): Promise<void> {
  await stopStream();
  if (!selectedDeviceId.value) return;
  error.value = null;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: {
        deviceId: { exact: selectedDeviceId.value },
        width: { ideal: 1280 },
        height: { ideal: 720 },
      },
      audio: false,
    });
    if (videoRef.value) {
      videoRef.value.srcObject = stream;
      await videoRef.value.play();
    }
    startInferLoop();
    setupHands();
    startHandsLoop();
  } catch (e) {
    error.value = `카메라 시작 실패: ${e instanceof Error ? e.message : String(e)}`;
  }
}

function setupHands(): void {
  if (hands) return;
  hands = new Hands({
    locateFile: (file) =>
      `https://cdn.jsdelivr.net/npm/@mediapipe/hands@0.4/${file}`,
  });
  hands.setOptions({
    maxNumHands: 1,
    modelComplexity: 0,           // 0=lite (빠름), 1=full
    minDetectionConfidence: 0.5,
    minTrackingConfidence: 0.5,
  });
  hands.onResults(handleHandResults);
}

function handleHandResults(results: HandResults): void {
  if (!results.multiHandLandmarks || results.multiHandLandmarks.length === 0) {
    fingertip = null;
    handDetected.value = false;
    currentRegion.value = null;
  } else {
    const landmarks = results.multiHandLandmarks[0];
    const tip = landmarks[8]; // 검지 fingertip
    fingertip = { x: tip.x, y: tip.y };
    handDetected.value = true;
    currentRegion.value = regionForFingertip(tip.x, tip.y);
  }
  updateLock();
  redraw();
}

function updateLock(): void {
  const region = currentRegion.value;

  if (!props.armed || region === null) {
    // 손이 보드 밖 또는 disarm → 다음 진입 시 다시 발사 가능하도록 모두 리셋
    lockedRegion = null;
    lockedFiredFor = null;
    lockProgress.value = 0;
    return;
  }

  // 같은 region 에서 이미 emit 된 상태 — 진행 100% 로 표시만 하고 재발사 X
  if (lockedFiredFor === region) {
    lockProgress.value = 1;
    return;
  }

  if (lockedRegion !== region) {
    // 새 region 진입 — 카운트다운 시작
    lockedRegion = region;
    lockStartT = performance.now();
  }

  const elapsed = performance.now() - lockStartT;
  lockProgress.value = Math.min(1, elapsed / LOCK_DURATION_MS);

  if (elapsed >= LOCK_DURATION_MS) {
    lockedFiredFor = region;
    emit('select', region);
  }
}

// armed 가 true 로 켜질 때 (예: 새 질문 시작) lock 상태 리셋 — 같은 답을 다시
// 선택할 수 있어야 함 (예: 연속 두 문제 답이 모두 'O')
watch(
  () => props.armed,
  (isArmed) => {
    if (isArmed) {
      lockedRegion = null;
      lockedFiredFor = null;
      lockStartT = 0;
      lockProgress.value = 0;
    }
  },
);

function regionForFingertip(nx: number, ny: number): 'O' | 'X' | null {
  if (!lastInfer || lastInfer.boxes.length === 0) return null;
  const [fw, fh] = lastInfer.frame_size;
  const px = nx * fw;
  const py = ny * fh;
  const box = lastInfer.boxes[0];
  if (!box.parts) return null;
  if (insideBbox(px, py, box.parts.O)) return 'O';
  if (insideBbox(px, py, box.parts.X)) return 'X';
  return null;
}

/** 검지 tip 이 현재 보드 bbox 안에 있으면 박스를 freeze. */
function isBboxFrozen(): boolean {
  if (!fingertip || !lastInfer || lastInfer.boxes.length === 0) return false;
  const [fw, fh] = lastInfer.frame_size;
  const px = fingertip.x * fw;
  const py = fingertip.y * fh;
  return insideBbox(px, py, lastInfer.boxes[0].bbox);
}

function insideBbox(x: number, y: number, b: [number, number, number, number]): boolean {
  return x >= b[0] && x <= b[2] && y >= b[1] && y <= b[3];
}

function startHandsLoop(): void {
  if (handsRafId != null) return;
  let lastSentAt = 0;
  const tick = (): void => {
    if (stopRequested) {
      handsRafId = null;
      return;
    }
    const v = videoRef.value;
    const now = performance.now();
    // 인터벌 + busy 가드 — mediapipe 가 메인 스레드 점유해 WS round-trip 을 막지 않게.
    if (
      v && v.readyState >= 2 && v.videoWidth && hands && !handsBusy
      && now - lastSentAt >= HANDS_MIN_INTERVAL_MS
    ) {
      handsBusy = true;
      lastSentAt = now;
      hands.send({ image: v }).finally(() => {
        handsBusy = false;
      });
    }
    handsRafId = window.requestAnimationFrame(tick);
  };
  handsRafId = window.requestAnimationFrame(tick);
}

function stopHandsLoop(): void {
  if (handsRafId != null) {
    window.cancelAnimationFrame(handsRafId);
    handsRafId = null;
  }
  // mediapipe WASM 리소스 명시적 해제 — GC 기다리지 않고 즉시 메모리 반환
  if (hands) {
    try {
      hands.close();
    } catch {
      /* close 두 번 호출 등 무시 */
    }
    hands = null;
  }
  handsBusy = false;
  fingertip = null;
  handDetected.value = false;
  currentRegion.value = null;
  lockProgress.value = 0;
  lockedRegion = null;
  lockedFiredFor = null;
}

async function stopStream(): Promise<void> {
  stopRequested = true;
  if (pendingSendTimer != null) {
    window.clearTimeout(pendingSendTimer);
    pendingSendTimer = null;
  }
  closeWs();
  stopHandsLoop();
  if (stream) {
    stream.getTracks().forEach((t) => t.stop());
    stream = null;
  }
  if (videoRef.value) videoRef.value.srcObject = null;
  fps.value = 0;
  inferenceMs.value = 0;
  lastInfer = null;
  clearOverlay();
}

function closeWs(): void {
  if (ws) {
    ws.onopen = ws.onmessage = ws.onerror = ws.onclose = null;
    if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
      ws.close();
    }
    ws = null;
  }
}

function startInferLoop(): void {
  stopRequested = false;
  closeWs();

  // Vite dev / 프로덕션 모두 동작: 같은 origin + ws/wss 자동 선택
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const url = `${proto}//${window.location.host}${VISION_WS_PATH}`;
  ws = new WebSocket(url);

  frameCount = 0;
  lastFpsT = performance.now();

  ws.onopen = () => {
    void sendNextFrame();
  };
  ws.onmessage = async (ev) => {
    try {
      const data = JSON.parse(ev.data as string) as InferResponse | { error: string };
      if ('error' in data) return;
      inferenceMs.value = Math.round(data.inference_ms);
      // Freeze: 손가락이 현재 bbox 안에 있으면 새 검출로 박스를 갱신하지 않음.
      // 아이가 손을 가져다 댄 순간 박스가 흔들리는 걸 방지 — 손이 영역 밖으로 나가면
      // 다시 라이브 업데이트 재개.
      if (!isBboxFrozen()) {
        lastInfer = data;
      }
      // hand 가 이미 잡혀있으면 (frozen 또는 새) bbox 로 region 다시 계산
      if (fingertip) {
        currentRegion.value = regionForFingertip(fingertip.x, fingertip.y);
      }
      redraw();
      frameCount += 1;
      const now = performance.now();
      if (now - lastFpsT > 1000) {
        fps.value = frameCount / ((now - lastFpsT) / 1000);
        lastFpsT = now;
        frameCount = 0;
      }
    } finally {
      void sendNextFrame();
    }
  };
  ws.onerror = (e) => {
    error.value = `vision WebSocket 에러: ${(e as Event).type}`;
  };
  ws.onclose = () => {
    if (!stopRequested) {
      // 비정상 종료면 1초 후 재연결 시도
      window.setTimeout(() => {
        if (!stopRequested && stream) startInferLoop();
      }, 1000);
    }
  };
}

async function sendNextFrame(): Promise<void> {
  if (stopRequested || !ws || ws.readyState !== WebSocket.OPEN) return;
  const v = videoRef.value;
  if (!v || v.readyState < 2 || !v.videoWidth) {
    window.setTimeout(() => void sendNextFrame(), 50);
    return;
  }
  // INFER_MIN_INTERVAL_MS 보다 빨리 보내려 하면 남은 시간만큼 지연
  const elapsed = performance.now() - lastInferSentAt;
  if (elapsed < INFER_MIN_INTERVAL_MS) {
    if (pendingSendTimer != null) return; // 이미 예약된 송신 있음 — 중복 방지
    pendingSendTimer = window.setTimeout(() => {
      pendingSendTimer = null;
      void sendNextFrame();
    }, INFER_MIN_INTERVAL_MS - elapsed);
    return;
  }
  const blob = await captureFrame(v);
  if (!blob) return;
  if (ws.readyState === WebSocket.OPEN) {
    ws.send(blob);
    lastInferSentAt = performance.now();
  }
}

async function captureFrame(v: HTMLVideoElement): Promise<Blob | null> {
  const w = SEND_W;
  const h = Math.round((v.videoHeight / v.videoWidth) * w);
  if (!captureCanvas) captureCanvas = document.createElement('canvas');
  captureCanvas.width = w;
  captureCanvas.height = h;
  const ctx = captureCanvas.getContext('2d');
  if (!ctx) return null;
  ctx.drawImage(v, 0, 0, w, h);
  return await new Promise<Blob | null>((resolve) =>
    captureCanvas!.toBlob((b) => resolve(b), 'image/jpeg', JPEG_QUALITY),
  );
}

function clearOverlay(): void {
  const c = overlayRef.value;
  if (!c) return;
  const ctx = c.getContext('2d');
  if (!ctx) return;
  ctx.clearRect(0, 0, c.width, c.height);
}

function redraw(): void {
  const c = overlayRef.value;
  const v = videoRef.value;
  if (!c || !v) return;
  const rect = v.getBoundingClientRect();
  if (c.width !== rect.width || c.height !== rect.height) {
    c.width = rect.width;
    c.height = rect.height;
  }
  const ctx = c.getContext('2d');
  if (!ctx) return;
  ctx.clearRect(0, 0, c.width, c.height);

  // 1) YOLO bbox
  if (lastInfer) {
    const [fw, fh] = lastInfer.frame_size;
    const sx = c.width / fw;
    const sy = c.height / fh;
    for (const b of lastInfer.boxes) {
      if (b.parts) {
        // 현재 손가락이 있는 영역은 두껍게 강조
        const oW = currentRegion.value === 'O' ? 5 : 2;
        const xW = currentRegion.value === 'X' ? 5 : 2;
        drawBox(ctx, b.parts.O, sx, sy, '#22dd55', `O ${b.score.toFixed(2)}`, oW);
        drawBox(ctx, b.parts.X, sx, sy, '#ff5544', `X ${b.score.toFixed(2)}`, xW);
      } else {
        drawBox(ctx, b.bbox, sx, sy, '#3a8fc2', `${b.label ?? ''} ${b.score.toFixed(2)}`);
      }
    }
  }

  // 2) 손가락 tip (mediapipe normalized → canvas px) + 락인 진행 호
  if (fingertip) {
    const fx = fingertip.x * c.width;
    const fy = fingertip.y * c.height;

    // 락인 진행 호 (검지 둘레)
    if (lockProgress.value > 0 && currentRegion.value) {
      const ringR = 22;
      const lockColor = currentRegion.value === 'O' ? '#22dd55' : '#ff5544';
      ctx.strokeStyle = 'rgba(255,255,255,0.35)';
      ctx.lineWidth = 4;
      ctx.beginPath();
      ctx.arc(fx, fy, ringR, 0, Math.PI * 2);
      ctx.stroke();
      ctx.strokeStyle = lockColor;
      ctx.lineWidth = 5;
      ctx.beginPath();
      ctx.arc(
        fx, fy, ringR,
        -Math.PI / 2,
        -Math.PI / 2 + lockProgress.value * Math.PI * 2,
      );
      ctx.stroke();
    }

    // 검지 dot
    ctx.beginPath();
    ctx.arc(fx, fy, 9, 0, Math.PI * 2);
    ctx.fillStyle = '#ffeb3b';
    ctx.fill();
    ctx.strokeStyle = 'black';
    ctx.lineWidth = 2;
    ctx.stroke();
  }
}

function drawBox(
  ctx: CanvasRenderingContext2D,
  b: [number, number, number, number],
  sx: number,
  sy: number,
  color: string,
  label: string,
  lineWidth = 2,
): void {
  const [x1, y1, x2, y2] = b;
  ctx.strokeStyle = color;
  ctx.lineWidth = lineWidth;
  ctx.strokeRect(x1 * sx, y1 * sy, (x2 - x1) * sx, (y2 - y1) * sy);
  ctx.font = 'bold 12px system-ui, sans-serif';
  const text = label.trim();
  const tw = ctx.measureText(text).width + 8;
  ctx.fillStyle = color;
  ctx.fillRect(x1 * sx, Math.max(0, y1 * sy - 16), tw, 16);
  ctx.fillStyle = 'white';
  ctx.fillText(text, x1 * sx + 4, Math.max(12, y1 * sy - 4));
}

async function onChange(): Promise<void> {
  await startStream();
}

async function rescan(): Promise<void> {
  await listCameras();
}

onMounted(listCameras);
onUnmounted(stopStream);
</script>

<template>
  <div class="vision-panel">
    <div class="vision-controls">
      <select
        v-model="selectedDeviceId"
        :disabled="!hasCameras"
        class="cam-select"
        @change="onChange"
      >
        <option v-if="!hasCameras" disabled value="">— 카메라 없음 —</option>
        <option v-for="c in cameras" :key="c.deviceId" :value="c.deviceId">
          {{ c.label || `카메라 ${c.deviceId.slice(0, 8)}…` }}
        </option>
      </select>
      <button class="rescan" type="button" title="다시 스캔" @click="rescan">↻</button>
    </div>
    <div class="vision-canvas">
      <video ref="videoRef" muted playsinline />
      <canvas ref="overlayRef" class="overlay" />
      <div v-if="fps > 0" class="hud">
        {{ fps.toFixed(1) }} fps · infer {{ inferenceMs }} ms
      </div>
      <div
        class="region-badge"
        :class="{
          'region-o': currentRegion === 'O',
          'region-x': currentRegion === 'X',
          'region-out': handDetected && !currentRegion,
          'region-none': !handDetected,
        }"
      >
        <template v-if="!handDetected">손 대기</template>
        <template v-else-if="currentRegion === 'O'">O 위</template>
        <template v-else-if="currentRegion === 'X'">X 위</template>
        <template v-else>영역 밖</template>
      </div>
    </div>
    <p v-if="error" class="vision-error">{{ error }}</p>
  </div>
</template>

<style scoped>
.vision-panel {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 320px;
}
.vision-controls {
  display: flex;
  gap: 6px;
  align-items: center;
}
.cam-select {
  flex: 1;
  padding: 6px 8px;
  border-radius: 6px;
  border: 1px solid #ccd;
  font-size: 12px;
  font-family: inherit;
  background: white;
  color: #1f3a4d;
}
.cam-select:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.rescan {
  background: white;
  border: 1px solid #ccd;
  border-radius: 6px;
  padding: 4px 10px;
  cursor: pointer;
  font-size: 14px;
  font-family: inherit;
  color: #5b7a8c;
}
.vision-canvas {
  position: relative;
  width: 100%;
  height: 200px;
  border-radius: 12px;
  overflow: hidden;
  background: #000;
  display: flex;
  align-items: center;
  justify-content: center;
}
.vision-canvas video {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}
.vision-canvas .overlay {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}
.vision-canvas .hud {
  position: absolute;
  top: 6px;
  left: 6px;
  background: rgba(0, 0, 0, 0.55);
  color: white;
  font-size: 11px;
  font-family: ui-monospace, monospace;
  padding: 3px 8px;
  border-radius: 4px;
  pointer-events: none;
}
.vision-canvas .region-badge {
  position: absolute;
  top: 6px;
  right: 6px;
  font-size: 12px;
  font-weight: 700;
  padding: 4px 10px;
  border-radius: 999px;
  pointer-events: none;
  letter-spacing: 0.3px;
}
.region-badge.region-none {
  background: rgba(0, 0, 0, 0.55);
  color: #aaa;
}
.region-badge.region-out {
  background: rgba(0, 0, 0, 0.55);
  color: #ffe082;
}
.region-badge.region-o {
  background: #22dd55;
  color: black;
}
.region-badge.region-x {
  background: #ff5544;
  color: white;
}
.vision-error {
  margin: 0;
  color: #c14545;
  font-size: 12px;
}
</style>
