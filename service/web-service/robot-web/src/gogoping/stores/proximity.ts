/**
 * GogoPing 근접 상황(사람/장애물)을 보관 — robot-web 안내 표시용.
 *
 * 흐름:
 *   safety_monitor → /gogoping/proximity_event
 *     → gogoping_modes 가 snapshot.proximity 에 실음 (tree_inspector.snapshot)
 *     → /gogoping/state → control-service /ws/robot-state → useGogopingStateWs
 *     → 본 store.setProximity → UI 컴포넌트가 message / blocked 를 read
 *
 * 표시 전용 — 로봇 제어(정지/reroute)는 graph_router 가 별도로 한다 (본 store 무관).
 */
import { defineStore } from 'pinia';

export type ProximityLevel = 'ok' | 'person_close' | 'wall_close';

export interface ProximityInfo {
  level: ProximityLevel;
  personDistM: number | null;
  wallDistM: number | null;
}

export const useProximityStore = defineStore('proximity', {
  state: () => ({
    level: 'ok' as ProximityLevel,
    personDistM: null as number | null,
    wallDistM: null as number | null,
  }),
  getters: {
    /** 근접 안내 문구 — 정상('ok')이면 빈 문자열. UI 가 그대로 표시. */
    message(state): string {
      switch (state.level) {
        case 'person_close': return '앞에 친구가 있어요. 비켜줄래요?';
        case 'wall_close':   return '앞에 장애물이 있어 잠시 멈췄어요.';
        default:             return '';
      }
    },
    /** 근접으로 멈춤 상태인지 — 배지/오버레이 표시 토글용. */
    blocked(state): boolean {
      return state.level === 'person_close' || state.level === 'wall_close';
    },
  },
  actions: {
    setProximity(info: ProximityInfo) {
      // 같은 값이면 reassign 안 함 (Vue reactive 효율)
      if (
        info.level === this.level
        && info.personDistM === this.personDistM
        && info.wallDistM === this.wallDistM
      ) return;
      this.level = info.level;
      this.personDistM = info.personDistM;
      this.wallDistM = info.wallDistM;
    },
  },
});
