/**
 * GogoPing 숨바꼭질 mock 백엔드 — 타이머만으로 단계 머신 전이를 만들어낸다.
 *
 * 실 도입 시 본 모듈을 다음으로 교체:
 *   - "위치 이동 도착" 이벤트 → BT_goto_sub 완료 콜백
 *   - "사람 발견" 이벤트 → /ws/face_detection 의 매칭 메시지
 *   - "순찰 노드 처리 완료" 이벤트 → BT_patrol_sub tick
 */
import { watch } from 'vue';
import {
  HIDE_CHANT_INTERVAL_MS,
  MOVE_DURATION_MS,
  PATROL_CAMERA_ROTATE_MS,
  PATROL_FIND_PROBABILITY,
  PATROL_TRAVEL_MS,
  RECRUIT_AUTO_FINISH_MS,
  RECRUIT_AUTO_REGISTER_INTERVAL_MS,
  RETURN_DURATION_MS,
} from './fixtures';
import type { HideAndSeekActions, HideAndSeekState } from './useHideAndSeekState';

export interface FakeBackendHandle {
  stop: () => void;
  /** 카운트다운 중 "꼭꼭 숨어라 머리카락 보일라" 챈트 콜백 등록. */
  onHideChant: (cb: () => void) => void;
  /** 카운트다운 시작 시 안내 ("30초 셀게!") 콜백 등록. */
  onCountdownStart: (cb: () => void) => void;
  /** 복귀 시작 시 "못찾겠다 꾀꼬리" 콜백 등록. */
  onCannotFind: (cb: () => void) => void;
  /** 모집 단계에서 자동 등록 중인지 (mock — 실 도입 시 얼굴 인식). */
  isAutoRegistering: () => boolean;
}

/**
 * mock 이벤트 생성을 phase 전이에 묶는다. App.vue 가 모드 변경으로 컴포넌트를
 * 마운트할 때 1회 실행, unmount 시 stop() 으로 타이머/와처 정리.
 */
export function startFakeBackend(
  state: HideAndSeekState,
  actions: HideAndSeekActions,
): FakeBackendHandle {
  const timers: number[] = [];
  let chantTimer: number | null = null;
  let countdownTimer: number | null = null;
  let recruitTimer: number | null = null;

  let hideChantCb: (() => void) | null = null;
  let countdownStartCb: (() => void) | null = null;
  let cannotFindCb: (() => void) | null = null;

  function schedule(fn: () => void, ms: number): void {
    timers.push(window.setTimeout(fn, ms));
  }

  function startRecruitAutoFlow(): void {
    // mock: 1.2초마다 다음 미등록자 자동 등록 (얼굴 인식 매칭 시뮬레이션)
    if (recruitTimer !== null) window.clearInterval(recruitTimer);
    recruitTimer = window.setInterval(() => {
      const next = state.participants.find((p) => !p.registered);
      if (!next) {
        if (recruitTimer !== null) window.clearInterval(recruitTimer);
        recruitTimer = null;
        return;
      }
      actions.registerParticipant(next.id);
    }, RECRUIT_AUTO_REGISTER_INTERVAL_MS);

    // 일정 시간 후 자동으로 모집 종료 → 위치 이동. 사용자가 먼저 "시작" 눌러도 됨.
    schedule(() => {
      if (state.phase === 'recruit' && state.registeredCount > 0) {
        actions.finishRecruit();
      }
    }, RECRUIT_AUTO_FINISH_MS);
  }

  function startMoveFlow(): void {
    schedule(() => {
      if (state.phase === 'move_to_play') actions.arriveAtPlayArea();
    }, MOVE_DURATION_MS);
  }

  function startCountdownFlow(): void {
    countdownStartCb?.();
    // 1Hz 카운트다운 — 0 도달 시 patrol 로
    if (countdownTimer !== null) window.clearInterval(countdownTimer);
    countdownTimer = window.setInterval(() => {
      actions.tickCountdown();
      if (state.countdownSec <= 0) {
        if (countdownTimer !== null) window.clearInterval(countdownTimer);
        countdownTimer = null;
        actions.startPatrol();
      }
    }, 1000);

    // "꼭꼭 숨어라 머리카락 보일라" 챈트 반복
    if (chantTimer !== null) window.clearInterval(chantTimer);
    hideChantCb?.();
    chantTimer = window.setInterval(() => {
      hideChantCb?.();
    }, HIDE_CHANT_INTERVAL_MS);
  }

  function stopChant(): void {
    if (chantTimer !== null) {
      window.clearInterval(chantTimer);
      chantTimer = null;
    }
  }

  function scheduleNextPatrolStep(): void {
    const idx = state.currentWaypointIdx;
    if (idx < 0 || idx >= state.waypoints.length) return;

    // 카메라 회전 마감 → 사람 발견 추첨 → 다음 노드로 이동
    schedule(() => {
      if (state.phase !== 'patrol') return;
      tryCatchAtCurrent();
      schedule(() => {
        if (state.phase !== 'patrol') return;
        actions.advanceWaypoint();
      }, PATROL_TRAVEL_MS);
    }, PATROL_CAMERA_ROTATE_MS);
  }

  function tryCatchAtCurrent(): void {
    // 등록 + 미발견 후보 중 한 명을 확률적으로 잡음 (mock).
    const candidates = state.participants.filter((p) => p.registered && !p.caught);
    if (candidates.length === 0) return;
    if (Math.random() > PATROL_FIND_PROBABILITY) return;
    const victim = candidates[Math.floor(Math.random() * candidates.length)];
    actions.catchAtCurrent(victim.id);
  }

  function startReturnFlow(): void {
    cannotFindCb?.();
    schedule(() => {
      if (state.phase === 'return') actions.finishReturn();
    }, RETURN_DURATION_MS);
  }

  // -------- phase 전이 감시 ----------
  const stopPhaseWatch = watch(
    () => state.phase,
    (next, prev) => {
      if (prev === 'countdown') stopChant();
      if (next === 'recruit') startRecruitAutoFlow();
      if (next === 'move_to_play') startMoveFlow();
      if (next === 'countdown') startCountdownFlow();
      if (next === 'patrol') scheduleNextPatrolStep();
      if (next === 'return') startReturnFlow();
    },
    { immediate: true },
  );

  // patrol 단계에서 현재 인덱스가 바뀔 때마다 다음 노드 step 예약 / 소진 시 복귀
  const stopWaypointWatch = watch(
    () => state.currentWaypointIdx,
    (idx) => {
      if (state.phase !== 'patrol') return;
      if (idx >= state.waypoints.length) {
        actions.finishPatrol();
        return;
      }
      if (idx >= 0) scheduleNextPatrolStep();
    },
  );

  function stop(): void {
    timers.forEach((t) => window.clearTimeout(t));
    timers.length = 0;
    if (chantTimer !== null) {
      window.clearInterval(chantTimer);
      chantTimer = null;
    }
    if (countdownTimer !== null) {
      window.clearInterval(countdownTimer);
      countdownTimer = null;
    }
    if (recruitTimer !== null) {
      window.clearInterval(recruitTimer);
      recruitTimer = null;
    }
    stopPhaseWatch();
    stopWaypointWatch();
  }

  return {
    stop,
    onHideChant: (cb) => { hideChantCb = cb; },
    onCountdownStart: (cb) => { countdownStartCb = cb; },
    onCannotFind: (cb) => { cannotFindCb = cb; },
    isAutoRegistering: () => recruitTimer !== null,
  };
}
