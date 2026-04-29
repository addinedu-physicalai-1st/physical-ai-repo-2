<script setup lang="ts">
import { computed } from 'vue';
import { storeToRefs } from 'pinia';
import { useModeStore } from '@/stores/mode';
import type { RobotId } from '@/config/robots';

defineEmits<{ start: [] }>();

const { robot } = storeToRefs(useModeStore());

const PRIMARY: Record<RobotId, string> = {
  eduping:  '#e08a14',
  gogoping: '#d8567a',
  noriarm:  '#3a8fc2',
};
const primary = computed(() => PRIMARY[robot.value.id]);
</script>

<template>
  <div class="overlay" :style="{ '--primary': primary }" @click="$emit('start')">
    <div class="card">
      <div class="mic">
        <svg viewBox="0 0 24 24" width="56" height="56" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect x="9" y="3" width="6" height="12" rx="3" />
          <path d="M5 11a7 7 0 0 0 14 0" />
          <line x1="12" y1="18" x2="12" y2="22" />
          <line x1="8" y1="22" x2="16" y2="22" />
        </svg>
      </div>
      <div class="title">탭해서 시작하기</div>
      <div class="subtitle">화면을 한 번 눌러주세요</div>
    </div>
  </div>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  background: color-mix(in srgb, var(--primary) 12%, white);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  cursor: pointer;
  animation: fade-in 0.3s ease;
}
.card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
  padding: 36px 56px;
  background: white;
  border-radius: 28px;
  box-shadow: 0 20px 50px color-mix(in srgb, var(--primary) 22%, transparent);
  animation: pop 0.4s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.mic {
  width: 96px;
  height: 96px;
  border-radius: 50%;
  background: linear-gradient(135deg, color-mix(in srgb, var(--primary) 70%, white), var(--primary));
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 8px 20px color-mix(in srgb, var(--primary) 35%, transparent);
  animation: pulse 1.8s ease-in-out infinite;
}
.title {
  font-size: 22px;
  font-weight: 700;
  color: color-mix(in srgb, var(--primary) 80%, #000);
  letter-spacing: -0.3px;
}
.subtitle {
  font-size: 13px;
  color: #888;
}
@keyframes fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}
@keyframes pop {
  0% { transform: scale(0.85); opacity: 0; }
  100% { transform: scale(1); opacity: 1; }
}
@keyframes pulse {
  50% {
    transform: scale(1.05);
    box-shadow: 0 8px 28px color-mix(in srgb, var(--primary) 50%, transparent);
  }
}
</style>
