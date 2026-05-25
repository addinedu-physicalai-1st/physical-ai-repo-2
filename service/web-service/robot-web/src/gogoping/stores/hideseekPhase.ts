/**
 * BT 가 publish 하는 hideseek phase + patrol info 를 한 곳에서 보관.
 *
 * 흐름:
 *   BT SetHideseekPhase("recruit"/"countdown"/...) + SearchWaypoints set
 *     → blackboard → tree_inspector.snapshot() → /gogoping/state 토픽
 *     → control-service /ws/robot-state → useGogopingStateWs
 *     → 본 store.setPhase / setPatrol
 *     → HideAndSeekGame / PatrolPhase 가 watch / read
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

export interface PatrolInfo {
  /** BT 가 패트롤 중인 vertex 이름 (search_waypoints 와 동일). 빈 list = 미진행. */
  vertices: string[];
  /** 현재 patrol_current_index — -1 (미진행) ~ vertices.length (완료). */
  currentIndex: number;
}

export const useHideseekPhaseStore = defineStore('hideseekPhase', {
  state: () => ({
    phase: '' as HideseekPhase,
    patrol: { vertices: [] as string[], currentIndex: -1 } as PatrolInfo,
  }),
  actions: {
    setPhase(p: HideseekPhase) { this.phase = p; },
    setPatrol(info: PatrolInfo) {
      // 같은 데이터면 reassign 안 함 (Vue reactive 효율)
      if (
        info.currentIndex === this.patrol.currentIndex
        && info.vertices.length === this.patrol.vertices.length
        && info.vertices.every((v, i) => v === this.patrol.vertices[i])
      ) return;
      this.patrol = { vertices: [...info.vertices], currentIndex: info.currentIndex };
    },
  },
});
