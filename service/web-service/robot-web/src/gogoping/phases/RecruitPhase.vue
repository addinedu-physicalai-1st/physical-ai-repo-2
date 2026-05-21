<script setup lang="ts">
import { computed } from 'vue';
import { useHideAndSeekState } from '../useHideAndSeekState';

const state = useHideAndSeekState();

const candidates = computed(() =>
  state.participants.value.filter((p) => p.candidate),
);
const canStart = computed(() => candidates.value.length > 0);

function start(): void {
  state.confirmParticipants();
}
</script>

<template>
  <div class="recruit">
    <p class="caption">같이 놀 사람~ 시야 안으로 들어와요</p>
    <ul class="gallery">
      <li
        v-for="p in state.participants.value"
        :key="p.id"
        class="card"
        :class="{ candidate: p.candidate }"
      >
        <div class="avatar" :style="{ background: p.color }">
          {{ p.name.slice(0, 1) }}
        </div>
        <div class="name">{{ p.name }}</div>
        <div v-if="p.candidate" class="check">✓</div>
      </li>
    </ul>
    <button class="start-btn" :disabled="!canStart" @click="start">
      시작 ({{ candidates.length }}명)
    </button>
  </div>
</template>

<style scoped>
.recruit {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 22px;
}
.caption {
  font-size: 22px;
  color: #555;
  margin: 0;
}
.gallery {
  display: flex;
  gap: 18px;
  list-style: none;
  padding: 0;
  margin: 0;
}
.card {
  width: 120px;
  background: rgba(255, 255, 255, 0.9);
  border-radius: 18px;
  padding: 14px 10px 12px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  box-shadow: 0 6px 18px rgba(196, 84, 111, 0.12);
  position: relative;
  opacity: 0.55;
  transition: opacity 0.2s, transform 0.2s;
}
.card.candidate {
  opacity: 1;
  transform: translateY(-4px);
  box-shadow: 0 10px 24px rgba(196, 84, 111, 0.28);
}
.avatar {
  width: 72px;
  height: 72px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 32px;
  font-weight: 700;
  color: white;
}
.name {
  font-size: 16px;
  font-weight: 600;
  color: #444;
}
.check {
  position: absolute;
  top: 6px;
  right: 10px;
  background: #6dbf6d;
  color: white;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
}
.start-btn {
  margin-top: 8px;
  padding: 14px 38px;
  background: #d8567a;
  color: white;
  border: none;
  border-radius: 999px;
  font-size: 18px;
  font-weight: 700;
  cursor: pointer;
}
.start-btn:disabled {
  background: #ccc;
  cursor: default;
}
</style>
