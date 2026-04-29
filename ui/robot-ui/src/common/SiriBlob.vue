<script setup lang="ts">
import { computed } from 'vue';
import type { VoiceState } from '@/stores/voice';

const props = defineProps<{ level: number; state: VoiceState }>();

const baseIntensity = computed(() => {
  if (props.state === 'listening' || props.state === 'wake_detected') return 1;
  if (props.state === 'cooldown') return 0.7;
  return 0.55;
});

const wrapperStyle = computed(() => ({
  transform: `scale(${0.55 + baseIntensity.value * 0.15 + props.level * 0.45})`,
}));

const glowStyle = computed(() => ({
  opacity: 0.25 + baseIntensity.value * 0.2 + props.level * 0.5,
}));
</script>

<template>
  <div class="siri">
    <div class="wrapper" :style="wrapperStyle">
      <div class="blob blob-1"></div>
      <div class="blob blob-2"></div>
      <div class="blob blob-3"></div>
      <div class="glow" :style="glowStyle"></div>
    </div>
  </div>
</template>

<style scoped>
.siri {
  width: 180px;
  height: 180px;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}
.wrapper {
  position: relative;
  width: 100%;
  height: 100%;
  transition: transform 0.12s linear;
}
.blob {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  filter: blur(2px);
  opacity: 0.92;
}
.blob-1 {
  background: radial-gradient(
    circle at 40% 40%,
    var(--primary) 0%,
    color-mix(in srgb, var(--primary) 70%, white) 35%,
    color-mix(in srgb, var(--primary) 30%, transparent) 65%,
    transparent 82%
  );
  animation: m1 5s ease-in-out infinite;
}
.blob-2 {
  background: radial-gradient(circle at 60% 60%, #8b5cf6 0%, #a78bfa 35%, rgba(167, 139, 250, 0.4) 65%, transparent 82%);
  animation: m2 6.2s ease-in-out infinite;
}
.blob-3 {
  background: radial-gradient(
    circle at 50% 30%,
    color-mix(in srgb, var(--primary) 50%, #2563eb) 0%,
    color-mix(in srgb, var(--primary) 30%, #60a5fa) 35%,
    color-mix(in srgb, var(--primary) 15%, rgba(96, 165, 250, 0.4)) 65%,
    transparent 82%
  );
  animation: m3 4.6s ease-in-out infinite;
}
.glow {
  position: absolute;
  inset: -14px;
  border-radius: 50%;
  background: radial-gradient(circle, color-mix(in srgb, var(--primary) 50%, transparent) 0%, transparent 65%);
  filter: blur(16px);
  transition: opacity 0.18s linear;
  z-index: -1;
}
@keyframes m1 {
  0%, 100% { transform: translate(0, 0); border-radius: 50% 50% 50% 50%; }
  33%       { transform: translate(10px, -8px); border-radius: 60% 40% 60% 40%; }
  66%       { transform: translate(-6px, 8px); border-radius: 40% 60% 40% 60%; }
}
@keyframes m2 {
  0%, 100% { transform: translate(0, 0); border-radius: 60% 40% 50% 50%; }
  50%       { transform: translate(-12px, 4px); border-radius: 40% 60% 50% 50%; }
}
@keyframes m3 {
  0%, 100% { transform: translate(0, 0); border-radius: 50% 60% 40% 50%; }
  40%       { transform: translate(8px, 10px); border-radius: 60% 40% 60% 40%; }
}
</style>
