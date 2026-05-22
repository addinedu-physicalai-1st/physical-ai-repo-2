<script setup lang="ts">
/**
 * OX 퀴즈 우상단 표정 미리보기.
 *
 * 기본은 외장 USB 카메라 (예: Alcorlink USB 2.0 Camera) — `pickExternalCamera` 가
 * 노트북 내장 카메라를 label 패턴으로 제외하고 첫 외장을 고른다. 사용자는 드롭다운으로
 * 다른 카메라로 바꿀 수 있다(내장 포함).
 *
 * 외장 카메라가 1대뿐이면 OXVisionPreview (좌하단 보드 인식) 와 같은 물리 카메라를
 * 공유한다. Chrome 은 동일 deviceId 에 대한 두 번째 getUserMedia 를 내부적으로
 * 같은 track 으로 재사용하므로 두 video element 모두 정상 렌더된다.
 *
 * 자연 촬영: `useEmotionCapture` 가 video stream 위에서 5fps 추론, happy/sad 임계 초과 시
 * 프레임을 Control Server 로 업로드한다. 연속 촬영은 쿨다운(약 2.8초) 간격으로 허용한다.
 * 부모가 `armed=false` 또는 `:reset-on="key"` 로 세션 상태를 초기화한다.
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { useEmotionCapture } from '@/composables/useEmotionCapture';
import { pickExternalCamera } from '@/composables/selectExternalCamera';

const props = defineProps<{
  /** 검출 활성. OX 퀴즈 진행 phase 일 때만 true. */
  armed: boolean;
  /** 모드 이탈·세션 재시작 시 부모가 카운터 증가시켜 락 해제. */
  resetKey: number;
  /** 파일명·DB 메타 — 보고서 합성용. */
  robot: string;
  mode: string;
  /** 추론 주기(ms). 생략 시 기본값(200ms). 율동처럼 rAF 경합이 있는 경우 늘려서 전달. */
  inferIntervalMs?: number;
}>();

const emit = defineEmits<{
  /** 외장 USB 카메라 가용 여부 (이벤트 이름은 호환을 위해 유지). */
  'integrated-available': [available: boolean];
  captured: [info: { emotion: 'happy' | 'sad'; score: number; photoId: number; url: string }];
}>();

const videoRef = ref<HTMLVideoElement | null>(null);
const error = ref<string | null>(null);

const cameras = ref<MediaDeviceInfo[]>([]);
const selectedDeviceId = ref<string>('');
const hasCameras = computed(() => cameras.value.length > 0);

let stream: MediaStream | null = null;

const emotionCapture = useEmotionCapture({
  robot: props.robot,
  mode: props.mode,
  enabled: () => props.armed,
  onCaptured: (info) => emit('captured', info),
  inferIntervalMs: props.inferIntervalMs,
});

const EMOTION_SUSTAIN_MAX = 3;

async function listCameras(): Promise<void> {
  try {
    // 권한 트리거 — label 이 비어 있으면 enumerate 가 빈 라벨만 돌려준다.
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
    cameras.value = devs.filter((d) => d.kind === 'videoinput');
    if (cameras.value.length === 0) {
      selectedDeviceId.value = '';
      emit('integrated-available', false);
      return;
    }
    const stillValid = cameras.value.some((c) => c.deviceId === selectedDeviceId.value);
    if (!selectedDeviceId.value || !stillValid) {
      // 기본은 외장 USB — 없으면 첫 번째.
      const ext = await pickExternalCamera();
      selectedDeviceId.value = ext?.deviceId ?? cameras.value[0].deviceId;
    }
  } catch (e) {
    error.value = `카메라 목록 실패: ${e instanceof Error ? e.message : String(e)}`;
    emit('integrated-available', false);
  }
}

async function start(): Promise<void> {
  error.value = null;
  await listCameras();
  if (!selectedDeviceId.value) return;
  await startStream();
}

async function startStream(): Promise<void> {
  stopStream();
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: {
        deviceId: { exact: selectedDeviceId.value },
        width: { ideal: 640 },
        height: { ideal: 360 },
      },
      audio: false,
    });
    if (videoRef.value) {
      videoRef.value.srcObject = stream;
      await videoRef.value.play();
      emotionCapture.attach(videoRef.value);
    }
    emit('integrated-available', true);
  } catch (e) {
    error.value = `카메라 시작 실패: ${e instanceof Error ? e.message : String(e)}`;
    emit('integrated-available', false);
  }
}

function stopStream(): void {
  emotionCapture.detach();
  if (stream) {
    stream.getTracks().forEach((t) => t.stop());
    stream = null;
  }
  if (videoRef.value) videoRef.value.srcObject = null;
}

