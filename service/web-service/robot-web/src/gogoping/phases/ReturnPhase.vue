<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue';
import { useHideAndSeekState } from '../useHideAndSeekState';

const state = useHideAndSeekState();

const shouting = ref(true);
let timer: number | null = null;

onMounted(() => {
  timer = window.setInterval(() => {
    shouting.value = !shouting.value;
  }, 800);
});
onBeforeUnmount(() => {
  if (timer !== null) window.clearInterval(timer);
});
</script>

<template>
  <div class="phase">
    <h2 class="title" :class="{ shout: shouting }">못찾겠다 꾀꼬리!</h2>
    <p class="sub">운동장2 로 돌아가는 중</p>
    <div class="progress-track">
      <div
        class="progress-fill"
        :style="{ width: `${state.navProgress.value * 100}%` }"
      />
    </div>
  </div>
</template>

<style scoped>
.phase {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 18px;
}
.title {
  font-size: 36px;
  color: #d8567a;
  margin: 0;
  font-weight: 800;
  transition: transform 0.3s, color 0.3s;
}
.title.shout {
  transform: scale(1.08);
  color: #b34060;
}
.sub {
  font-size: 18px;
  color: #777;
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
</style>
