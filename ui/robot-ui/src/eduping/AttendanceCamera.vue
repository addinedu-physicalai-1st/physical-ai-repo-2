<script setup lang="ts">
import { ref, onBeforeUnmount, watch } from 'vue';
import { FaceMesh, type Results } from '@mediapipe/face_mesh';
import { useModeStore } from '@/stores/mode';
import { useTTS } from '@/composables/useTTS';

const props = defineProps<{
  /** 'IN' (등원) or 'OUT' (하원). null 이면 카메라 정지. */
  mode: 'IN' | 'OUT' | null;
}>();

const modeStore = useModeStore();
const tts = useTTS();

function buildGreeting(name: string, type: 'IN' | 'OUT'): string {
  return type === 'IN'
    ? `${name} 어린이, 안녕! 오늘도 같이 신나게 놀아요!`
    : `${name} 어린이, 잘 가요! 내일 또 만나요!`;
}

const videoRef = ref<HTMLVideoElement | null>(null);
const canvasRef = ref<HTMLCanvasElement | null>(null);

const status = ref<string>('');
const lastResult = ref<{
  name: string;
  type: 'IN' | 'OUT';
  already: boolean;
  /** 서버 응답의 arm_status — "fired" 면 표시 안 함, "skipped:..." 면 사유를 한국어로 노출. */
  armStatus: string | null;
} | null>(null);

/** 서버의 arm_status 코드(스키마 참조)를 교사용 한국어 메시지로 변환. */
function armSkipMessage(code: string | null): string | null {
  if (!code || code === 'fired') return null;
  if (code === 'skipped:no_bridge') return '팔 인사 생략 — 서버에 로봇 브릿지가 없어요';
  if (code === 'skipped:no_real_arm') return '팔 인사 생략 — 실물 팔이 연결돼 있지 않아요';
  if (code === 'skipped:routine_missing:morning') return '팔 인사 생략 — 등원 인사 녹화가 없어요';
  if (code === 'skipped:routine_missing:evening') return '팔 인사 생략 — 하원 인사 녹화가 없어요';
  if (code.startsWith('skipped:routine_missing:')) return '팔 인사 생략 — 인사 녹화가 없어요';
  if (code.startsWith('skipped:')) return `팔 인사 생략 — ${code.slice('skipped:'.length)}`;
  return null;
}

let stream: MediaStream | null = null;
let faceMesh: FaceMesh | null = null;
let rafId: number | null = null;
let busy = false;

// 어린이별 cooldown — IN/OUT 모드 전환에도 유지되어, 등원 직후 모드만 OUT 으로 바꾼다고
// 같은 어린이가 즉시 하원 처리되는 사고를 막는다. 다른 어린이는 영향 없음 (줄 처리 가능).
const childCooldowns = new Map<number, number>();

// 클라이언트 사이드 face presence 사전 필터 — 빈 프레임을 서버로 보내지 않기 위해
// mediapipe FaceMesh 로 로컬 detection 후 안정적으로 잡힐 때만 /recognize 호출.
let stableFrameCount = 0;
let lastRecognizeAt = 0;

const DEVICE_TOKEN = import.meta.env.VITE_ROBOT_TOKEN ?? 'dev-robot-token-change-me';
const COOLDOWN_MS = 8000;
// 얼굴이 연속 N 프레임 (rAF 60Hz 기준 ~133ms) 이상 잡혀야 안정적이라 판정
const STABLE_FRAMES_REQUIRED = 8;
// 매칭 실패해도 최소 이 간격은 두고 다음 recognize 시도 (CPU/네트워크 보호)
const MIN_RECOGNIZE_INTERVAL_MS = 1500;

interface RecognizeResult {
  matched: boolean;
  child_id: number | null;
  child_name: string | null;
  distance: number | null;
}

interface CheckResult {
  child_id: number;
  child_name: string;
  type: 'IN' | 'OUT';
  time: string;
  already: boolean;
  /** 신규 기록일 때 server 가 실물 팔로워 인사 모션을 trigger 한 결과.
   *  중복(already=true) 이거나 server 가 구버전이면 null. */
  arm_status: string | null;
}

