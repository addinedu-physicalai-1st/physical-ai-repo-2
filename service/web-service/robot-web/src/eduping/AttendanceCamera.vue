<script setup lang="ts">
import { computed, inject, ref, onBeforeUnmount, onMounted, watch } from 'vue';
import { useModeStore } from '@/stores/mode';
import { VOICE_CONTROLLER_KEY } from '@/composables/voiceControllerKey';
import { isDepthCamera } from '@/composables/selectExternalCamera';
import { postRecognizeMulti } from '@/composables/identifyTracksFromFrame';
import { useDepthStream, type DecodedDepthFrame } from '@/eduping/useDepthStream';

const props = defineProps<{
  /** 'IN' (등원) or 'OUT' (하원). null 이면 카메라 정지. */
  mode: 'IN' | 'OUT' | null;
}>();

const emit = defineEmits<{
  /** 등원(IN) 신규 인식 + "하이파이브" 멘트 직후 — 부모가 HighfiveDetector 를 띄움. */
  'highfive-request': [childName: string];
}>();

const modeStore = useModeStore();
const voiceController = inject(VOICE_CONTROLLER_KEY);

function buildGreeting(name: string, type: 'IN' | 'OUT'): string {
  return type === 'IN'
    ? `${name} 어린이, 안녕! 오늘도 같이 신나게 놀아요!`
    : `${name} 어린이, 잘 가요! 내일 또 만나요!`;
}

const videoRef = ref<HTMLVideoElement | null>(null);
// D435 WS 모드 미리보기 겸 얼굴인식 입력 canvas — colorBlob 을 여기 그려 detector/recognize 가 읽음.
const d435PreviewRef = ref<HTMLCanvasElement | null>(null);

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
  // 등원 morning 율동은 하이파이브로 대체 — 별도 "생략" 안내 불필요.
  if (code === 'skipped:replaced_by_highfive') return null;
  if (code === 'skipped:no_bridge') return '팔 인사 생략 — 서버에 로봇 브릿지가 없어요';
  if (code === 'skipped:no_real_arm') return '팔 인사 생략 — 실물 팔이 연결돼 있지 않아요';
  if (code === 'skipped:routine_missing:evening') return '팔 인사 생략 — 하원 인사 녹화가 없어요';
  if (code.startsWith('skipped:routine_missing:')) return '팔 인사 생략 — 인사 녹화가 없어요';
  if (code.startsWith('skipped:')) return `팔 인사 생략 — ${code.slice('skipped:'.length)}`;
  return null;
}

// DepthViewer 와 동일한 의사-디바이스 — getUserMedia 가 아니라 depth WS 의 D435
// colorBlob 을 얼굴인식 입력으로 쓴다 (정면 장착 전용 RGB, 노트북 웹캠보다 정확).
const D435_WS_ID = '__d435_ws__';
type CameraOption = { deviceId: string; label: string };
const cameras = ref<CameraOption[]>([]);
const selectedDeviceId = ref<string>(D435_WS_ID);
const hasCameras = computed(() => cameras.value.length > 0);
const isD435 = computed(() => selectedDeviceId.value === D435_WS_ID);

let stream: MediaStream | null = null;
let busy = false;

// D435 WS 모드 — colorBlob 공급 stream + 'frame 1장 이상 그려짐' 플래그.
const depthStream = useDepthStream('eduping');
let d435FrameReady = false;
// 서버 폴링 주기 — client 측 MediaPipe 검출을 제거(main thread block = lag 원인)하고,
// 미리보기 frame 을 주기적으로 /recognize-multi 로 보내 서버(InsightFace)가 검출+인식한다.
const RECOGNIZE_INTERVAL_MS = 700;
let recognizeTimer: ReturnType<typeof setInterval> | null = null;
let recognizing = false;

// 어린이별 cooldown — IN/OUT 모드 전환에도 유지되어, 등원 직후 모드만 OUT 으로 바꾼다고
// 같은 어린이가 즉시 하원 처리되는 사고를 막는다. 다른 어린이는 영향 없음 (줄 처리 가능).
const childCooldowns = new Map<number, number>();

