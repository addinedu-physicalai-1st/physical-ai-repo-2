<script setup lang="ts">
import { useHideAndSeekState } from '../useHideAndSeekState';

const state = useHideAndSeekState();
</script>

<template>
  <div class="phase">
    <div class="camera-mock">
      <p class="cam-label">📷 카메라 (mock)</p>
      <p class="cam-hint">순찰 중...</p>
    </div>

    <aside class="side">
      <h3 class="side-title">참가자</h3>
      <ul class="list">
        <li
          v-for="p in state.registered.value"
          :key="p.id"
          class="row"
          :class="{ caught: p.caught }"
        >
          <span class="avatar" :style="{ background: p.color }">
            {{ p.name.slice(0, 1) }}
          </span>
          <span class="name">{{ p.name }}</span>
          <span v-if="p.caught" class="badge">잡힘</span>
        </li>
      </ul>

      <div class="patrol-dots">
        <span
          v-for="i in state.totalPatrols"
          :key="i"
          class="dot"
          :class="{ done: i <= state.patrolIndex.value }"
        />
      </div>
    </aside>
  </div>
</template>

<style scoped>
.phase {
  display: grid;
  grid-template-columns: 1fr 280px;
  gap: 28px;
  width: 90%;
  max-width: 960px;
}
.camera-mock {
  background: #1a1a1a;
  border-radius: 18px;
  aspect-ratio: 4 / 3;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: white;
}
.cam-label {
  font-size: 18px;
  opacity: 0.85;
  margin: 0;
}
.cam-hint {
  font-size: 14px;
  opacity: 0.5;
  margin: 0;
}
.side {
  background: rgba(255, 255, 255, 0.9);
  border-radius: 18px;
  padding: 18px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.side-title {
  font-size: 16px;
  color: #555;
  margin: 0 0 4px;
}
.list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 8px;
  border-radius: 10px;
  transition: opacity 0.2s, filter 0.2s;
}
.row.caught {
  opacity: 0.45;
  filter: grayscale(0.7);
}
.avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  color: white;
}
.name {
  flex: 1;
  font-size: 15px;
  color: #444;
  font-weight: 600;
}
.badge {
  background: #888;
  color: white;
  font-size: 12px;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: 999px;
}
.patrol-dots {
  display: flex;
  gap: 6px;
  margin-top: 6px;
  justify-content: center;
}
.dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: rgba(216, 86, 122, 0.25);
}
.dot.done {
  background: #d8567a;
}
</style>
