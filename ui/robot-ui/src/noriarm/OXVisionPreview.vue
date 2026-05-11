<script setup lang="ts">
/**
 * OX 보드 인식 미리보기 — 브라우저가 카메라 잡고, AI Hub 가 YOLO 추론.
 *
 * 흐름:
 *   1. enumerateDevices() 로 카메라 목록, getUserMedia({ deviceId }) → <video>
 *   2. WebSocket 으로 /api/noriarm/vision/ox-board/infer 연결 (Control Server → AI Hub 프록시)
 *   3. 새 응답 받으면 다음 프레임을 즉시 캡처해 binary 로 send (back-pressure 자연스러움)
 *   4. 응답 JSON bbox 를 overlay <canvas> 에 그림
 *
 * back-pressure:
 *   "응답 받으면 다음 send" 패턴이라 추론 속도 ≈ 전송 속도. 서버 폭주 방지.
 *
 * 좌표 매핑:
 *   서버 응답 bbox 는 받은 frame 픽셀 좌표 (frame_size 기준).
 *   overlay canvas 는 video 표시 크기에 맞추고 sx/sy 로 스케일.
 */
import { computed, onMounted, onUnmounted, ref } from 'vue';

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

const JPEG_QUALITY = 0.7;
const SEND_W = 640; // 추론 보내기 전 다운스케일
const VISION_WS_PATH = '/api/noriarm/vision/ox-board/infer';

const cameras = ref<MediaDeviceInfo[]>([]);
const selectedDeviceId = ref<string>('');
const error = ref<string | null>(null);
const fps = ref<number>(0);
const inferenceMs = ref<number>(0);

const videoRef = ref<HTMLVideoElement | null>(null);
const overlayRef = ref<HTMLCanvasElement | null>(null);

let stream: MediaStream | null = null;
let captureCanvas: HTMLCanvasElement | null = null;
let ws: WebSocket | null = null;
let stopRequested = false;
let lastSentAt = 0;
let frameCount = 0;
let lastFpsT = 0;

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
  } catch (e) {
    error.value = `카메라 시작 실패: ${e instanceof Error ? e.message : String(e)}`;
  }
}

async function stopStream(): Promise<void> {
  stopRequested = true;
  closeWs();
  if (stream) {
    stream.getTracks().forEach((t) => t.stop());
    stream = null;
  }
  if (videoRef.value) videoRef.value.srcObject = null;
  fps.value = 0;
  inferenceMs.value = 0;
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
      drawOverlay(data);
      frameCount += 1;
      const now = performance.now();
      if (now - lastFpsT > 1000) {
        fps.value = frameCount / ((now - lastFpsT) / 1000);
        lastFpsT = now;
        frameCount = 0;
      }
    } finally {
      // back-pressure: 응답 받은 후에 다음 프레임 송신 → 추론 속도 ≈ 전송 속도
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
    // 비디오 아직 안 준비됨 — 잠시 후 다시
    window.setTimeout(() => void sendNextFrame(), 50);
    return;
  }
  const blob = await captureFrame(v);
  if (!blob) return;
  if (ws.readyState === WebSocket.OPEN) {
    ws.send(blob);
    lastSentAt = performance.now();
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

function drawOverlay(data: InferResponse): void {
  const c = overlayRef.value;
  const v = videoRef.value;
  if (!c || !v) return;
  const rect = v.getBoundingClientRect();
  // canvas 픽셀 = video 표시 픽셀 (devicePixelRatio 무시 — 화질보다 정렬 우선)
  if (c.width !== rect.width || c.height !== rect.height) {
    c.width = rect.width;
    c.height = rect.height;
  }
  const ctx = c.getContext('2d');
  if (!ctx) return;
  ctx.clearRect(0, 0, c.width, c.height);

  const [fw, fh] = data.frame_size;
  const sx = c.width / fw;
  const sy = c.height / fh;
  for (const b of data.boxes) {
    if (b.parts) {
      drawBox(ctx, b.parts.O, sx, sy, '#22dd55', `O ${b.score.toFixed(2)}`);
      drawBox(ctx, b.parts.X, sx, sy, '#ff5544', `X ${b.score.toFixed(2)}`);
    } else {
      drawBox(ctx, b.bbox, sx, sy, '#3a8fc2', `${b.label ?? ''} ${b.score.toFixed(2)}`);
    }
  }
}

function drawBox(
  ctx: CanvasRenderingContext2D,
  b: [number, number, number, number],
  sx: number,
  sy: number,
  color: string,
  label: string,
): void {
  const [x1, y1, x2, y2] = b;
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.strokeRect(x1 * sx, y1 * sy, (x2 - x1) * sx, (y2 - y1) * sy);
  // 라벨 배경
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
.vision-error {
  margin: 0;
  color: #c14545;
  font-size: 12px;
}
</style>
