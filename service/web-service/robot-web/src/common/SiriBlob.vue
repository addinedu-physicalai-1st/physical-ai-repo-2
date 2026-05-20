<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { storeToRefs } from 'pinia';
import type { VoiceState } from '@/stores/voice';
import { useVoiceStore } from '@/stores/voice';

const props = defineProps<{ level: number; state: VoiceState }>();
const { lastWakeAt } = storeToRefs(useVoiceStore());

const baseIntensity = computed(() => {
  if (props.state === 'listening' || props.state === 'wake_detected') return 1;
  if (props.state === 'cooldown') return 0.7;
  return 0.55;
});

const active = computed(() => props.state !== 'idle');

// mic 은 wake 감지를 위해 idle 에도 항상 켜져 있어 level 이 흐른다.
// SiriBlob 은 호출어 직후 (wake_detected) ~ listening 동안에만 음성 크기에 반응.
const reactiveLevel = computed(() =>
  props.state === 'wake_detected' || props.state === 'listening' ? props.level : 0
);

const wrapperStyle = computed(() => ({
  transform: `scale(${0.55 + baseIntensity.value * 0.15 + reactiveLevel.value * 0.45})`,
}));

const glowStyle = computed(() => ({
  opacity: 0.25 + baseIntensity.value * 0.2 + reactiveLevel.value * 0.5,
}));

// 호출어가 감지될 때마다 한 번 튕긴다. wakeAt 변경 → 클래스 토글 (off → on)
// 사이에 nextFrame 을 두어 같은 클래스가 연속 적용돼도 keyframe 이 재시작되도록.
const bounce = ref(false);
let bounceTimer: ReturnType<typeof setTimeout> | null = null;
watch(lastWakeAt, (v) => {
  if (!v) return;
  bounce.value = false;
  requestAnimationFrame(() => {
    bounce.value = true;
    if (bounceTimer) clearTimeout(bounceTimer);
    bounceTimer = setTimeout(() => { bounce.value = false; }, 850);
  });
});
</script>

<template>
  <div class="siri" :class="{ 'wake-bounce': bounce, active }">
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
.siri.wake-bounce {
  animation: wakePop 0.85s cubic-bezier(0.34, 1.56, 0.64, 1);
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
}
.blob-2 {
  background: radial-gradient(circle at 60% 60%, #8b5cf6 0%, #a78bfa 35%, rgba(167, 139, 250, 0.4) 65%, transparent 82%);
}
.blob-3 {
  background: radial-gradient(
    circle at 50% 30%,
    color-mix(in srgb, var(--primary) 50%, #2563eb) 0%,
    color-mix(in srgb, var(--primary) 30%, #60a5fa) 35%,
    color-mix(in srgb, var(--primary) 15%, rgba(96, 165, 250, 0.4)) 65%,
    transparent 82%
  );
}
/* keyframe wobble 은 활성 상태 동안만 — idle 일 때는 완전 정지 (사용자가 호출 안 하면 움직이지 않음). */
.siri.active .blob-1 { animation: m1 5s ease-in-out infinite; }
.siri.active .blob-2 { animation: m2 6.2s ease-in-out infinite; }
.siri.active .blob-3 { animation: m3 4.6s ease-in-out infinite; }
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
@keyframes wakePop {
  0%   { transform: scale(0.7) translateY(6px); }
  35%  { transform: scale(1.35) translateY(-10px); }
  60%  { transform: scale(0.92) translateY(2px); }
  100% { transform: scale(1) translateY(0); }
}
</style>
