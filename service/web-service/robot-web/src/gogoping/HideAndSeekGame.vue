<script setup lang="ts">
/**
 * GogoPing 숨바꼭질 (SR-PLAY-007) UI — gogoping 모드가 "숨바꼭질" 일 때 마운트.
 *
 * 단계 머신 (BT 가 publish 하는 hideseek_phase 가 단일 진실원):
 *   move_to_play → recruit → countdown → patrol → return → end
 *
 * 본 컴포넌트는 BT snapshot 으로부터 phase 만 동기화하고, 화면 라우팅 + UI 부속
 * 부수 효과 (countdown 1Hz tick, chant, 안내 음성) 만 책임진다. 단계 전이 자체는
 * `useHideseekPhaseStore.phase` 를 watch 해서 `actions.syncFromBtPhase` 로 들어옴.
 */
import { inject, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { storeToRefs } from 'pinia';
import { useModeStore } from '@/stores/mode';
import { useHideseekPhaseStore } from '@/gogoping/stores/hideseekPhase';
import { VOICE_CONTROLLER_KEY } from '@/composables/voiceControllerKey';
import { postModeClick } from '@/composables/useIntentDispatch';
import { useHideAndSeekState } from './useHideAndSeekState';
import { COUNTDOWN_SEC, HIDE_CHANT_INTERVAL_MS, type RosterEntry } from './fixtures';
import { postRecruitComplete } from './api/hideseekApi';
import RecruitPhase from './phases/RecruitPhase.vue';
import MoveToPlayPhase from './phases/MoveToPlayPhase.vue';
import CountdownPhase from './phases/CountdownPhase.vue';
import PatrolPhase from './phases/PatrolPhase.vue';
import ReturnPhase from './phases/ReturnPhase.vue';
import EndPhase from './phases/EndPhase.vue';

const DEVICE_TOKEN = import.meta.env.VITE_ROBOT_TOKEN ?? 'dev-robot-token-change-me';

const mode = useModeStore();
const voiceController = inject(VOICE_CONTROLLER_KEY);
const hideseekStore = useHideseekPhaseStore();
const { phase: btPhase } = storeToRefs(hideseekStore);

function speak(text: string): void {
  voiceController?.speak(text);
}

const { state, actions } = useHideAndSeekState();

const chantTick = ref(0);

const PHASE_META: Record<typeof state.phase, { label: string; helper: string; accent: string }> = {
  recruit:      { label: '모집',       helper: '같이 놀 친구들을 모으는 중',     accent: '#16a34a' },
  move_to_play: { label: '이동',       helper: `${state.playArea} 로 가는 중`,    accent: '#0ea5e9' },
  countdown:    { label: '카운트다운', helper: '눈 가리고 30 초!',                accent: '#fbbf24' },
  patrol:       { label: '순찰',       helper: '웨이포인트를 돌며 친구들을 찾아요', accent: '#f59e0b' },
  return:       { label: '복귀',       helper: '못 찾겠다 꾀꼬리!',                accent: '#7c3aed' },
  end:          { label: '발표',       helper: '오늘의 챔피언!',                  accent: '#dc2626' },
};

// -------- BT → UI phase 동기화 --------
watch(
  btPhase,
  (p) => {
    if (p) actions.syncFromBtPhase(p);
  },
  { immediate: true },
);

// -------- phase 진입/이탈 부수 효과 (음성 + 타이머) --------
let countdownTimer: number | null = null;
let chantTimer: number | null = null;

function stopCountdownTimer(): void {
  if (countdownTimer !== null) {
    window.clearInterval(countdownTimer);
    countdownTimer = null;
  }
}
function stopChantTimer(): void {
  if (chantTimer !== null) {
    window.clearInterval(chantTimer);
    chantTimer = null;
  }
}

watch(
  () => state.phase,
  (p, prev) => {
    // countdown 진입 — 안내 + 1Hz tick + 챈트 반복
    if (p === 'countdown' && prev !== 'countdown') {
      speak(`눈 감고 ${COUNTDOWN_SEC} 초 셀게!`);
      stopCountdownTimer();
      countdownTimer = window.setInterval(() => {
        actions.tickCountdown();
      }, 1000);
      // 즉시 한 번 챈트 + 이후 HIDE_CHANT_INTERVAL_MS 마다 반복
      stopChantTimer();
      chantTick.value += 1;
      speak('꼭꼭 숨어라, 머리카락 보일라!');
      chantTimer = window.setInterval(() => {
        chantTick.value += 1;
        speak('꼭꼭 숨어라, 머리카락 보일라!');
      }, HIDE_CHANT_INTERVAL_MS);
    }
    // countdown 이탈 — 두 timer 정지
    if (p !== 'countdown') {
      stopCountdownTimer();
      stopChantTimer();
    }
    // return 진입 — "못 찾겠다 꾀꼬리!"
    if (p === 'return' && prev !== 'return') {
      speak('못 찾겠다 꾀꼬리!');
    }
  },
);

async function loadRoster(): Promise<void> {
  try {
    const res = await fetch('/api/children/roster', {
      headers: { 'X-Device-Token': DEVICE_TOKEN },
    });
    if (!res.ok) return;  // 실패 시 fixture roster 그대로 사용
    const roster = (await res.json()) as RosterEntry[];
    if (Array.isArray(roster) && roster.length > 0) actions.setRoster(roster);
  } catch {
    /* 네트워크 실패 — fixture roster 로 진행 */
  }
}

onMounted(async () => {
  await loadRoster();
});

onBeforeUnmount(() => {
  stopCountdownTimer();
  stopChantTimer();
});

function onRecruitToggle(id: number): void {
  const p = state.participants.find((x) => x.id === id);
  if (!p) return;
  if (p.registered) actions.unregisterParticipant(id);
  else actions.registerParticipant(id);
}

// Task 12 — "출발" 버튼: control-service API 호출.
// phase 전환은 BT 가 SetHideseekPhase("countdown") 발화 시 snapshot 으로 들어와 자동.
async function onRecruitStart(): Promise<void> {
  const registeredIds = state.participants
    .filter((p) => p.registered)
    .map((p) => p.id);
  if (registeredIds.length === 0) return;
  const ok = await postRecruitComplete(registeredIds);
  if (!ok) {
    console.warn('recruit-complete API 실패 — BT 미연결?');
  }
}

async function close(): Promise<void> {
  mode.setMode('대기');
  try {
    await postModeClick('대기', 'gogoping');
  } catch {
    /* BT 미연결이어도 UI 는 진행 */
  }
}

async function restart(): Promise<void> {
  // BT_hide_and_seek_sub 가 Sequence(memory=True) 라 step_end 의 Running 이
  // 살아있는 동안 같은 mode 재요청 (same_state) 만으로는 처음으로 못 돌아간다.
  // → 명시적으로 cancel ("대기") 했다가 다시 "숨바꼭질" 발화 → BT 빌더 재실행.
  actions.reset();
  try {
    await postModeClick('대기', 'gogoping');
  } catch {
    /* BT 미연결이어도 UI 는 진행 */
  }
  try {
    await postModeClick('숨바꼭질', 'gogoping');
  } catch {
    /* noop */
  }
}

// PatrolPhase 인식 → caught 처리. waypoint label 그대로 기록.
function onPatrolCaught(childId: number, _childName: string, waypoint?: string): void {
  actions.markCaught(childId, waypoint ?? '');
}

// ReturnPhase 인식 → caught 처리. 복귀 중이라 정적 라벨.
function onReturnCaught(childId: number, _childName: string): void {
  actions.markCaught(childId, '복귀 중');
}
</script>

<template>
  <Transition name="fade" appear>
    <div class="popup-overlay">
      <div class="popup-card" role="dialog" aria-modal="true" aria-label="숨바꼭질">
        <header class="top-bar" :style="{ borderBottomColor: PHASE_META[state.phase].accent + '33' }">
          <div class="stage-indicator" :style="{ '--accent': PHASE_META[state.phase].accent }">
            <div class="stage-pulse" />
            <div class="stage-text">
              <div class="stage-label">{{ PHASE_META[state.phase].label }}</div>
              <div class="stage-helper">{{ PHASE_META[state.phase].helper }}</div>
            </div>
          </div>
          <button type="button" class="close-btn" aria-label="닫기" @click="close">×</button>
        </header>

        <main class="main">
          <RecruitPhase
            v-if="state.phase === 'recruit'"
            :participants="state.participants"
            :registered-count="state.registeredCount"
            @toggle="onRecruitToggle"
            @register="actions.registerParticipant"
            @start="onRecruitStart"
          />
          <MoveToPlayPhase
            v-else-if="state.phase === 'move_to_play'"
            :play-area="state.playArea"
          />
          <CountdownPhase
            v-else-if="state.phase === 'countdown'"
            :remaining-sec="state.countdownSec"
            :total-sec="COUNTDOWN_SEC"
            :chant-tick="chantTick"
          />
          <PatrolPhase
            v-else-if="state.phase === 'patrol'"
            :waypoints="state.waypoints"
            :current-idx="state.currentWaypointIdx"
            :waypoint-status="state.waypointStatus"
            :participants="state.participants"
            :capture-banners="state.captureBanners"
            @caught="onPatrolCaught"
          />
          <ReturnPhase
            v-else-if="state.phase === 'return'"
            :play-area="state.playArea"
            :participants="state.participants"
            @caught="onReturnCaught"
          />
          <EndPhase
            v-else
            :winners="state.winners"
            :caught="state.participants.filter((p) => p.registered && p.caught)"
            @restart="restart"
            @close="close"
          />
        </main>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.popup-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  backdrop-filter: blur(6px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 80;
}
.popup-card {
  width: min(960px, 92vw);
  height: min(640px, 88vh);
  background: linear-gradient(135deg, #f0fdf4 0%, #ecfccb 100%);
  border-radius: 24px;
  box-shadow: 0 30px 60px rgba(0, 0, 0, 0.25);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 22px;
  border-bottom: 2px solid transparent;
  flex-shrink: 0;
}
.stage-indicator {
  display: flex;
  align-items: center;
  gap: 12px;
}
.stage-pulse {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--accent, #16a34a);
  box-shadow: 0 0 0 6px color-mix(in srgb, var(--accent, #16a34a) 25%, transparent);
  animation: indicator-pulse 1.6s ease-in-out infinite;
}
@keyframes indicator-pulse {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.25); }
}
.stage-label {
  font-size: 18px;
  font-weight: 800;
  color: var(--accent, #16a34a);
}
.stage-helper {
  font-size: 13px;
  color: #4b5563;
  margin-top: 1px;
}

.close-btn {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  border: none;
  background: rgba(0, 0, 0, 0.08);
  font-size: 22px;
  font-weight: 800;
  cursor: pointer;
  color: #4b5563;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s ease;
}
.close-btn:hover { background: rgba(0, 0, 0, 0.16); }

.main {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.fade-enter-active, .fade-leave-active {
  transition: opacity 0.25s ease;
}
.fade-enter-from, .fade-leave-to { opacity: 0; }

@media (max-width: 768px), (pointer: coarse) {
  .popup-card {
    width: 100vw;
    height: 100dvh;
    border-radius: 0;
  }
  .stage-label { font-size: 16px; }
  .stage-helper { font-size: 11px; }
}
</style>
