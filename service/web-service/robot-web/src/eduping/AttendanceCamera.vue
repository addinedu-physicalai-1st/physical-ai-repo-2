<script setup lang="ts">
import { inject, ref, onBeforeUnmount, watch } from 'vue';
import { useModeStore } from '@/stores/mode';
import { VOICE_CONTROLLER_KEY } from '@/composables/voiceControllerKey';
import { useFaceDetector } from '@/composables/useFaceDetector';
import { useFaceTracker, type TrackedFace } from '@/composables/useFaceTracker';
import { useFaceIdentityCache, type IdentityResult } from '@/composables/useFaceIdentityCache';
import { mapMatchesToTracks, postRecognizeMulti } from '@/composables/identifyTracksFromFrame';

const props = defineProps<{
  /** 'IN' (등원) or 'OUT' (하원). null 이면 카메라 정지. */
  mode: 'IN' | 'OUT' | null;
}>();

const modeStore = useModeStore();
const voiceController = inject(VOICE_CONTROLLER_KEY);

function buildGreeting(name: string, type: 'IN' | 'OUT'): string {
  return type === 'IN'
    ? `${name} 어린이, 안녕! 오늘도 같이 신나게 놀아요!`
    : `${name} 어린이, 잘 가요! 내일 또 만나요!`;
}

// 카메라는 EduPing D435 — 노드(d435_rgb_uploader)가 /ws/eduping/rgb 로 JPEG 를 송출하고
// 여기선 그걸 canvas 에 그려 표시 + 얼굴검출/인식에 사용한다. 브라우저 getUserMedia·장치
// 선택 없음 (D435 는 perception 노드가 점유하므로 브라우저가 직접 열 수 없음).
const RGB_PATH = '/ws/eduping/rgb?role=consumer';
const rgbCanvas = ref<HTMLCanvasElement | null>(null);
let rgbWs: WebSocket | null = null;
let hasFrame = false;

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

let rafId: number | null = null;
let busy = false;

// 어린이별 cooldown — IN/OUT 모드 전환에도 유지되어, 등원 직후 모드만 OUT 으로 바꾼다고
// 같은 어린이가 즉시 하원 처리되는 사고를 막는다. 다른 어린이는 영향 없음 (줄 처리 가능).
const childCooldowns = new Map<number, number>();

const DEVICE_TOKEN = import.meta.env.VITE_ROBOT_TOKEN ?? 'dev-robot-token-change-me';
const COOLDOWN_MS = 8000;
const STABLE_FRAMES_REQUIRED = 5;  // 트래커 연속성이 노이즈 컷오프 역할

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

