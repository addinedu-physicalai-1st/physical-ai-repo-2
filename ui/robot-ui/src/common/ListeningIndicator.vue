<script setup lang="ts">
import type { VoiceState } from '@/stores/voice';

const props = defineProps<{ state: VoiceState }>();

const labelMap: Record<VoiceState, string> = {
  idle: 'idle',
  wake_detected: '대답 중',
  listening: '듣는 중',
  dispatching: '해석 중',
  cooldown: '...',
};

const colorMap: Record<VoiceState, string> = {
  idle: '#9ca3af',
  wake_detected: '#f59e0b',
  listening: '#16a34a',
  dispatching: '#3b82f6',
  cooldown: '#9ca3af',
};
</script>

<template>
  <span class="indicator">
    <span class="dot" :style="{ backgroundColor: colorMap[props.state] }"></span>
    <span class="label">{{ labelMap[props.state] }}</span>
  </span>
</template>

<style scoped>
.indicator {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: #555;
  font-weight: 600;
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  animation: pulse 1.5s ease-in-out infinite;
}
@keyframes pulse {
  50% {
    opacity: 0.3;
    transform: scale(0.85);
  }
}
</style>
