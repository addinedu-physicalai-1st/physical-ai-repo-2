/**
 * GogoPing 숨바꼭질 UI 상태 머신 — SR-PLAY-007.
 *
 * 단계 흐름:
 *   recruit → move_to_play → countdown → patrol → return → end
 *
 * patrol 단계 안에서 "사람 발견" 이벤트가 인터럽트로 들어와 참가자를 caught 처리.
 * 발견 자체는 별도 phase 가 아니라 patrol 위에 깔리는 토스트/배너로 표시.
 *
 * 본 composable 은 백엔드 미연결 상태의 UI mock — fakeBackend 가 타이머로
 * "도착" / "발견" / "순찰 소진" 이벤트를 생성한다. 실 도입 시 fakeBackend 만
 * gogoping BT/Control Server WS 로 교체하면 된다.
 */
import { computed, reactive, ref } from 'vue';
import {
  COUNTDOWN_SEC,
  PLAY_AREA_LABEL,
  ROSTER_FALLBACK,
  WAYPOINTS,
  type RosterEntry,
  type Waypoint,
} from './fixtures';

export type Phase =
  | 'recruit'
  | 'move_to_play'
  | 'countdown'
  | 'patrol'
  | 'return'
  | 'end';

export interface Participant {
  id: number;
  name: string;
  /** 모집 단계에서 "참가" 확정. */
  registered: boolean;
  /** patrol 단계에서 발견됨. true = 우승 후보에서 제외. */
  caught: boolean;
  /** 발견된 웨이포인트 라벨 (있다면). */
  caughtAt: string | null;
}

export interface CaptureBanner {
  id: number;
  participantId: number;
  participantName: string;
  waypointLabel: string;
}

/**
 * reactive() 가 ref / computed 를 unwrap 한 뒤 노출되는 shape.
 * 컴포넌트 입장에선 `state.phase === 'recruit'` 처럼 평범한 값으로 다룬다.
 */
export interface HideAndSeekState {
  phase: Phase;
  participants: Participant[];
  waypoints: Waypoint[];
  /** 현재 카메라가 회전 중인 patrol 웨이포인트 인덱스 (-1 = 아직 도착 전). */
  currentWaypointIdx: number;
  /** patrol 단계에서 노드별 상태. */
  waypointStatus: (idx: number) => 'visited' | 'rotating' | 'pending';
  /** countdown 단계의 남은 초. */
  countdownSec: number;
  /** 토스트로 깜빡일 발견 이벤트 큐. */
  captureBanners: CaptureBanner[];
  /** 운동장2 라벨 (UI 표시용). */
  playArea: string;
  /** 모집 단계에서 등록된 참가자 수. */
  registeredCount: number;
  /** 우승자 (아직 잡히지 않은 등록 참가자). */
  winners: Participant[];
  /** patrol 노드 전체 통과 여부. */
  patrolExhausted: boolean;
}

export interface HideAndSeekActions {
  /** 모집: 한 명을 등록 (mock 얼굴 매칭). */
  registerParticipant: (id: number) => void;
  /** 모집: 한 명을 해제. */
  unregisterParticipant: (id: number) => void;
  /** 모집 종료 → 위치 이동 단계로. */
  finishRecruit: () => void;
  /** 운동장2 도착 → 카운트다운 시작. */
  arriveAtPlayArea: () => void;
  /** 카운트다운 종료 → 순찰 시작. */
  startPatrol: () => void;
  /** patrol: 다음 웨이포인트 이동 (현재 노드 회전 끝났음). */
  advanceWaypoint: () => void;
  /** patrol: 현재 노드에서 사람 발견 (mock). 없으면 무시. */
  catchAtCurrent: (participantId: number) => void;
  /** patrol 전 노드 소진 → 복귀 단계로. */
  finishPatrol: () => void;
  /** 운동장2 복귀 도착 → 발표 단계로. */
  finishReturn: () => void;
  /** 카운트다운 1초 감소 — fakeBackend 1Hz tick. */
  tickCountdown: () => void;
  /** roster 초기화 — recruit 진입 시 1회. */
  setRoster: (roster: RosterEntry[]) => void;
  /** 초기화 (모드 재진입 시). */
  reset: () => void;
}

function makeInitialParticipants(roster: RosterEntry[]): Participant[] {
  return roster.map((r) => ({
    id: r.id,
    name: r.name,
    registered: false,
    caught: false,
    caughtAt: null,
  }));
}

