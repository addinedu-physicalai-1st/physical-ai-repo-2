<script setup lang="ts">
/**
 * 노트북 내장 카메라 라이브 프리뷰 — 추론 없이 그냥 영상만 보여준다.
 * 추후 OX 퀴즈 진행 중 "자연스러운 순간" 캡처 (사진 촬영) 용도로 확장 예정.
 *
 * USB 외장 카메라는 OXVisionPreview 가 담당하므로 여기서는 제외 (label 에 'usb'/'webcam'
 * 미포함인 첫 카메라를 picks). 내장 카메라가 없으면 패널 자체가 안 보이도록 부모에 emit.
 */
import { onMounted, onUnmounted, ref } from 'vue';

const emit = defineEmits<{
  'integrated-available': [available: boolean];
}>();

const videoRef = ref<HTMLVideoElement | null>(null);
const error = ref<string | null>(null);

let stream: MediaStream | null = null;

function isUsbCamera(label: string): boolean {
  return /usb|webcam/i.test(label);
}

async function start(): Promise<void> {
  error.value = null;
  try {
    // 라벨 받으려면 권한 한 번 필요 — 임시 스트림으로 트리거.
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
    // 내장 = USB/Webcam 라벨이 아닌 것. 라벨이 비어있는 경우(권한 거부) 도 '내장 후보' 로 포함.
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
    }
    emit('integrated-available', true);
  } catch (e) {
    error.value = `내장 카메라 시작 실패: ${e instanceof Error ? e.message : String(e)}`;
    emit('integrated-available', false);
  }
}

function stop(): void {
  if (stream) {
    stream.getTracks().forEach((t) => t.stop());
    stream = null;
  }
  if (videoRef.value) videoRef.value.srcObject = null;
}

onMounted(start);
onUnmounted(stop);
</script>

<template>
  <div class="cam-panel">
    <video ref="videoRef" muted playsinline />
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
}
.cam-panel video {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
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