async function onChange(): Promise<void> {
  await startStream();
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

// 부모가 resetKey 증가시키면 세션 초기화 — 다음 표정 트리거부터 다시 촬영 가능.
watch(
  () => props.resetKey,
  () => emotionCapture.reset(),
);

onMounted(() => {
  void start();
  navigator.mediaDevices.addEventListener('devicechange', scheduleListCamerasOnDeviceChange);
});
onUnmounted(() => {
  navigator.mediaDevices.removeEventListener('devicechange', scheduleListCamerasOnDeviceChange);
  if (deviceChangeDebounce !== null) {
    window.clearTimeout(deviceChangeDebounce);
    deviceChangeDebounce = null;
  }
  stopStream();
});
</script>

<template>
  <div class="cam-panel" :class="{ 'is-captured': emotionCapture.captured.value }">
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
    <video ref="videoRef" muted playsinline />
    <!-- 셔터 플래시 — flashTick 값이 바뀔 때마다 :key 가 바뀌어 element 재마운트 → CSS 키프레임
         1회 재생. tick=0 (초기) 일 때는 렌더 안 함. -->
    <div
      v-if="emotionCapture.flashTick.value > 0"
      :key="emotionCapture.flashTick.value"
      class="shutter"
    />
    <div
      v-if="emotionCapture.lastEmotion.value !== null"
      class="emotion-tag"
      :class="`is-${emotionCapture.lastEmotion.value}`"
    >
      📸 {{ emotionCapture.lastEmotion.value === 'happy' ? '활짝!' : '시무룩' }}
    </div>
    <div
      v-if="armed && !emotionCapture.inCaptureCooldown.value && emotionCapture.ready.value"
      class="emotion-live-hud"
      :class="{ 'has-face': emotionCapture.faceDetected.value }"
    >
      <template v-if="!emotionCapture.faceDetected.value">얼굴 찾는 중…</template>
      <template v-else>
        웃음 {{ (emotionCapture.liveHappy.value * 100).toFixed(0) }}% · 슬픔
        {{ (emotionCapture.liveSad.value * 100).toFixed(0) }}%
        <span v-if="emotionCapture.sustainProgress.value > 0" class="emotion-sustain">
          · {{ emotionCapture.sustainProgress.value }}/{{ EMOTION_SUSTAIN_MAX }}
        </span>
      </template>
    </div>
    <p v-if="emotionCapture.uploadError.value" class="cam-upload-err">
      {{ emotionCapture.uploadError.value }}
    </p>
    <p v-if="error" class="cam-error">{{ error }}</p>
  </div>
</template>

<style scoped>
.cam-panel {
  width: 240px;
  border-radius: 12px;
  overflow: hidden;
  background: #000;
  position: relative;
  transition: box-shadow 0.4s ease;
  display: flex;
  flex-direction: column;
}
.cam-panel.is-captured {
  box-shadow: 0 0 0 3px #f0c042 inset;
}
.cam-controls {
  display: flex;
  gap: 4px;
  padding: 4px;
  background: rgba(0, 0, 0, 0.55);
}
.cam-select {
  flex: 1;
  min-width: 0;
  padding: 4px 6px;
  border-radius: 4px;
  border: 1px solid rgba(255, 255, 255, 0.2);
  font-size: 11px;
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
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 4px;
  padding: 2px 8px;
  cursor: pointer;
  font-size: 12px;
  font-family: inherit;
  color: #5b7a8c;
  flex-shrink: 0;
}
.cam-panel video {
  width: 100%;
  height: 140px;
  object-fit: cover;
  display: block;
}
.shutter {
  position: absolute;
  inset: 0;
  background: white;
  opacity: 0;
  pointer-events: none;
  animation: shutter-flash 0.6s ease-out;
  animation-iteration-count: 1;
}
@keyframes shutter-flash {
  0%   { opacity: 0; }
  10%  { opacity: 0.95; }
  100% { opacity: 0; }
}
.emotion-tag {
  position: absolute;
  bottom: 6px;
  left: 6px;
  font-size: 12px;
  font-weight: 700;
  padding: 4px 10px;
  border-radius: 999px;
  color: white;
  letter-spacing: 0.2px;
  pointer-events: none;
}
.emotion-tag.is-happy {
  background: rgba(45, 139, 87, 0.92);
}
.emotion-tag.is-sad {
  background: rgba(193, 69, 69, 0.92);
}
.emotion-live-hud {
  position: absolute;
  left: 6px;
  right: 6px;
  bottom: 28px;
  z-index: 2;
  font-size: 10px;
  font-weight: 600;
  padding: 4px 6px;
  border-radius: 6px;
  color: rgba(255, 255, 255, 0.95);
  background: rgba(30, 45, 58, 0.75);
  pointer-events: none;
  line-height: 1.2;
  text-align: center;
}
.emotion-live-hud.has-face {
  background: rgba(45, 110, 75, 0.82);
}
.emotion-sustain {
  font-weight: 800;
}
.cam-upload-err {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  margin: 0;
  padding: 4px 6px;
  font-size: 10px;
  color: #ffb4b4;
  background: rgba(80, 20, 20, 0.85);
  text-align: center;
  z-index: 3;
}
.cam-error {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0;
  color: #ffb4b4;
  font-size: 12px;
  text-align: center;
  padding: 8px;
  background: rgba(0, 0, 0, 0.6);
}
</style>
