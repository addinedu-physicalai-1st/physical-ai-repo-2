<script setup lang="ts">
import { computed } from 'vue';
import { useHideAndSeekState } from '../useHideAndSeekState';

const state = useHideAndSeekState();

const matched = computed(() => {
  const id = state.capture.value?.matchedParticipantId;
  if (!id) return null;
  return state.participants.value.find((p) => p.id === id) ?? null;
});
</script>

<template>
  <div class="capture">
    <div class="modal">
      <p class="prompt">얼굴 보여주세요</p>
      <div class="preview">
        <div
          class="big-avatar"
          :style="{ background: matched ? matched.color : '#aaa' }"
        >
          {{ matched ? matched.name.slice(0, 1) : '?' }}
        </div>
      </div>
      <p v-if="matched" class="hit">{{ matched.name }} 잡았다!</p>
      <p v-else class="miss">다른 사람이었네...</p>
    </div>
  </div>
</template>

<style scoped>
.capture {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.25);
  display: flex;
  align-items: center;
  justify-content: center;
}
.modal {
  background: white;
  border-radius: 22px;
  padding: 26px 32px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  box-shadow: 0 18px 50px rgba(0, 0, 0, 0.22);
  min-width: 320px;
}
.prompt {
  font-size: 22px;
  color: #555;
  margin: 0;
  font-weight: 700;
}
.big-avatar {
  width: 140px;
  height: 140px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 64px;
  font-weight: 800;
  color: white;
}
.hit {
  font-size: 26px;
  color: #d8567a;
  font-weight: 800;
  margin: 0;
}
.miss {
  font-size: 18px;
  color: #888;
  margin: 0;
}
</style>