const DEVICE_TOKEN = import.meta.env.VITE_ROBOT_TOKEN ?? 'dev-robot-token-change-me';
const COOLDOWN_MS = 8000;

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

async function listCameras(): Promise<void> {
  let devs = await navigator.mediaDevices.enumerateDevices();
  if (devs.filter((d) => d.kind === 'videoinput').every((d) => !d.label)) {
    try {
      const tmp = await navigator.mediaDevices.getUserMedia({ video: true });
      tmp.getTracks().forEach((t) => t.stop());
    } catch {
      /* 권한 거부해도 enumerate 는 동작 (label 빈 채로) */
    }
    devs = await navigator.mediaDevices.enumerateDevices();
  }
  // RealSense raw 디바이스는 ROS d435_camera 가 점유 → getUserMedia 로는 black 이라
  // 제외. 대신 depth WS 의 D435 RGB(colorBlob) 를 의사-디바이스로 항상 첫 옵션 + 기본값
  // (DepthViewer 와 동일 패턴). 정면 장착 D435 가 얼굴인식에 정확 — 노트북 웹캠은 fallback.
  const usbCams: CameraOption[] = devs
    .filter((d) => d.kind === 'videoinput' && !isDepthCamera(d))
    .map((d) => ({ deviceId: d.deviceId, label: d.label || `카메라 ${d.deviceId.slice(0, 8)}…` }));
  cameras.value = [
    { deviceId: D435_WS_ID, label: 'D435 RGB (얼굴 인식)' },
    ...usbCams,
  ];
  const stillValid = cameras.value.some((c) => c.deviceId === selectedDeviceId.value);
  if (!selectedDeviceId.value || !stillValid) {
    selectedDeviceId.value = D435_WS_ID;   // 기본값 D435 — 원하면 USB 로 override
  }
}

async function setupCamera(): Promise<void> {
  if (cameras.value.length === 0) await listCameras();
  if (!selectedDeviceId.value) {
    throw new Error('사용 가능한 카메라가 없습니다');
  }
  // D435 WS 모드: getUserMedia 안 씀 — depthStream.onFrame(handleDepthFrame) 이 colorBlob
  // 을 d435PreviewRef canvas 로 그린다. 남아있는 getUserMedia stream 은 정리.
  if (selectedDeviceId.value === D435_WS_ID) {
    if (stream) {
      stream.getTracks().forEach((t) => t.stop());
      stream = null;
    }
    if (videoRef.value) videoRef.value.srcObject = null;
    return;
  }
  // 외장 USB 모드 (fallback) — getUserMedia 경로.
  if (stream) return;
  stream = await navigator.mediaDevices.getUserMedia({
    video: {
      deviceId: { exact: selectedDeviceId.value },
      width: { ideal: 640 },
      height: { ideal: 480 },
    },
    audio: false,
  });
  if (videoRef.value) {
    videoRef.value.srcObject = stream;
    await videoRef.value.play();
  }
}

async function restartStream(): Promise<void> {
  if (stream) {
    stream.getTracks().forEach((t) => t.stop());
    stream = null;
  }
  await setupCamera();
}

async function onChange(): Promise<void> {
  // 모드 활성 중에 카메라를 바꾸면 새 스트림으로 교체. 비활성 상태면 다음 활성 때 새 선택값 사용.
  if (props.mode !== null) {
    try {
      await restartStream();
    } catch {
      status.value = '카메라 접근 실패';
    }
  }
}

async function rescan(): Promise<void> {
  await listCameras();
}

let deviceChangeDebounce: number | null = null;
function scheduleListCamerasOnDeviceChange(): void {
  if (deviceChangeDebounce !== null) {
    window.clearTimeout(deviceChangeDebounce);
  }
  deviceChangeDebounce = window.setTimeout(() => {
    deviceChangeDebounce = null;
    void listCameras();
  }, 400);
}

