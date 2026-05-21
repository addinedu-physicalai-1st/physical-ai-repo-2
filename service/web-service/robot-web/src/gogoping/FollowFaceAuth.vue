<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { pickExternalCamera } from '@/composables/selectExternalCamera';

const props = defineProps<{
  /** true 면 카메라 켜고 매칭 시도. false 면 teardown. */
  active: boolean;
}>();

const emit = defineEmits<{
  (e: 'authenticated', name: string): void;
  (e: 'cancel'): void;
}>();

interface MatchResult {
  matched: boolean;
  teacher_id: string | null;
  name: string | null;
  distance: number | null;
  threshold: number;
}

const DEVICE_TOKEN = import.meta.env.VITE_ROBOT_TOKEN ?? 'dev-robot-token-change-me';
// 매 N ms 마다 한 장씩 서버로 보내 매칭 시도. 얼굴 없을 땐 server 의 InsightFace 가 빠르게
// matched=false 리턴하므로 빈 프레임 사전 필터는 불필요.
const POLL_INTERVAL_MS = 1500;

const videoRef = ref<HTMLVideoElement | null>(null);
const canvasRef = ref<HTMLCanvasElement | null>(null);

const status = ref<string>('교사 얼굴을 인식 중...');
const cameras = ref<MediaDeviceInfo[]>([]);
const selectedDeviceId = ref<string>('');
const hasCameras = computed(() => cameras.value.length > 0);

let stream: MediaStream | null = null;
let pollTimer: number | null = null;
let busy = false;
// 인증 성공 후에도 카메라는 살려둬 "고고핑이 보는 화면" 디버그 PiP 로 표시한다.
// template 분기를 위해 ref.
const succeeded = ref(false);

async function listCameras(): Promise<void> {
  let devs = await navigator.mediaDevices.enumerateDevices();
  if (devs.filter((d) => d.kind === 'videoinput').every((d) => !d.label)) {
    try {
      const tmp = await navigator.mediaDevices.getUserMedia({ video: true });
      tmp.getTracks().forEach((t) => t.stop());
    } catch {
      /* 권한 거부해도 enumerate 는 동작 */
    }
    devs = await navigator.mediaDevices.enumerateDevices();
  }
  cameras.value = devs.filter((d) => d.kind === 'videoinput');
  if (cameras.value.length === 0) {
    selectedDeviceId.value = '';
    return;
  }
  const stillValid = cameras.value.some((c) => c.deviceId === selectedDeviceId.value);
  if (!selectedDeviceId.value || !stillValid) {
    // 외장 USB 우선 — 노트북 내장은 거리·각도가 안 맞음.
    const ext = await pickExternalCamera();
    selectedDeviceId.value = ext?.deviceId ?? cameras.value[0].deviceId;
  }
}

async function setupCamera(): Promise<void> {
  if (stream) return;
  if (cameras.value.length === 0) await listCameras();
  if (!selectedDeviceId.value) throw new Error('사용 가능한 카메라가 없습니다');
  stream = await navigator.mediaDevices.getUserMedia({
    video: {
      deviceId: { exact: selectedDeviceId.value },
      // 전신 + 옷 디테일까지 보이도록 HD. InsightFace 얼굴 임베딩은 face crop 만 쓰니 부담 없음.
      width: { ideal: 1280 },
      height: { ideal: 720 },
    },
    audio: false,
  });
  if (videoRef.value) {
    videoRef.value.srcObject = stream;
    await videoRef.value.play();
  }
}

async function restartStream(): Promise<void> {
  if (!stream) return;
  stream.getTracks().forEach((t) => t.stop());
  stream = null;
  await setupCamera();
}

async function onCameraChange(): Promise<void> {
  if (!props.active) return;
  try {
    await restartStream();
  } catch {
    status.value = '카메라 접근 실패';
  }
}

function stopPolling(): void {
  // 카메라 스트림은 유지하고 폴링만 정지 — 인증 성공 후 PiP 디버그용.
  if (pollTimer !== null) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
  busy = false;
}

