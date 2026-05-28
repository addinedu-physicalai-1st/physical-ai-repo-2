<script setup lang="ts">
import { computed, inject, onUnmounted, ref, watch } from 'vue';
import { storeToRefs } from 'pinia';
import { useModeStore } from '@/stores/mode';
import { VOICE_CONTROLLER_KEY } from '@/composables/voiceControllerKey';
import { useModeIntents } from '@/composables/useModeIntents';

type Phase = 'intro' | 'rps' | 'announce' | 'playing' | 'done';

const voiceController = inject(VOICE_CONTROLLER_KEY);
const tts = {
  speak: (text: string) => { voiceController?.speak(text); return Promise.resolve(); },
  cancel: () => { voiceController?.cancelSpeak(); },
};

const mode = useModeStore();
const { currentMode } = storeToRefs(mode);
const isActive = computed(() => currentMode.value === '블럭쌓기');

const phase = ref<Phase>('intro');
const sessionId = ref<string | null>(null);
const homeEventCount = ref(0);
const error = ref<string | null>(null);
let eventSource: EventSource | null = null;
let phaseTimer: number | null = null;
let rpsDetectAbort: AbortController | null = null;

function exitToIdle(): void {
  mode.setMode('대기');
}

function playCelebration(): void {
  try {
    const audio = new Audio('/sounds/fanfare.mp3');
    void audio.play();
  } catch {
    /* 재생 실패 무시 */
  }
}

function closeEventSource(): void {
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
}

function clearTimers(): void {
  if (phaseTimer !== null) {
    window.clearTimeout(phaseTimer);
    phaseTimer = null;
  }
  if (rpsDetectAbort !== null) {
    rpsDetectAbort.abort();
    rpsDetectAbort = null;
  }
}

async function startSession(): Promise<void> {
  error.value = null;
  homeEventCount.value = 0;
  try {
    const r = await fetch('/api/noriarm/games/block-stacking/sessions', { method: 'POST' });
    const data = (await r.json()) as { session_id: string };
    sessionId.value = data.session_id;
    subscribeEvents(data.session_id);
    await playRps();
  } catch (e) {
    error.value = String(e);
  }
}

function subscribeEvents(sid: string): void {
  closeEventSource();
  eventSource = new EventSource(`/api/noriarm/games/block-stacking/sessions/${sid}/events`);
  eventSource.onmessage = (ev) => {
    try {
      const payload = JSON.parse(ev.data);
      if (payload.type === 'home_event') {
        homeEventCount.value = payload.count;
        if (payload.count === 1) {
          void tts.speak('잘했어! 이번엔 초록색 블록을 쌓아봐!');
        }
      } else if (payload.type === 'done') {
        phase.value = 'done';
        void tts.speak('잘했어! 완벽해!');
        playCelebration();
        closeEventSource();
      }
    } catch {
      /* keepalive 등 무시 */
    }
  };
  eventSource.onerror = () => {
    console.warn('[BlockStacking] SSE error');
  };
}

const detectedGesture = ref<string | null>(null);
const robotGesture = ref<string | null>(null);
const humanWon = ref<boolean | null>(null); // null=비김

type RpsKey = '가위' | '바위' | '보';
const RPS_BEATS: Record<RpsKey, RpsKey> = { '가위': '보', '바위': '가위', '보': '바위' };

function calcWinner(robot: string, human: string): 'human' | 'robot' | 'draw' {
  if (robot === human) return 'draw';
  return RPS_BEATS[robot as RpsKey] === human ? 'robot' : 'human';
}

async function playRps(): Promise<void> {
  if (!sessionId.value) return;
  phase.value = 'rps';
  detectedGesture.value = null;
  robotGesture.value = null;
  humanWon.value = null;
  void tts.speak('가위바위보!');

  const sid = sessionId.value;

  // 로봇 동작 시작 — robot_gesture 받아옴
  try {
    const r = await fetch(`/api/noriarm/games/block-stacking/sessions/${sid}/rps`, { method: 'POST' });
    const d = (await r.json()) as { robot_gesture: string | null };
    robotGesture.value = d.robot_gesture;
  } catch {
    return;
  }

  // 감지 — 백엔드가 손 인식될 때까지 블로킹
  clearTimers();
  rpsDetectAbort = new AbortController();
  let humanGesture: string | null = null;
  try {
    const r = await fetch(`/api/noriarm/games/block-stacking/sessions/${sid}/rps-detect`, {
      method: 'POST',
      signal: rpsDetectAbort.signal,
    });
    const data = (await r.json()) as { gesture: string | null };
    humanGesture = data.gesture;
  } catch {
    return;
  }
  rpsDetectAbort = null;
  detectedGesture.value = humanGesture;

  if (!humanGesture) {
    // 감지 실패 → 재시도
    void playRps();
    return;
  }

  const result = calcWinner(robotGesture.value ?? '', humanGesture);

  if (result === 'draw') {
    void tts.speak('비겼어! 다시 해볼까?');
    phaseTimer = window.setTimeout(() => { phaseTimer = null; void playRps(); }, 2000);
    return;
  }

  humanWon.value = result === 'human';

  // 텍스트와 동시에 TTS 즉시 발화
  const prefix = robotGesture.value && humanGesture ? `나는 ${robotGesture.value}, 니가 ${humanGesture}를 냈네! ` : '';
  const resultMsg = humanWon.value ? `${prefix}니가 이겼어! 니가 먼저야!` : `${prefix}내가 이겼어! 니가 먼저해!`;
  void tts.speak(resultMsg);

  // 4초 대기 (로봇 홈 복귀) → announceWinner
  phaseTimer = window.setTimeout(() => { phaseTimer = null; void announceWinner(); }, 4000);
}

