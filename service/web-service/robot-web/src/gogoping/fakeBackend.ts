import { watch, onBeforeUnmount } from 'vue';
import type { HideAndSeekStateApi } from './useHideAndSeekState';

const NAV_DURATION_MS = 4000;
const NAV_TICK_MS = 100;
const COUNTDOWN_TICK_MS = 1000;
const RECRUIT_TICK_MS = 1000;
const PATROL_DETECT_MS = 3000;
const CAPTURE_RESOLVE_MS = 1500;
const UNKNOWN_FACE_PROB = 0.2;

/**
 * phase 변화에 따라 mock 이벤트를 만들어 state 를 자동 진행시킨다.
 * 컴포넌트 setup() 안에서 1회 호출. onBeforeUnmount 로 모든 timer cleanup.
 */
export function installFakeBackend(state: HideAndSeekStateApi): void {
  let timers: number[] = [];
  function setT(fn: () => void, ms: number): number {
    const id = window.setTimeout(fn, ms);
    timers.push(id);
    return id;
  }
  function setI(fn: () => void, ms: number): number {
    const id = window.setInterval(fn, ms);
    timers.push(id);
    return id;
  }
  function clearAll(): void {
    for (const id of timers) {
      window.clearTimeout(id);
      window.clearInterval(id);
    }
    timers = [];
  }

  watch(
    state.phase,
    (p) => {
      clearAll();
      switch (p) {
        case 'recruit':
          runRecruitSim();
          break;
        case 'move_to_play':
          runNavSim(state.arriveAtPlayArea);
          break;
        case 'countdown':
          runCountdownSim();
          break;
        case 'patrol':
          runPatrolSim();
          break;
        case 'capture':
          runCaptureSim();
          break;
        case 'return':
          runNavSim(state.arriveAtReturn);
          break;
        case 'end':
          break;
      }
    },
    { immediate: true },
  );

  onBeforeUnmount(clearAll);

  function runRecruitSim(): void {
    setI(() => {
      const pool = state.participants.value.filter((p) => !p.candidate);
      if (pool.length === 0) return;
      const pick = pool[Math.floor(Math.random() * pool.length)];
      state.setCandidate(pick.id, true);
    }, RECRUIT_TICK_MS);
  }

  function runNavSim(onArrive: () => void): void {
    const steps = NAV_DURATION_MS / NAV_TICK_MS;
    let i = 0;
    setI(() => {
      i += 1;
      state.setNavProgress(i / steps);
      if (i >= steps) {
        clearAll();
        onArrive();
      }
    }, NAV_TICK_MS);
  }

  function runCountdownSim(): void {
    setI(() => {
      state.setCountdownSec(state.countdownSec.value - 1);
    }, COUNTDOWN_TICK_MS);
  }

  function runPatrolSim(): void {
    setT(() => {
      const remaining = state.remaining.value;
      const r = Math.random();
      if (r < 0.7 && remaining.length > 0) {
        const pick = remaining[Math.floor(Math.random() * remaining.length)];
        state.detectPerson(pick.id);
      } else if (r < 0.7 + UNKNOWN_FACE_PROB) {
        const unregistered = state.participants.value.filter((p) => !p.registered);
        const ghostId =
          unregistered.length > 0
            ? unregistered[Math.floor(Math.random() * unregistered.length)].id
            : 'ghost';
        state.detectPerson(ghostId);
      } else {
        state.advancePatrol();
      }
    }, PATROL_DETECT_MS);
  }

  function runCaptureSim(): void {
    setT(() => {
      const cap = state.capture.value;
      if (!cap) return;
      if (cap.matchedParticipantId) {
        state.resolveCapture('matched', cap.matchedParticipantId);
      } else {
        state.resolveCapture('unknown');
      }
    }, CAPTURE_RESOLVE_MS);
  }
}
