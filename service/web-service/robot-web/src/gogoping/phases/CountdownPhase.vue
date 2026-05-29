<script setup lang="ts">
/**
 * 30초 카운트다운 + "꼭꼭 숨어라 머리카락 보일라" 챈트 반복.
 * chant tick 은 부모 (HideAndSeekGame) 가 HIDE_CHANT_INTERVAL_MS 마다 +1 해 내려준다.
 */
import { computed, onMounted, onBeforeUnmount } from 'vue';

const props = defineProps<{
  remainingSec: number;
  totalSec: number;
  /** chant 발생 카운터 — 부모가 HIDE_CHANT_INTERVAL_MS 마다 +1 하면 애니메이션 트리거. */
  chantTick: number;
}>();

const progress = computed(() => {
  const elapsed = props.totalSec - props.remainingSec;
  return Math.max(0, Math.min(1, elapsed / props.totalSec));
});

// ─── 카운트다운 브금 (꼭꼭 숨어라) — countdown phase 동안만 재생, 이탈 시 정지 ───
const COUNTDOWN_BGM_SRC = '/sounds/countdown_bgm.mp3';
let countdownAudio: HTMLAudioElement | null = null;
onMounted(() => {
  countdownAudio = new Audio(COUNTDOWN_BGM_SRC);
  countdownAudio.loop = true;
  countdownAudio.volume = 0.7;
  void countdownAudio.play().catch(() => {});  // autoplay 차단 시 무음 (예외 무시)
});
onBeforeUnmount(() => {
  if (countdownAudio) {
    countdownAudio.pause();
    countdownAudio = null;
  }
});
</script>

<template>
  <section class="countdown">
    <div class="eyes-cover" aria-hidden="true">
      <div class="hand left">✋</div>
      <div class="hand right">✋</div>
    </div>

    <div class="count-num" :class="{ low: remainingSec <= 10 }">
      {{ remainingSec }}
    </div>
    <div class="count-label">초만 셀게!</div>

    <Transition name="chant">
      <div v-if="chantTick > 0" :key="chantTick" class="chant">
        꼭꼭 숨어라!<br />
        머리카락 보일라!
      </div>
    </Transition>

    <div class="bar">
      <div class="bar-fill" :style="{ width: `${progress * 100}%` }" />
    </div>
  </section>
</template>

<style scoped>
.countdown {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 18px;
  padding: 28px;
  position: relative;
}
.eyes-cover {
  display: flex;
  gap: 10px;
  font-size: 70px;
  margin-bottom: 6px;
}
.hand { animation: cover 2.4s ease-in-out infinite; }
.hand.right { animation-delay: 0.2s; }
@keyframes cover {
  0%, 100% { transform: translateY(0) rotate(0); }
  50% { transform: translateY(-6px) rotate(-6deg); }
}
.count-num {
  font-size: 168px;
  font-weight: 900;
  line-height: 1;
  color: #166534;
  letter-spacing: -6px;
  text-shadow: 0 6px 18px rgba(22, 163, 74, 0.25);
  font-variant-numeric: tabular-nums;
}
.count-num.low {
  color: #dc2626;
  animation: shake 0.6s ease-in-out infinite;
}
@keyframes shake {
  0%, 100% { transform: translateX(0); }
  25% { transform: translateX(-4px); }
  75% { transform: translateX(4px); }
}
.count-label {
  font-size: 20px;
  font-weight: 700;
  color: #4b5563;
  margin-top: -8px;
}

.chant {
  position: absolute;
  top: 18%;
  left: 50%;
  transform: translateX(-50%);
  padding: 14px 28px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.96);
  border: 3px solid #fbbf24;
  font-size: 22px;
  font-weight: 800;
  color: #92400e;
  text-align: center;
  line-height: 1.4;
  box-shadow: 0 10px 30px rgba(251, 191, 36, 0.35);
  pointer-events: none;
}
.chant-enter-active { transition: opacity 0.2s ease, transform 0.35s cubic-bezier(.2,1.6,.4,1); }
.chant-leave-active { transition: opacity 0.4s ease, transform 0.4s ease; }
.chant-enter-from { opacity: 0; transform: translateX(-50%) scale(0.7); }
.chant-leave-to   { opacity: 0; transform: translateX(-50%) translateY(-20px); }

.bar {
  width: min(80%, 460px);
  height: 12px;
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.08);
  overflow: hidden;
}
.bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #16a34a, #15803d);
  border-radius: 999px;
  transition: width 0.9s linear;
}
</style>