/** 미리보기 frame 을 /recognize-multi 로 보내 서버(InsightFace)가 검출+인식한다. 매칭된
 *  (cooldown 아닌) 어린이 한 명을 체크인. client 측 MediaPipe 검출/트래킹 없음 → main
 *  thread 를 안 막아 미리보기가 부드럽고, 인식은 서버(실제 recognizer)가 처리한다. */
async function pollRecognize(): Promise<void> {
  if (props.mode === null || recognizing || busy) return;
  recognizing = true;
  try {
    const blob = await captureFullFrame(isD435.value ? null : videoRef.value);
    if (!blob) return;
    const matches = await postRecognizeMulti(blob, DEVICE_TOKEN);
    const matched = matches.filter((m) => m.matched && m.child_id != null);
    // 진단 로그 — serverFaces=0(검출 실패/프레임 미준비), matched=0(임계 초과/미등록), dist 분포.
    console.info(
      `[Attendance] recognize serverFaces=${matches.length} matched=${matched.length} ` +
      `dist=${matches.map((m) => (m.distance == null ? '-' : m.distance.toFixed(2))).join(',')}`,
    );
    for (const m of matched) {
      const childId = m.child_id as number;
      const cd = childCooldowns.get(childId) ?? 0;
      if (Date.now() < cd) continue;
      await performCheck(childId);
      break;   // 한 번에 한 명 (busy guard 와 함께)
    }
    if (!lastResult.value && !busy) status.value = '얼굴 인식 중...';
  } finally {
    recognizing = false;
  }
}

async function captureFullFrame(video: HTMLVideoElement | null): Promise<Blob | null> {
  let src: HTMLCanvasElement | null = null;
  if (isD435.value) {
    if (!d435PreviewRef.value || !d435FrameReady) return null;
    src = d435PreviewRef.value;          // D435: colorBlob 이 그려진 미리보기 canvas
  } else {
    if (!video || video.readyState < 2) return null;
    const c = document.createElement('canvas');
    c.width = video.videoWidth;
    c.height = video.videoHeight;
    const ctx = c.getContext('2d');
    if (!ctx) return null;
    ctx.drawImage(video, 0, 0);
    src = c;
  }
  return new Promise((resolve) => src!.toBlob((b) => resolve(b), 'image/jpeg', 0.85));
}

// D435 colorBlob 을 매 WS frame 미리보기 canvas 에 그린다 (JPEG decode 는 가벼워 부드럽다).
// 얼굴 인식은 client 검출 없이 pollRecognize 가 이 canvas 를 주기적으로 서버로 보낸다.
function handleDepthFrame(frame: DecodedDepthFrame): void {
  if (!isD435.value) return;             // USB 모드면 <video> 가 native 미리보기
  if (props.mode === null) return;
  const cv = d435PreviewRef.value;
  if (!cv) return;
  void createImageBitmap(frame.colorBlob)
    .then((bm) => {
      if (cv.width !== bm.width) cv.width = bm.width;
      if (cv.height !== bm.height) cv.height = bm.height;
      cv.getContext('2d')?.drawImage(bm, 0, 0);
      d435FrameReady = true;
      bm.close();
    })
    .catch((e) => { console.warn('[AttendanceCamera] depth frame decode:', e); });
}

function teardown(): void {
  if (recognizeTimer !== null) {
    clearInterval(recognizeTimer);
    recognizeTimer = null;
  }
  recognizing = false;
  if (stream) {
    stream.getTracks().forEach((t) => t.stop());
    stream = null;
  }
  if (videoRef.value) videoRef.value.srcObject = null;
  d435FrameReady = false;
  void stopDepthSession();   // 모드 떠남 → producer 정리 (외부 tmux launch 는 안 건드림)
  status.value = '';
  lastResult.value = null;
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
      if (checked.type === 'IN') {
        // 등원: "{이름}어린이! 하이파이브" 멘트 → 하이파이브 서브플로우 시작.
        await modeStore.holdEmotionDuring('hello', async () => {
          voiceController?.speak(`${checked.child_name}어린이! 하이파이브`);
          await new Promise((r) => setTimeout(r, 1500));
        });
        emit('highfive-request', checked.child_name);
      } else {
        // 하원: 기존 작별 인사.
        void modeStore.holdEmotionDuring('hello', async () => {
          voiceController?.speak(buildGreeting(checked.child_name, checked.type));
          await new Promise((r) => setTimeout(r, 1500));
        });
      }
    }
  } finally {
    busy = false;
  }
}

