<script setup lang="ts">
import { useHideAndSeekState } from '../useHideAndSeekState';

const state = useHideAndSeekState();
</script>

<template>
  <div class="phase">
    <h2 class="title">운동장2 로 가는 중</h2>
    <div class="progress-track">
      <div
        class="progress-fill"
        :style="{ width: `${state.navProgress.value * 100}%` }"
      />
    </div>
    <p class="pct">{{ Math.round(state.navProgress.value * 100) }}%</p>
  </div>
</template>

<style scoped>
.phase {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 22px;
}
.title {
  font-size: 28px;
  color: #555;
  margin: 0;
}
.progress-track {
  width: 480px;
  height: 22px;
  background: rgba(255, 255, 255, 0.7);
  border-radius: 999px;
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #ffb4c2, #d8567a);
  transition: width 0.12s linear;
}
.pct {
  font-size: 18px;
  color: #888;
  margin: 0;
}
</style>
