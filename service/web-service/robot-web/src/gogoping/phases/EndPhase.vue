<script setup lang="ts">
import { computed } from 'vue';
import { useModeStore } from '@/stores/mode';
import { useHideAndSeekState } from '../useHideAndSeekState';

const state = useHideAndSeekState();

const modeStore = useModeStore();

const winnerLabel = computed(() => {
  const ws = state.winners.value;
  if (ws.length === 0) return null;
  return ws.map((w) => w.name).join(', ');
});

function close(): void {
  modeStore.setMode('대기');
}
</script>

<template>
  <div class="end">
    <h2 class="title">게임 종료</h2>
    <template v-if="winnerLabel">
      <p class="sub">오늘의 우승자</p>
      <ul class="winners">
        <li v-for="w in state.winners.value" :key="w.id" class="winner-card">
          <div class="avatar" :style="{ background: w.color }">
            {{ w.name.slice(0, 1) }}
          </div>
          <div class="name">{{ w.name }}</div>
          <div class="badge">🏆</div>
        </li>
      </ul>
    </template>
    <template v-else>
      <p class="sub">모두 잡혔어요!</p>
    </template>
    <button class="close-btn" @click="close">대기 모드로</button>
  </div>
</template>

<style scoped>
.end {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 18px;
}
.title {
  font-size: 36px;
  color: #555;
  margin: 0;
}
.sub {
  font-size: 20px;
  color: #888;
  margin: 0;
}
.winners {
  display: flex;
  gap: 18px;
  list-style: none;
  padding: 0;
  margin: 0;
}
.winner-card {
  width: 140px;
  background: white;
  border-radius: 20px;
  padding: 18px 12px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  box-shadow: 0 12px 32px rgba(196, 84, 111, 0.22);
  position: relative;
}
.avatar {
  width: 84px;
  height: 84px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 36px;
  font-weight: 800;
  color: white;
}
.name {
  font-size: 18px;
  font-weight: 700;
  color: #444;
}
.badge {
  position: absolute;
  top: 8px;
  right: 12px;
  font-size: 22px;
}
.close-btn {
  margin-top: 14px;
  background: #d8567a;
  color: white;
  border: none;
  border-radius: 999px;
  padding: 14px 32px;
  font-size: 16px;
  font-weight: 700;
  cursor: pointer;
}
</style>