export function useHideAndSeekState(): { state: HideAndSeekState; actions: HideAndSeekActions } {
  const phase = ref<Phase>('recruit');
  const participants = ref<Participant[]>(makeInitialParticipants(ROSTER_FALLBACK));
  const waypoints = ref<Waypoint[]>([...WAYPOINTS]);
  const currentWaypointIdx = ref<number>(-1);
  const countdownSec = ref<number>(COUNTDOWN_SEC);
  const captureBanners = ref<CaptureBanner[]>([]);
  let bannerSeq = 0;

  /** 현재 인덱스 까지의 진행을 보고 노드별 상태 결정. */
  function waypointStatus(idx: number): 'visited' | 'rotating' | 'pending' {
    if (idx < currentWaypointIdx.value) return 'visited';
    if (idx === currentWaypointIdx.value) return 'rotating';
    return 'pending';
  }

  const registeredCount = computed(() =>
    participants.value.filter((p) => p.registered).length,
  );

  const winners = computed(() =>
    participants.value.filter((p) => p.registered && !p.caught),
  );

  const patrolExhausted = computed(
    () => currentWaypointIdx.value >= waypoints.value.length,
  );

  function setRoster(roster: RosterEntry[]): void {
    participants.value = makeInitialParticipants(roster);
  }

  function registerParticipant(id: number): void {
    const p = participants.value.find((x) => x.id === id);
    if (!p) return;
    p.registered = true;
  }

  function unregisterParticipant(id: number): void {
    const p = participants.value.find((x) => x.id === id);
    if (!p) return;
    p.registered = false;
  }

  function finishRecruit(): void {
    if (phase.value !== 'recruit') return;
    if (registeredCount.value === 0) return;
    phase.value = 'move_to_play';
  }

  function arriveAtPlayArea(): void {
    if (phase.value !== 'move_to_play') return;
    phase.value = 'countdown';
    countdownSec.value = COUNTDOWN_SEC;
  }

  function startPatrol(): void {
    if (phase.value !== 'countdown') return;
    phase.value = 'patrol';
    currentWaypointIdx.value = 0;
  }

  function advanceWaypoint(): void {
    if (phase.value !== 'patrol') return;
    currentWaypointIdx.value += 1;
  }

  function catchAtCurrent(participantId: number): void {
    if (phase.value !== 'patrol') return;
    const idx = currentWaypointIdx.value;
    if (idx < 0 || idx >= waypoints.value.length) return;
    const p = participants.value.find((x) => x.id === participantId);
    if (!p || !p.registered || p.caught) return;
    p.caught = true;
    p.caughtAt = waypoints.value[idx].label;
    const banner: CaptureBanner = {
      id: ++bannerSeq,
      participantId: p.id,
      participantName: p.name,
      waypointLabel: waypoints.value[idx].label,
    };
    captureBanners.value.push(banner);
    window.setTimeout(() => {
      captureBanners.value = captureBanners.value.filter((b) => b.id !== banner.id);
    }, 3000);
  }

  function finishPatrol(): void {
    if (phase.value !== 'patrol') return;
    phase.value = 'return';
  }

  function finishReturn(): void {
    if (phase.value !== 'return') return;
    phase.value = 'end';
  }

  function tickCountdown(): void {
    if (phase.value !== 'countdown') return;
    if (countdownSec.value > 0) countdownSec.value -= 1;
  }

  function reset(): void {
    phase.value = 'recruit';
    participants.value = makeInitialParticipants(ROSTER_FALLBACK);
    currentWaypointIdx.value = -1;
    countdownSec.value = COUNTDOWN_SEC;
    captureBanners.value = [];
  }

  const state = reactive({
    phase,
    participants,
    waypoints,
    currentWaypointIdx,
    waypointStatus,
    countdownSec,
    captureBanners,
    playArea: PLAY_AREA_LABEL,
    registeredCount,
    winners,
    patrolExhausted,
  }) as HideAndSeekState;

  const actions: HideAndSeekActions = {
    registerParticipant,
    unregisterParticipant,
    finishRecruit,
    arriveAtPlayArea,
    startPatrol,
    advanceWaypoint,
    catchAtCurrent,
    finishPatrol,
    finishReturn,
    tickCountdown,
    setRoster,
    reset,
  };

  return { state, actions };
}