async function startDepthSession(): Promise<void> {
  try {
    const res = await fetch('/api/eduping/depth/session/start', { method: 'POST' });
    if (!res.ok) console.warn('[AttendanceCamera] depth session/start non-OK:', res.status);
  } catch (e) {
    console.warn('[AttendanceCamera] depth session/start failed:', e);
  }
}
async function stopDepthSession(): Promise<void> {
  try {
    const blob = new Blob([''], { type: 'application/json' });
    const sent = navigator.sendBeacon?.('/api/eduping/depth/session/stop', blob);
    if (!sent) await fetch('/api/eduping/depth/session/stop', { method: 'POST' });
  } catch (e) {
    console.warn('[AttendanceCamera] depth session/stop failed:', e);
  }
}

watch(
  () => props.mode,
  async (newMode) => {
    if (newMode === null) {
      teardown();
      return;
    }
    try {
      // D435 producer 기동 (idempotent) — depthStream.onFrame 은 onMounted 에서 등록.
      void startDepthSession();
      await setupCamera();
      status.value = '얼굴 인식 중...';
      lastResult.value = null;
      // childCooldowns 는 reset 하지 않음 — IN→OUT 전환 시 같은 어린이가
      // 즉시 다른 type 으로 또 trigger 되는 것을 방지
      if (recognizeTimer === null) {
        recognizeTimer = setInterval(() => { void pollRecognize(); }, RECOGNIZE_INTERVAL_MS);
      }
    } catch {
      status.value = '카메라 접근 실패';
    }
  },
  { immediate: true },
);

onMounted(() => {
  // 첫 mount 에서 카메라 목록을 채워둠 — props.mode 가 null 이라 setupCamera 가 늦더라도
  // 드롭다운에 즉시 항목이 표시됨.
  void listCameras();
  // D435 colorBlob 구독 (handleDepthFrame 은 D435 모드 + 카드 표시 중일 때만 그림).
  depthStream.onFrame(handleDepthFrame);
  navigator.mediaDevices.addEventListener('devicechange', scheduleListCamerasOnDeviceChange);
});
onBeforeUnmount(() => {
  navigator.mediaDevices.removeEventListener('devicechange', scheduleListCamerasOnDeviceChange);
  if (deviceChangeDebounce !== null) {
    window.clearTimeout(deviceChangeDebounce);
    deviceChangeDebounce = null;
  }
  depthStream.stop();
  teardown();
});
</script>

<template>
  <div v-if="mode !== null" class="attendance-pip">
    <div class="card">
      <div class="header">
        <span class="badge">{{ mode === 'IN' ? '등원' : '하원' }}</span>
      </div>
      <div class="cam-controls">
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
      <div class="video-wrap">
        <!-- D435 WS 모드: colorBlob 을 그린 canvas (미리보기 + 얼굴인식 입력). 그 외: video. -->
        <canvas v-show="isD435" ref="d435PreviewRef" class="video" />
        <video v-show="!isD435" ref="videoRef" muted playsinline class="video" />
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
.cam-controls {
  display: flex;
  gap: 4px;
  align-items: center;
}
.cam-select {
  flex: 1;
  min-width: 0;
  padding: 4px 6px;
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
  padding: 2px 8px;
  cursor: pointer;
  font-size: 13px;
  font-family: inherit;
  color: #5b7a8c;
  flex-shrink: 0;
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