function wsUrl(path: string): string {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${location.host}${path}`;
}

async function drawRgb(blob: Blob): Promise<void> {
  const c = rgbCanvas.value;
  if (!c) return;
  let bm: ImageBitmap;
  try {
    bm = await createImageBitmap(blob);
  } catch {
    return;
  }
  if (c.width !== bm.width || c.height !== bm.height) {
    c.width = bm.width;
    c.height = bm.height;
  }
  c.getContext('2d')?.drawImage(bm, 0, 0);
  bm.close();
  hasFrame = true;
}

function connectRgb(): void {
  if (rgbWs) return;
  rgbWs = new WebSocket(wsUrl(RGB_PATH));
  rgbWs.binaryType = 'blob';
  rgbWs.onmessage = (ev: MessageEvent): void => {
    if (ev.data instanceof Blob) void drawRgb(ev.data);
  };
  rgbWs.onerror = () => { /* close 가 뒤따름 */ };
}

function disconnectRgb(): void {
  if (rgbWs) {
    rgbWs.onmessage = rgbWs.onerror = rgbWs.onclose = null;
    try { rgbWs.close(); } catch { /* noop */ }
    rgbWs = null;
  }
  hasFrame = false;
}

const tracker = useFaceTracker();
let latestTracks: TrackedFace[] = [];

const identityCache = useFaceIdentityCache({
  stableFramesRequired: STABLE_FRAMES_REQUIRED,
  identify: async (tracks): Promise<IdentityResult[]> => {
    return identifyTracks(tracks);
  },
});

const detector = useFaceDetector({
  onDetections: (faces) => {
    latestTracks = tracker.update(faces.map((f) => ({ bbox: f.bbox })));
    void identityCache.feed(latestTracks).then(() => {
      void maybeCheckInOrOut();
    });
  },
});

/** 전체 frame 을 /recognize-multi 로 보내고 응답 bbox 를 stable track 에 IoU 매칭. */
async function identifyTracks(tracks: TrackedFace[]): Promise<IdentityResult[]> {
  const c = rgbCanvas.value;
  if (!c || !hasFrame) return [];
  const blob = await captureFullFrame(c);
  if (!blob) return [];
  const matches = await postRecognizeMulti(blob, DEVICE_TOKEN);
  return mapMatchesToTracks(tracks, matches).map((p) => p.result);
}

async function captureFullFrame(canvas: HTMLCanvasElement): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob((b) => resolve(b), 'image/jpeg', 0.85));
}

function teardown(): void {
  if (rafId !== null) {
    cancelAnimationFrame(rafId);
    rafId = null;
  }
  detector.close();
  tracker.reset();
  identityCache.reset();
  disconnectRgb();
  status.value = '';
  lastResult.value = null;
  latestTracks = [];
  childCooldowns.clear();
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

async function maybeCheckInOrOut(): Promise<void> {
  if (props.mode === null) return;
  if (busy) return;
  for (const t of latestTracks) {
    const childId = identityCache.getChildId(t.trackId);
    if (childId == null) continue;
    const cd = childCooldowns.get(childId) ?? 0;
    if (Date.now() < cd) continue;
    await performCheck(childId);
    return; // 한 frame 에 한 명만 처리 (busy guard 와 함께)
  }
  if (!lastResult.value) status.value = '얼굴 인식 중...';
}

async function performCheck(childId: number): Promise<void> {
  if (props.mode === null) return;
  busy = true;
  try {
    status.value = `확인 중...`;
    const checked = await check(childId, props.mode);
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
      void modeStore.holdEmotionDuring('hello', async () => {
        voiceController?.speak(buildGreeting(checked.child_name, checked.type));
        await new Promise((r) => setTimeout(r, 1500));
      });
    }
  } finally {
    busy = false;
  }
}

// MediaPipe face_detection.send() 가 main thread 를 ~117ms 동안 점유 (WASM 동기).
// 매 rAF 마다 호출하면 main thread 가 거의 항상 잠겨 worklet → audio ring 의
// chunk 처리가 batch 로 지연되어 호출어 인식이 버벅임. 등원 인식은 어린이가
// 카메라 앞에 잠시 멈춰 있을 때 잡는 시나리오라 4fps 면 충분.
const FACE_SEND_INTERVAL_MS = 220;
async function loop(): Promise<void> {
  const c = rgbCanvas.value;
  if (c && hasFrame && c.width > 0) {
    const t0 = performance.now();
    await detector.send(c);
    const elapsed = performance.now() - t0;
    if (elapsed < FACE_SEND_INTERVAL_MS) {
      await new Promise((r) => setTimeout(r, FACE_SEND_INTERVAL_MS - elapsed));
    }
  } else {
    await new Promise((r) => setTimeout(r, FACE_SEND_INTERVAL_MS));
  }
  rafId = requestAnimationFrame(() => { void loop(); });
}

watch(
  () => props.mode,
  (newMode) => {
    if (newMode === null) {
      teardown();
      return;
    }
    connectRgb();
    detector.start();
    status.value = '카메라 연결 중...';
    lastResult.value = null;
    // childCooldowns 는 reset 하지 않음 — IN→OUT 전환 시 같은 어린이가
    // 즉시 다른 type 으로 또 trigger 되는 것을 방지
    if (rafId === null) {
      rafId = requestAnimationFrame(() => {
        void loop();
      });
    }
  },
  { immediate: true },
);

onBeforeUnmount(() => {
  teardown();
});
</script>

<template>
  <div v-if="mode !== null" class="attendance-pip">
    <div class="card">
      <div class="header">
        <span class="badge">{{ mode === 'IN' ? '등원' : '하원' }}</span>
      </div>
      <div class="video-wrap">
        <canvas ref="rgbCanvas" class="video" />
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
  left: 24px;
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
