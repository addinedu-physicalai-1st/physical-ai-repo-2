import { defineStore } from 'pinia';
import { ref } from 'vue';

/**
 * GogoPing BT FSM 의 raw state 문자열 store (예: 'IDLE', 'HIDEANDSEEK', 'RETURNING').
 * useGogopingStateWs 가 snapshot.fsm_state 를 그대로 set, App.vue 우상단 상태 배지가 read.
 * 한국어 mode 라벨(modeStore.currentMode)과 별개 — 디버그용 영문 표기.
 */
export const useGogopingFsmStore = defineStore('gogopingFsm', () => {
  const fsmState = ref('');

  function setFsmState(state: string): void {
    fsmState.value = state;
  }

  return { fsmState, setFsmState };
});