async function setupCamera(): Promise<void> {
  if (stream) return;
  stream = await navigator.mediaDevices.getUserMedia({
    video: { width: 640, height: 480 },
    audio: false,
  });
  if (videoRef.value) {
    videoRef.value.srcObject = stream;
    await videoRef.value.play();
  }
}

function setupFaceMesh(): void {
  faceMesh = new FaceMesh({
    locateFile: (file) =>
      `https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh@0.4/${file}`,
  });
  faceMesh.setOptions({
    maxNumFaces: 1,
    refineLandmarks: false,
    minDetectionConfidence: 0.6,
    minTrackingConfidence: 0.6,
  });
  faceMesh.onResults(handleFaceResults);
}

function teardown(): void {
  if (rafId !== null) {
    cancelAnimationFrame(rafId);
    rafId = null;
  }
  if (faceMesh) {
    faceMesh.close();
    faceMesh = null;
  }
  if (stream) {
    stream.getTracks().forEach((t) => t.stop());
    stream = null;
  }
  if (videoRef.value) videoRef.value.srcObject = null;
  status.value = '';
  lastResult.value = null;
  stableFrameCount = 0;
  lastRecognizeAt = 0;
  childCooldowns.clear();
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

async function recognize(blob: Blob): Promise<RecognizeResult | null> {
  const form = new FormData();
  form.append('file', blob, 'frame.jpg');
  const res = await fetch('/api/attendance/recognize', {
    method: 'POST',
    headers: { 'X-Device-Token': DEVICE_TOKEN },
    body: form,
  });
  if (!res.ok) return null;
  return (await res.json()) as RecognizeResult;
}

async function check(child_id: number, type: 'IN' | 'OUT'): Promise<CheckResult | null> {
  const res = await fetch('/api/attendance/check', {
    method: 'POST',
    headers: {
      'X-Device-Token': DEVICE_TOKEN,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ child_id, type }),
  });
  if (!res.ok) return null;
  return (await res.json()) as CheckResult;
}

function handleFaceResults(results: Results): void {
  if (props.mode === null) return;

  const hasFace = !!results.multiFaceLandmarks?.[0];
  if (!hasFace) {
    stableFrameCount = 0;
    if (!lastResult.value) status.value = '얼굴 인식 중...';
    return;
  }

  stableFrameCount += 1;
  if (stableFrameCount < STABLE_FRAMES_REQUIRED) return;
  if (busy) return;
  if (Date.now() - lastRecognizeAt < MIN_RECOGNIZE_INTERVAL_MS) return;

  void runRecognize();
}

async function runRecognize(): Promise<void> {
  if (props.mode === null) return;
  busy = true;
  lastRecognizeAt = Date.now();
  try {
    const blob = await captureFrame();
    if (!blob) return;
    const result = await recognize(blob);
    if (!result) {
      status.value = '서버 오류';
      return;
    }
    if (!result.matched) {
      status.value = '얼굴 인식 중...';
      return;
    }
    // 인식된 어린이가 cooldown 중이면 check 호출하지 않음.
    // 다른 어린이는 같은 tick 에선 알 수 없지만 다음 안정 프레임에서 처리.
    const matchedChildId = result.child_id!;
    const cd = childCooldowns.get(matchedChildId) ?? 0;
    if (Date.now() < cd) {
      // 여전히 같은 어린이 — 마지막 결과 카드 유지
      return;
    }

    status.value = `${result.child_name} 어린이 확인 중...`;
    const checked = await check(matchedChildId, props.mode);
    if (!checked) {
      status.value = '출결 기록 실패';
      return;
    }
    lastResult.value = {
      name: checked.child_name,
      type: checked.type,
      already: checked.already,
      armStatus: checked.arm_status ?? null,
    };
    childCooldowns.set(checked.child_id, Date.now() + COOLDOWN_MS);
    status.value = '';
    if (!checked.already) {
      void modeStore.holdEmotionDuring('hello', () =>
        tts.speak(buildGreeting(checked.child_name, checked.type)),
      );
    }
  } finally {
    busy = false;
  }
}

