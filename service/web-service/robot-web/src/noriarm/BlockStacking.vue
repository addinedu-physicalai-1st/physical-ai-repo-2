<script setup lang="ts">
import { computed, inject, onUnmounted, ref, watch } from 'vue';
import { storeToRefs } from 'pinia';
import { useModeStore } from '@/stores/mode';
import { VOICE_CONTROLLER_KEY } from '@/composables/voiceControllerKey';

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

function exitToIdle(): void {
  mode.setMode('대기');
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
        void tts.speak('잘했어! 다 쌓았어!');
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

async function playRps(): Promise<void> {
  if (!sessionId.value) return;
  phase.value = 'rps';
  void tts.speak('가위바위보!');
  await fetch(`/api/noriarm/games/block-stacking/sessions/${sessionId.value}/rps`, {
    method: 'POST',
  });
  clearTimers();
  phaseTimer = window.setTimeout(() => {
    phaseTimer = null;
    void announceWinner();
  }, 6000);
}

async function announceWinner(): Promise<void> {
  phase.value = 'announce';
  void tts.speak('네가 이겼어! 네가 먼저야!');
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

watch(isActive, async (active, prev) => {
  if (!active && prev) {
    await endSession();
    phase.value = 'intro';
  }
  if (active && !prev) {
    phase.value = 'intro';
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
        <div v-if="phase === 'intro'" class="card">
          <h1>블럭쌓기</h1>
          <p>가위바위보로 누가 먼저 쌓을지 정해볼까?</p>
          <button class="primary" @click="startSession">시작하기</button>
          <button class="ghost" @click="exitToIdle">취소</button>
        </div>

        <div v-else-if="phase === 'rps'" class="card">
          <h2>가위바위보!</h2>
          <p class="hint">로봇 팔이 모양을 보여줍니다…</p>
        </div>

        <div v-else-if="phase === 'announce'" class="card">
          <h2>네가 이겼어! 🎉</h2>
          <p>먼저 블럭을 쌓아!</p>
        </div>

        <div v-else-if="phase === 'playing'" class="card">
          <h2>블럭을 쌓고 있어요</h2>
          <div v-if="homeEventCount === 0" class="notice" style="color:#1d4ed8;background:#eff6ff;border-color:#93c5fd;">
            🟦 파란색 블록을 쌓아봐!
          </div>
          <div v-else-if="homeEventCount === 1" class="notice" style="color:#166534;background:#f0fdf4;border-color:#86efac;">
            🟩 초록색 블록을 쌓아봐!
          </div>
          <div class="counter">로봇이 블럭을 쌓은 횟수: <strong>{{ homeEventCount }}</strong> / 2</div>
          <button class="ghost" @click="exitToIdle">그만</button>
        </div>

        <div v-else-if="phase === 'done'" class="card">
          <h2>다 쌓았어요! 🎉</h2>
          <button class="primary" @click="exitToIdle">끝내기</button>
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
  min-width: 320px;
  text-align: center;
  display: flex;
  flex-direction: column;
  gap: 16px;
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
  padding: 8px 16px;
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
