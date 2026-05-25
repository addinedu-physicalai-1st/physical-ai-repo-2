/**
 * BT 가 publish 하는 hideseek_phase 를 한 곳에서 보관.
 * HideAndSeekGame 의 phase state 가 이걸 watch 해서 화면 라우팅 (Task 11).
 *
 * 흐름:
 *   BT SetHideseekPhase("recruit"/"countdown"/...) → blackboard
 *     → tree_inspector.snapshot() → /gogoping/state 토픽
 *     → control-service /ws/robot-state → useGogopingStateWs
 *     → 본 store.setPhase
 *     → HideAndSeekGame.watch(btPhase) (Task 11)
 */
import { defineStore } from 'pinia';

export type HideseekPhase =
  | ''
  | 'move_to_play'
  | 'recruit'
  | 'countdown'
  | 'patrol'
  | 'return'
  | 'end';

export const useHideseekPhaseStore = defineStore('hideseekPhase', {
  state: () => ({ phase: '' as HideseekPhase }),
  actions: {
    setPhase(p: HideseekPhase) { this.phase = p; },
  },
});