async function loop(): Promise<void> {
  if (videoRef.value && faceMesh && videoRef.value.readyState >= 2) {
    await faceMesh.send({ image: videoRef.value });
  }
  rafId = requestAnimationFrame(() => {
    void loop();
  });
}

watch(
  () => props.mode,
  async (newMode) => {
    if (newMode === null) {
      teardown();
      return;
    }
    try {
      await setupCamera();
      if (!faceMesh) setupFaceMesh();
      status.value = '얼굴 인식 중...';
      lastResult.value = null;
      stableFrameCount = 0;
      lastRecognizeAt = 0;
      // childCooldowns 는 reset 하지 않음 — IN→OUT 전환 시 같은 어린이가
      // 즉시 다른 type 으로 또 trigger 되는 것을 방지
      if (rafId === null) {
        rafId = requestAnimationFrame(() => {
          void loop();
        });
      }
    } catch {
      status.value = '카메라 접근 실패';
    }
  },
  { immediate: true },
);

onBeforeUnmount(teardown);
</script>

<template>
  <div v-if="mode !== null" class="attendance-pip">
    <div class="card">
      <div class="header">
        <span class="badge">{{ mode === 'IN' ? '등원' : '하원' }}</span>
      </div>
      <div class="video-wrap">
        <video ref="videoRef" muted playsinline class="video" />
        <canvas ref="canvasRef" hidden />
      </div>
      <p v-if="status && !lastResult" class="status">{{ status }}</p>

      <div v-if="lastResult" class="result" :class="{ already: lastResult.already }">
        <strong>{{ lastResult.name }}</strong>
        <span v-if="lastResult.already">
          이미 {{ lastResult.type === 'IN' ? '등원' : '하원' }} 했어요
        </span>
        <span v-else>
          {{ lastResult.type === 'IN' ? '등원했어요!' : '하원했어요!' }}
        </span>
      </div>
      <p
        v-if="lastResult && armSkipMessage(lastResult.armStatus)"
        class="arm-note"
        role="status"
      >
        {{ armSkipMessage(lastResult.armStatus) }}
      </p>
    </div>
  </div>
</template>

<style scoped>
.attendance-pip {
  position: absolute;
  top: 24px;
  right: 24px;
  z-index: 5;
  pointer-events: none;
}
.card {
  background: rgba(255, 255, 255, 0.94);
  backdrop-filter: blur(6px);
  border-radius: 18px;
  padding: 14px 14px 12px;
  box-shadow: 0 10px 28px rgba(196, 84, 111, 0.18);
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 10px;
  width: 280px;
  pointer-events: auto;
}
.header {
  display: flex;
  align-items: center;
  justify-content: flex-start;
}
.badge {
  display: inline-block;
  padding: 4px 12px;
  background: #c4546f;
  color: white;
  font-size: 14px;
  font-weight: 700;
  border-radius: 999px;
  letter-spacing: 0.5px;
}
.video-wrap {
  position: relative;
  width: 100%;
  aspect-ratio: 4 / 3;
  border-radius: 12px;
  overflow: hidden;
  background: #1a1a1a;
}
.video {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transform: scaleX(-1);
}
.status {
  margin: 0;
  color: #888;
  font-size: 13px;
  text-align: center;
}
.result {
  background: #e8f5e9;
  color: #2e7d32;
  padding: 10px 14px;
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  font-size: 14px;
}
.result.already {
  background: #fff8e1;
  color: #ef6c00;
}
.result strong {
  font-size: 16px;
}
.arm-note {
  margin: 0;
  padding: 6px 10px;
  background: #fff4e5;
  color: #8a4b00;
  border: 1px solid #f0c98a;
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.4;
  text-align: center;
}
</style>
