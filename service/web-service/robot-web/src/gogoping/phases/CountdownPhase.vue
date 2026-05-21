<script setup lang="ts">
import { computed } from 'vue';
import { useHideAndSeekState } from '../useHideAndSeekState';

const state = useHideAndSeekState();

const shoutKey = computed(() => Math.floor(state.countdownSec.value / 5));
</script>

<template>
  <div class="phase">
    <p class="big" :key="shoutKey">꼭꼭 숨어라 머리카락 보인다</p>
    <div class="cover">
      <span class="hand">🙈</span>
    </div>
    <div class="counter">{{ state.countdownSec.value }}</div>
  </div>
</template>

<style scoped>
.phase {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 18px;
}
.big {
  font-size: 32px;
  color: #d8567a;
  margin: 0;
  font-weight: 800;
  animation: shout 0.6s ease-out;
}
@keyframes shout {
  0% { transform: scale(0.85); opacity: 0.6; }
  60% { transform: scale(1.06); opacity: 1; }
  100% { transform: scale(1); opacity: 1; }
}
.cover {
  font-size: 96px;
  line-height: 1;
}
.counter {
  font-size: 96px;
  font-weight: 800;
  color: #555;
  letter-spacing: -2px;
}
</style>
