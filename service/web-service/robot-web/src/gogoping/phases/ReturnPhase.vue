<script setup lang="ts">
/**
 * 복귀 단계 — "못찾겠다 꾀꼬리!" 외치며 운동장2 로 자율 주행.
 * 복귀 중에도 카메라 라이브 + 인식 파이프라인 활성 — PatrolPhase 와 동일 composable.
 * 발견 시 음성 호명 + caught API + 부모로 caught 이벤트. 로봇은 정지하지 않고
 * 복귀 nav 그대로 진행.
 */
import { computed, inject, onBeforeUnmount, onMounted, ref } from 'vue';
import CameraView from '../CameraView.vue';
import { VOICE_CONTROLLER_KEY } from '@/composables/voiceControllerKey';
import { useHideSeekRecognition } from '../composables/useHideSeekRecognition';
import { postCaught } from '../api/hideseekApi';
import type { Participant } from '../useHideAndSeekState';

const props = defineProps<{
  playArea: string;
  participants: Participant[];
}>();

const emit = defineEmits<{
  caught: [childId: number, childName: string];
}>();

const voiceController = inject(VOICE_CONTROLLER_KEY);
const cameraViewRef = ref<{ getImgEl: () => HTMLImageElement | null } | null>(null);
const captureCanvasRef = ref<HTMLCanvasElement | null>(null);
const cameraImgEl = computed(() => cameraViewRef.value?.getImgEl() ?? null);

const recognition = useHideSeekRecognition({
  imgEl: cameraImgEl,
  captureCanvas: captureCanvasRef,
  isRegistered: (id) => props.participants.find((p) => p.id === id)?.registered ?? false,
  isCaught: (id) => props.participants.find((p) => p.id === id)?.caught ?? false,
  onCaught: (childId, childName) => {
    voiceController?.speak(`${childName} 찾았다!`);
    void postCaught(childId);  // waypoint 없음 (복귀 중)
    emit('caught', childId, childName);
  },
});

onMounted(() => recognition.start());
onBeforeUnmount(() => recognition.stop());
</script>

<template>
  <section class="ret">
    <div class="shout">못 찾겠다, 꾀꼬리! 🐦</div>
    <div class="camera-wrap">
      <CameraView ref="cameraViewRef" />
      <canvas ref="captureCanvasRef" hidden />
    </div>
    <h2 class="title">{{ playArea }} 로 돌아가는 중</h2>
    <p class="sub">다 모이면 우승자를 발표할게!</p>
  </section>
</template>

<style scoped>
.ret {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 14px;
  padding: 22px;
  min-height: 0;
}
.camera-wrap {
  position: relative;
  width: min(80%, 480px);
  flex: 1 1 auto;
  min-height: 0;
  border-radius: 14px;
  overflow: hidden;
  background: #000;
  box-shadow: 0 8px 22px rgba(0, 0, 0, 0.25);
}
.shout {
  font-size: 28px;
  font-weight: 800;
  color: #92400e;
  background: rgba(254, 243, 199, 0.95);
  border: 3px solid #fbbf24;
  border-radius: 18px;
  padding: 12px 24px;
  box-shadow: 0 10px 24px rgba(251, 191, 36, 0.3);
  animation: shout-pulse 1.2s ease-in-out infinite;
  flex-shrink: 0;
}
@keyframes shout-pulse {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.04); }
}
.title {
  margin: 0;
  font-size: 24px;
  font-weight: 800;
  color: #166534;
  flex-shrink: 0;
}
.sub { margin: 0; color: #4b5563; font-size: 14px; flex-shrink: 0; }
</style>
