<script setup lang="ts">
import { storeToRefs } from 'pinia';
import { useVoiceStore } from '@/stores/voice';
import { useModeStore } from '@/stores/mode';
import ListeningIndicator from './ListeningIndicator.vue';

const voice = useVoiceStore();
const mode = useModeStore();
const { state } = storeToRefs(voice);
const { currentMode } = storeToRefs(mode);
</script>

<template>
  <div class="bar">
    <span class="mode-tag">{{ currentMode }}</span>
    <ListeningIndicator :state="state" />
  </div>
</template>

<style scoped>
.bar {
  position: absolute;
  top: 40px;
  left: 50%;
  transform: translateX(-50%);
  background: white;
  border-radius: 999px;
  padding: 10px 20px;
  display: flex;
  align-items: center;
  gap: 14px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  max-width: 80vw;
  z-index: 10;
}
.mode-tag {
  background: #ff6b8a;
  color: white;
  border-radius: 8px;
  padding: 6px 14px;
  font-size: 15px;
  font-weight: 700;
  white-space: nowrap;
}
</style>
