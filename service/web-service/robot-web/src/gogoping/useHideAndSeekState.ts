import { ref, computed, inject, type ComputedRef, type Ref, type InjectionKey } from 'vue';
import { REGISTERED_CHILDREN } from './fixtures';

export type Phase =
  | 'recruit'
  | 'move_to_play'
  | 'countdown'
  | 'patrol'
  | 'capture'
  | 'return'
  | 'end';

export interface Participant {
  id: string;
  name: string;
  color: string;
  /** recruit 단계에서 카메라 시야 내로 검출된 후보 표시 (자동 토글) */
  candidate: boolean;
  /** 교사가 "시작" 으로 확정한 참가자 여부 */
  registered: boolean;
  /** capture 에서 잡힘 처리 */
  caught: boolean;
  caughtAt: number | null;
}

export interface CaptureState {
  status: 'waiting' | 'matched' | 'unknown';
  /** matched 일 때 어느 참가자가 잡혔는지 */
  matchedParticipantId: string | null;
}

export interface HideAndSeekStateApi {
  phase: Ref<Phase>;
  participants: Ref<Participant[]>;
  countdownSec: Ref<number>;
  navProgress: Ref<number>;
  patrolIndex: Ref<number>;
  totalPatrols: number;
  capture: Ref<CaptureState | null>;
  registered: ComputedRef<Participant[]>;
  remaining: ComputedRef<Participant[]>;
  caught: ComputedRef<Participant[]>;
  winners: ComputedRef<Participant[]>;
  setCandidate(id: string, value: boolean): void;
  confirmParticipants(): void;
  setNavProgress(v: number): void;
  arriveAtPlayArea(): void;
  setCountdownSec(v: number): void;
  enterPatrol(): void;
  detectPerson(participantId: string): void;
  resolveCapture(result: 'matched' | 'unknown', participantId?: string): void;
  advancePatrol(): void;
  enterReturn(): void;
  arriveAtReturn(): void;
  finishGame(): void;
}

export const HIDE_AND_SEEK_KEY: InjectionKey<HideAndSeekStateApi> = Symbol(
  'hide-and-seek-state',
);

export function useHideAndSeekState(): HideAndSeekStateApi {
  const state = inject(HIDE_AND_SEEK_KEY);
  if (!state) throw new Error('HideAndSeekState not provided');
  return state;
}

export const TOTAL_PATROLS = 5;
export const COUNTDOWN_START_SEC = 30;

export function createHideAndSeekState(): HideAndSeekStateApi {
  const phase = ref<Phase>('recruit');
  const participants = ref<Participant[]>(
    REGISTERED_CHILDREN.map((c) => ({
      ...c,
      candidate: false,
      registered: false,
      caught: false,
      caughtAt: null,
    })),
  );
  const countdownSec = ref<number>(COUNTDOWN_START_SEC);
  const navProgress = ref<number>(0);
  const patrolIndex = ref<number>(0);
  const capture = ref<CaptureState | null>(null);

  const registered = computed(() => participants.value.filter((p) => p.registered));
  const remaining = computed(() =>
    participants.value.filter((p) => p.registered && !p.caught),
  );
  const caught = computed(() => participants.value.filter((p) => p.caught));
  const winners = computed(() =>
    participants.value.filter((p) => p.registered && !p.caught),
  );

  function setCandidate(id: string, value: boolean): void {
    const p = participants.value.find((x) => x.id === id);
    if (p) p.candidate = value;
  }

  function confirmParticipants(): void {
    if (phase.value !== 'recruit') return;
    for (const p of participants.value) {
      if (p.candidate) p.registered = true;
    }
    if (registered.value.length === 0) return;
    navProgress.value = 0;
    phase.value = 'move_to_play';
  }

  function setNavProgress(v: number): void {
    navProgress.value = Math.max(0, Math.min(1, v));
  }

  function arriveAtPlayArea(): void {
    if (phase.value !== 'move_to_play') return;
    navProgress.value = 1;
    countdownSec.value = COUNTDOWN_START_SEC;
    phase.value = 'countdown';
  }

  function setCountdownSec(v: number): void {
    countdownSec.value = Math.max(0, v);
    if (countdownSec.value === 0 && phase.value === 'countdown') {
      enterPatrol();
    }
  }

  function enterPatrol(): void {
    patrolIndex.value = 0;
    phase.value = 'patrol';
  }

  function detectPerson(participantId: string): void {
    if (phase.value !== 'patrol') return;
    const target = participants.value.find((p) => p.id === participantId);
    capture.value = {
      status: 'waiting',
      matchedParticipantId:
        target && target.registered && !target.caught ? participantId : null,
    };
    phase.value = 'capture';
  }

  function resolveCapture(
    result: 'matched' | 'unknown',
    participantId?: string,
  ): void {
    if (phase.value !== 'capture') return;
    if (result === 'matched' && participantId) {
      const target = participants.value.find((p) => p.id === participantId);
      if (target && target.registered && !target.caught) {
        target.caught = true;
        target.caughtAt = Date.now();
      }
    }
    capture.value = null;
    if (remaining.value.length === 0) {
      enterReturn();
    } else {
      phase.value = 'patrol';
    }
  }

  function advancePatrol(): void {
    if (phase.value !== 'patrol') return;
    patrolIndex.value += 1;
    if (patrolIndex.value >= TOTAL_PATROLS) {
      enterReturn();
    }
  }

  function enterReturn(): void {
    navProgress.value = 0;
    phase.value = 'return';
  }

  function arriveAtReturn(): void {
    if (phase.value !== 'return') return;
    navProgress.value = 1;
    phase.value = 'end';
  }

  function finishGame(): void {
    phase.value = 'end';
  }

  return {
    phase,
    participants,
    countdownSec,
    navProgress,
    patrolIndex,
    totalPatrols: TOTAL_PATROLS,
    capture,
    registered,
    remaining,
    caught,
    winners,
    setCandidate,
    confirmParticipants,
    setNavProgress,
    arriveAtPlayArea,
    setCountdownSec,
    enterPatrol,
    detectPerson,
    resolveCapture,
    advancePatrol,
    enterReturn,
    arriveAtReturn,
    finishGame,
  };
}
