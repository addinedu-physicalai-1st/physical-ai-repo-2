<script setup lang="ts">
/**
 * 노트북 내장 카메라 라이브 프리뷰 + 자연 촬영.
 *
 * USB 외장 카메라는 OXVisionPreview 가 점유 (OX 보드 인식) — 여기서는 라벨에 'usb'/'webcam'
 * 미포함인 첫 카메라를 picks. 내장 카메라가 없으면 패널 자체가 안 보이도록 부모에 emit.
 *
 * 자연 촬영: `useEmotionCapture` 가 video stream 위에서 5fps 추론, happy/sad 임계 초과 시
 * 1프레임을 Control Server 로 업로드한다. 한 게임 세션당 최대 1장 — 부모가 `armed=false`
 * 또는 `:reset-on="key"` 로 락 해제.
 */
import { onMounted, onUnmounted, ref, watch } from 'vue';
import { useEmotionCapture } from '@/composables/useEmotionCapture';

const props = defineProps<{
  /** 검출 활성. OX 퀴즈 진행 phase 일 때만 true. */
  armed: boolean;
  /** 모드 이탈·세션 재시작 시 부모가 카운터 증가시켜 락 해제. */
  resetKey: number;
  /** 파일명·DB 메타 — 보고서 합성용. */
  robot: string;
  mode: string;
}>();

const emit = defineEmits<{
  'integrated-available': [available: boolean];
  captured: [info: { emotion: 'happy' | 'sad'; score: number; photoId: number; url: string }];
}>();

const videoRef = ref<HTMLVideoElement | null>(null);
const error = ref<string | null>(null);

let stream: MediaStream | null = null;

const emotionCapture = useEmotionCapture({
  robot: props.robot,
  mode: props.mode,
  enabled: () => props.armed,
  onCaptured: (info) => emit('captured', info),
});

function isUsbCamera(label: string): boolean {
  return /usb|webcam/i.test(label);
}

async function start(): Promise<void> {
  error.value = null;
  try {
    if (!(await navigator.mediaDevices.enumerateDevices()).some((d) => d.label)) {
      try {
        const tmp = await navigator.mediaDevices.getUserMedia({ video: true });
        tmp.getTracks().forEach((t) => t.stop());
      } catch {
        /* 권한 거부해도 enumerate 는 동작 (label 빈 채로) */
      }
    }
    const devs = await navigator.mediaDevices.enumerateDevices();
    const videos = devs.filter((d) => d.kind === 'videoinput');
    const integrated = videos.find((d) => !isUsbCamera(d.label));
    if (!integrated) {
      emit('integrated-available', false);
      return;
    }
    stream = await navigator.mediaDevices.getUserMedia({
      video: {
        deviceId: { exact: integrated.deviceId },
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
    error.value = `내장 카메라 시작 실패: ${e instanceof Error ? e.message : String(e)}`;
    emit('integrated-available', false);
  }
}

function stop(): void {
  emotionCapture.detach();
  if (stream) {
    stream.getTracks().forEach((t) => t.stop());
    stream = null;
  }
  if (videoRef.value) videoRef.value.srcObject = null;
}

// 부모가 resetKey 증가시키면 세션 락 해제 — 다음 happy/sad 트리거에 다시 1장 가능.
watch(
  () => props.resetKey,
  () => emotionCapture.reset(),
);

onMounted(start);
onUnmounted(stop);
</script>

<template>
  <div class="cam-panel" :class="{ 'is-captured': emotionCapture.captured.value }">
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
    <p v-if="error" class="cam-error">{{ error }}</p>
  </div>
</template>

<style scoped>
.cam-panel {
  width: 240px;
  height: 140px;
  border-radius: 12px;
  overflow: hidden;
  background: #000;
  position: relative;
  transition: box-shadow 0.4s ease;
}
.cam-panel.is-captured {
  box-shadow: 0 0 0 3px #f0c042 inset;
}
.cam-panel video {
  width: 100%;
  height: 100%;
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