function teardown(): void {
  stopPolling();
  if (stream) {
    stream.getTracks().forEach((t) => t.stop());
    stream = null;
  }
  if (videoRef.value) videoRef.value.srcObject = null;
  succeeded.value = false;
}

async function captureFrame(): Promise<Blob | null> {
  const video = videoRef.value;
  const canvas = canvasRef.value;
  if (!video || !canvas) return null;
  if (video.readyState < 2) return null;
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  ctx.drawImage(video, 0, 0);
  return new Promise((resolve) => canvas.toBlob((b) => resolve(b), 'image/jpeg', 0.85));
}

async function matchFace(blob: Blob): Promise<MatchResult | null> {
  const form = new FormData();
  form.append('file', blob, 'frame.jpg');
  const res = await fetch('/api/teachers/match-face', {
    method: 'POST',
    headers: { 'X-Device-Token': DEVICE_TOKEN },
    body: form,
  });
  if (!res.ok) return null;
  return (await res.json()) as MatchResult;
}

async function runRecognize(): Promise<void> {
  if (!props.active || succeeded.value || busy) return;
  busy = true;
  try {
    const blob = await captureFrame();
    if (!blob) return;
    const result = await matchFace(blob);
    if (!result) {
      status.value = '서버 오류 — 잠시 후 다시 시도해요';
      return;
    }
    if (!result.matched || !result.name) {
      status.value = '교사를 찾을 수 없어요 — 다시 카메라를 봐주세요';
      return;
    }
    succeeded.value = true;
    status.value = `${result.name} 선생님 확인`;
    emit('authenticated', result.name);
    // 더 이상 매칭 시도하지 않고 PiP 로 전환. 카메라 스트림만 유지.
    stopPolling();
  } finally {
    busy = false;
  }
}

watch(
  () => props.active,
  async (now) => {
    if (!now) {
      teardown();
      return;
    }
    try {
      await setupCamera();
      status.value = '교사 얼굴을 인식 중...';
      succeeded.value = false;
      if (pollTimer === null) {
        pollTimer = window.setInterval(() => {
          void runRecognize();
        }, POLL_INTERVAL_MS);
      }
    } catch {
      status.value = '카메라 접근 실패';
    }
  },
  { immediate: true },
);

let deviceChangeDebounce: number | null = null;
function scheduleListCamerasOnDeviceChange(): void {
  if (deviceChangeDebounce !== null) window.clearTimeout(deviceChangeDebounce);
  deviceChangeDebounce = window.setTimeout(() => {
    deviceChangeDebounce = null;
    void listCameras();
  }, 400);
}

onMounted(() => {
  void listCameras();
  navigator.mediaDevices.addEventListener('devicechange', scheduleListCamerasOnDeviceChange);
});
onBeforeUnmount(() => {
  navigator.mediaDevices.removeEventListener('devicechange', scheduleListCamerasOnDeviceChange);
  if (deviceChangeDebounce !== null) {
    window.clearTimeout(deviceChangeDebounce);
    deviceChangeDebounce = null;
  }
  teardown();
});
</script>

<template>
  <div class="follow-auth-root" :class="{ minimized: succeeded }">
    <div v-if="!succeeded" class="backdrop" />
    <div class="auth-card">
      <video ref="videoRef" muted playsinline class="video" />
      <canvas ref="canvasRef" hidden />

      <template v-if="!succeeded">
        <div class="top-bar">
          <div class="title">추종 시작 — 교사 인증</div>
          <select
            v-model="selectedDeviceId"
            :disabled="!hasCameras"
            class="cam-select"
            @change="onCameraChange"
          >
            <option v-if="!hasCameras" disabled value="">— 카메라 없음 —</option>
            <option v-for="c in cameras" :key="c.deviceId" :value="c.deviceId">
              {{ c.label || `카메라 ${c.deviceId.slice(0, 8)}…` }}
            </option>
          </select>
          <button
            type="button"
            class="close-btn"
            aria-label="인증 취소"
            @click="emit('cancel')"
          >
            ✕
          </button>
        </div>
        <div class="bottom-bar">
          <p class="status">{{ status }}</p>
          <p class="hint">전신이 화면에 들어오도록 한두 걸음 떨어져 정면을 봐주세요.</p>
        </div>
      </template>

      <div v-else class="pip-badge">● 추종 중</div>
    </div>
  </div>
