<script setup lang="ts">
import { computed, provide } from 'vue';
import { useModeStore } from '@/stores/mode';
import {
  createHideAndSeekState,
  HIDE_AND_SEEK_KEY,
  type Phase,
} from './useHideAndSeekState';
import { installFakeBackend } from './fakeBackend';
import RecruitPhase from './phases/RecruitPhase.vue';
import MoveToPlayPhase from './phases/MoveToPlayPhase.vue';
import CountdownPhase from './phases/CountdownPhase.vue';
import PatrolPhase from './phases/PatrolPhase.vue';
import CapturePhase from './phases/CapturePhase.vue';
import ReturnPhase from './phases/ReturnPhase.vue';
import EndPhase from './phases/EndPhase.vue';

const modeStore = useModeStore();
const state = createHideAndSeekState();
provide(HIDE_AND_SEEK_KEY, state);
installFakeBackend(state);

const phaseLabel: Record<Phase, string> = {
  recruit: '참가자 모집',
  move_to_play: '운동장2 로 이동 중',
  countdown: '꼭꼭 숨어라!',
  patrol: '순찰 중',
  capture: '얼굴 확인',
  return: '못찾겠다 꾀꼬리',
  end: '게임 종료',
};

const label = computed(() => phaseLabel[state.phase.value]);

function quit(): void {
  state.finishGame();
  modeStore.setMode('대기');
}
</script>

<template>
  <div class="hide-and-seek">
    <header class="header">
      <span class="phase-badge">{{ label }}</span>
      <button class="quit-btn" @click="quit">종료</button>
    </header>
    <main class="phase-slot">
      <RecruitPhase v-if="state.phase.value === 'recruit'" />
      <MoveToPlayPhase v-else-if="state.phase.value === 'move_to_play'" />
      <CountdownPhase v-else-if="state.phase.value === 'countdown'" />
      <PatrolPhase
        v-else-if="state.phase.value === 'patrol' || state.phase.value === 'capture'"
      />
      <ReturnPhase v-else-if="state.phase.value === 'return'" />
      <EndPhase v-else-if="state.phase.value === 'end'" />
      <CapturePhase v-if="state.phase.value === 'capture'" />
    </main>
  </div>
</template>

<style scoped>
.hide-and-seek {
  position: absolute;
  inset: 0;
  z-index: 4;
  display: flex;
  flex-direction: column;
  pointer-events: auto;
}
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 28px;
}
.phase-badge {
  padding: 8px 18px;
  background: #d8567a;
  color: white;
  font-size: 18px;
  font-weight: 700;
  border-radius: 999px;
  letter-spacing: 0.5px;
}
.quit-btn {
  background: rgba(255, 255, 255, 0.85);
  border: none;
  border-radius: 999px;
  padding: 10px 22px;
  font-size: 15px;
  font-weight: 600;
  color: #555;
  cursor: pointer;
}
.quit-btn:hover {
  background: white;
}
.phase-slot {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
}
</style>
