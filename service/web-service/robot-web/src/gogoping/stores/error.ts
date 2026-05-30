/**
 * GogoPing FSM ERROR(고장) 상태 보관 — robot-web 전용 오버레이 표시용.
 *
 * 흐름:
 *   fault → blackboard.error_reason → tree_inspector.snapshot.error_reason
 *     → /ws/robot-state → useGogopingStateWs.setError
 *     → GogopingErrorOverlay 가 active / reason 을 read
 *
 * ERROR 는 terminal — 복구는 로봇 재시작뿐. 재시작 시 fsm_state 가 CHARGING/IDLE 로
 * 바뀌어 active=false → 오버레이 자동 해제. (UI 측 별도 해제 로직 불필요)
 */
import { defineStore } from 'pinia';

export interface ErrorInfo {
  active: boolean;
  reason: string;
}

export const useErrorStore = defineStore('gogopingError', {
  state: () => ({
    active: false,
    reason: '',
  }),
  actions: {
    setError(info: ErrorInfo) {
      // 같은 값이면 reassign 안 함 (Vue reactive 효율)
      if (info.active === this.active && info.reason === this.reason) return;
      this.active = info.active;
      this.reason = info.reason;
    },
  },
});