async function announceWinner(): Promise<void> {
  phase.value = 'announce';
  clearTimers();
  phaseTimer = window.setTimeout(() => {
    phaseTimer = null;
    void startPlaying();
  }, 2500);
}

async function startPlaying(): Promise<void> {
  if (!sessionId.value) return;
  try {
    const r = await fetch(`/api/noriarm/games/block-stacking/sessions/${sessionId.value}/start`, {
      method: 'POST',
    });
    if (!r.ok) throw new Error(`start 실패 (${r.status})`);
    phase.value = 'playing';
    void tts.speak('파란색 블록을 쌓아봐!');
  } catch (e) {
    error.value = String(e);
    phase.value = 'intro';
  }
}

async function restartSession(): Promise<void> {
  await endSession();
  phase.value = 'intro';
  await startSession();
}

async function endSession(): Promise<void> {
  clearTimers();
  if (!sessionId.value) return;
  try {
    await fetch(`/api/noriarm/games/block-stacking/sessions/${sessionId.value}`, {
      method: 'DELETE',
    });
  } catch {
    /* ignore */
  }
  sessionId.value = null;
  closeEventSource();
}

useModeIntents('블럭쌓기', {
  onStart: () => {
    if (phase.value === 'intro') void startSession();
    else if (phase.value === 'done') void restartSession();
  },
  onModeExit: () => exitToIdle(),
});

watch(isActive, async (active, prev) => {
  if (!active && prev) {
    await endSession();
    phase.value = 'intro';
  }
  if (active && !prev) {
    phase.value = 'intro';
    void startSession();
  }
});

onUnmounted(() => {
  clearTimers();
  void endSession();
});
</script>

<template>
  <Teleport to="body">
    <Transition name="bs-fade">
      <div v-if="isActive" class="bs-overlay" :data-phase="phase">
        <div v-if="phase === 'rps'" class="card">
          <div class="card-body">
            <template v-if="detectedGesture">
              <p class="hint">너는 {{ detectedGesture }}, 나는 {{ robotGesture }}</p>
              <h2 v-if="humanWon === true">니가 이겼어! 🎉</h2>
              <h2 v-else-if="humanWon === false">내가 이겼어! 🤖</h2>
              <h2 v-else>비겼어! 다시 해볼까? 🤝</h2>
              <p class="hint">로봇이 돌아오는 중…</p>
            </template>
            <template v-else>
              <p class="hint">손을 카메라에 보여줘!</p>
              <h2>가위바위보!</h2>
              <p class="hint">감지 중…</p>
            </template>
          </div>
          <div class="card-actions">
            <button class="ghost" @click="exitToIdle">그만하기</button>
          </div>
        </div>

        <div v-else-if="phase === 'announce'" class="card">
          <div class="card-body">
            <h2 v-if="humanWon">니가 이겼어! 🎉</h2>
            <h2 v-else>내가 이겼어! 🤖</h2>
            <p>먼저 블럭을 쌓아!</p>
          </div>
          <div class="card-actions">
            <button class="ghost" @click="exitToIdle">그만하기</button>
          </div>
        </div>

        <div v-else-if="phase === 'playing'" class="card">
          <div class="card-body">
            <h2>블럭을 쌓고 있어요</h2>
            <div v-if="homeEventCount === 0" class="notice" style="color:#1d4ed8;background:#eff6ff;border-color:#93c5fd;">
              🟦 파란색 블록을 쌓아봐!
            </div>
            <div v-else-if="homeEventCount === 1" class="notice" style="color:#166534;background:#f0fdf4;border-color:#86efac;">
              🟩 초록색 블록을 쌓아봐!
            </div>
            <div class="counter">로봇이 블럭을 쌓은 횟수: <strong>{{ homeEventCount }}</strong> / 2</div>
          </div>
          <div class="card-actions">
            <button class="ghost" @click="exitToIdle">그만하기</button>
          </div>
        </div>

        <div v-else-if="phase === 'done'" class="card">
          <div class="card-body">
            <h2>다 쌓았어요! 🎉</h2>
          </div>
          <div class="card-actions">
            <button class="primary" @click="restartSession">다시하기</button>
            <button class="ghost" @click="exitToIdle">그만하기</button>
          </div>
        </div>

        <div v-if="error" class="error">{{ error }}</div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.bs-overlay {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.4);
  z-index: 50;
}
.card {
  background: white;
  padding: 32px;
  border-radius: 16px;
  width: 360px;
  height: 300px;
  text-align: center;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}
.card-body {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  flex: 1;
  justify-content: center;
}
.card-actions {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.primary {
  padding: 12px 32px;
  font-size: 1.2rem;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 8px;
  cursor: pointer;
}
.ghost {
  padding: 12px 32px;
  font-size: 1.2rem;
  background: transparent;
  border: 1px solid #ccc;
  border-radius: 8px;
  cursor: pointer;
}
.notice {
  font-size: 1.4rem;
  font-weight: bold;
  color: #1d4ed8;
  background: #eff6ff;
  border: 2px solid #93c5fd;
  border-radius: 12px;
  padding: 12px 20px;
}
.counter { font-size: 1.1rem; }
.hint { color: #666; }
.error { color: #dc2626; margin-top: 16px; }
.bs-fade-enter-active,
.bs-fade-leave-active {
  transition: opacity 0.3s;
}
.bs-fade-enter-from,
.bs-fade-leave-to {
  opacity: 0;
}
</style>