</template>

<style scoped>
.follow-auth-root {
  position: absolute;
  z-index: 50;
}
.follow-auth-root:not(.minimized) {
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}
.follow-auth-root.minimized {
  top: 16px;
  left: 16px;
}
.backdrop {
  position: absolute;
  inset: 0;
  background: rgba(20, 30, 25, 0.55);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
}
.auth-card {
  position: relative;
  background: #000;
  border-radius: 18px;
  overflow: hidden;
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.4);
}
.follow-auth-root:not(.minimized) .auth-card {
  width: min(560px, 80vw);
  aspect-ratio: 4 / 3;
}
.follow-auth-root.minimized .auth-card {
  width: 240px;
  aspect-ratio: 4 / 3;
  border: 2px solid rgba(255, 255, 255, 0.55);
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.45);
}
.video {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transform: scaleX(-1);
}
.top-bar {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  padding: 12px 14px;
  display: flex;
  align-items: center;
  gap: 10px;
  background: linear-gradient(to bottom, rgba(0, 0, 0, 0.6), rgba(0, 0, 0, 0));
  pointer-events: none;
}
.title {
  font-size: 18px;
  font-weight: 800;
  color: white;
  letter-spacing: -0.4px;
  text-shadow: 0 2px 8px rgba(0, 0, 0, 0.6);
  flex: 1;
}
.cam-select {
  pointer-events: auto;
  padding: 5px 8px;
  border-radius: 7px;
  border: 1px solid rgba(255, 255, 255, 0.4);
  font-size: 12px;
  font-family: inherit;
  background: rgba(0, 0, 0, 0.55);
  color: white;
  max-width: 180px;
}
.cam-select:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.close-btn {
  pointer-events: auto;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: 1px solid rgba(255, 255, 255, 0.4);
  background: rgba(0, 0, 0, 0.55);
  color: white;
  font-size: 15px;
  font-weight: 700;
  cursor: pointer;
  font-family: inherit;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.close-btn:hover { background: rgba(0, 0, 0, 0.75); }
.bottom-bar {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 14px 14px 18px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  background: linear-gradient(to top, rgba(0, 0, 0, 0.7), rgba(0, 0, 0, 0));
}
.status {
  margin: 0;
  text-align: center;
  font-size: 17px;
  font-weight: 800;
  color: white;
  text-shadow: 0 2px 8px rgba(0, 0, 0, 0.7);
}
.hint {
  margin: 0;
  text-align: center;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.78);
  text-shadow: 0 1px 4px rgba(0, 0, 0, 0.6);
}
.pip-badge {
  position: absolute;
  top: 6px;
  left: 8px;
  padding: 2px 8px;
  background: rgba(34, 197, 94, 0.88);
  color: white;
  font-size: 11px;
  font-weight: 800;
  border-radius: 999px;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.4);
  letter-spacing: 0.3px;
}

@media (max-width: 768px), (pointer: coarse) {
  .follow-auth-root:not(.minimized) .auth-card { width: 88vw; }
  .title { font-size: 15px; }
  .cam-select { font-size: 11px; max-width: 130px; padding: 4px 6px; }
  .close-btn { width: 28px; height: 28px; font-size: 13px; }
  .bottom-bar { padding: 10px 12px 14px; }
  .status { font-size: 14px; }
  .hint { font-size: 11px; }
  .follow-auth-root.minimized .auth-card { width: 180px; }
}
</style>
