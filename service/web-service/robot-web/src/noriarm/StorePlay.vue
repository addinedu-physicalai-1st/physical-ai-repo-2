<script setup lang="ts">
import { computed, inject, onUnmounted, ref, watch } from 'vue';
import { storeToRefs } from 'pinia';
import { useModeStore } from '@/stores/mode';
import { VOICE_CONTROLLER_KEY } from '@/composables/voiceControllerKey';

// 5종 과일 — game.yaml 의 paraphrases 와 1:1.
const ITEMS: { id: string; label: string; prompts: string[] }[] = [
  { id: 'broccoli',   label: '브로콜리', prompts: ['give me broccoli', 'bring me broccoli', 'pass me the broccoli', 'I want broccoli'] },
  { id: 'grape',      label: '포도',     prompts: ['give me grape', 'bring me grape', 'pass me the grape', 'I want grape'] },
  { id: 'kiwi',       label: '키위',     prompts: ['give me kiwi', 'bring me kiwi', 'pass me the kiwi', 'I want kiwi'] },
  { id: 'strawberry', label: '딸기',     prompts: ['give me strawberry', 'bring me strawberry', 'pass me the strawberry', 'I want strawberry'] },
  { id: 'pineapple',  label: '파인애플', prompts: ['give me pineapple', 'bring me pineapple', 'pass me the pineapple', 'I want pineapple'] },
];

// long-lived runner UX 흐름:
//   intro    → 모드 진입 화면 (시작 버튼)
//   loading  → POST /sessions + /start 진행 중 (모델·YOLO·카메라·모터 load, ~10~20s)
//   ready    → idle 상태 (아이템 클릭 대기)
//   serving  → 아이템 클릭 후 task 실행 중 (양팔 움직이는 중)
//   done     → task 완료, 또하기/끝내기 선택
type Phase = 'intro' | 'loading' | 'ready' | 'serving' | 'done';

const voiceController = inject(VOICE_CONTROLLER_KEY);
const speak = (text: string) => voiceController?.speak(text);

const mode = useModeStore();
const { currentMode } = storeToRefs(mode);
const isActive = computed(() => currentMode.value === '가게놀이');

const phase = ref<Phase>('intro');
const sessionId = ref<string | null>(null);
const selectedItem = ref<(typeof ITEMS)[number] | null>(null);
const error = ref<string | null>(null);
let eventSource: EventSource | null = null;

function exitToIdle(): void {
  mode.setMode('대기');
}

function closeEventSource(): void {
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
}

function pickPrompt(item: (typeof ITEMS)[number]): string {
  return item.prompts[Math.floor(Math.random() * item.prompts.length)];
}

// ───────────────── session lifecycle ─────────────────

async function bootSession(): Promise<void> {
  error.value = null;
  phase.value = 'loading';
  try {
    // 1) POST /sessions — spawn runner (heavy init 시작).
    const r1 = await fetch('/api/noriarm/games/store-play/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target: 'real' }),
    });
    if (!r1.ok) throw new Error(`세션 생성 실패 (${r1.status})`);
    const data1 = (await r1.json()) as { session_id: string };
    sessionId.value = data1.session_id;
    subscribeEvents(data1.session_id);

    // 2) POST /start — wait_ready + send_start (모델·YOLO·카메라·모터 load 완료까지 block).
    const r2 = await fetch(`/api/noriarm/games/store-play/sessions/${data1.session_id}/start`, {
      method: 'POST',
    });
    if (!r2.ok) {
      const msg = await r2.text().catch(() => '');
      throw new Error(`start 실패 (${r2.status}): ${msg}`);
    }
    phase.value = 'ready';
    speak('어떤 거 줄까?');
  } catch (e) {
    error.value = String(e);
    phase.value = 'intro';
    void endSession();
  }
}

async function serveItem(item: (typeof ITEMS)[number]): Promise<void> {
  if (!sessionId.value || phase.value !== 'ready') return;
  selectedItem.value = item;
  error.value = null;
  const prompt = pickPrompt(item);
  try {
    const r = await fetch(`/api/noriarm/games/store-play/sessions/${sessionId.value}/serve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt }),
    });
    if (!r.ok) {
      const msg = await r.text().catch(() => '');
      throw new Error(`serve 실패 (${r.status}): ${msg}`);
    }
    phase.value = 'serving';
    speak(`${item.label} 서빙할게!`);
  } catch (e) {
    error.value = String(e);
    phase.value = 'ready';
  }
}

async function abortServe(): Promise<void> {
  if (!sessionId.value || phase.value !== 'serving') return;
  try {
    await fetch(`/api/noriarm/games/store-play/sessions/${sessionId.value}/abort`, {
      method: 'POST',
    });
  } catch {
    /* ignore */
  }
  // abort → 서버가 task_done 이벤트 보내며 idle 복귀 → phase = ready (SSE 에서 처리).
}

function subscribeEvents(sid: string): void {
  closeEventSource();
  eventSource = new EventSource(`/api/noriarm/games/store-play/sessions/${sid}/events`);
  eventSource.onmessage = (ev) => {
    try {
      const payload = JSON.parse(ev.data) as { type: string; prompt?: string };
      switch (payload.type) {
        case 'ready':
          // start 완료 — bootSession 에서 phase 처리하지만 보강.
          if (phase.value === 'loading') phase.value = 'ready';
          break;
        case 'task_started':
          // 클라이언트가 이미 'serving' 으로 갱신했지만 일관성 위해 보강.
          break;
        case 'task_done':
          phase.value = 'done';
          speak('다 됐어!');
          break;
        case 'task_timeout':
          phase.value = 'ready';
          error.value = '시간 초과 — 다시 시도해봐';
          break;
        case 'task_error':
          phase.value = 'ready';
          error.value = `task 실패: ${(payload as any).error ?? ''}`;
          break;
        case 'done':
          // session 종료 — 보통 사용자가 모드 나갈 때.
          closeEventSource();
          break;
      }
    } catch {
      /* keepalive 무시 */
    }
  };
  eventSource.onerror = () => {
    console.warn('[StorePlay] SSE error');
  };
}

async function endSession(): Promise<void> {
  closeEventSource();
  if (!sessionId.value) return;
  const sid = sessionId.value;
  sessionId.value = null;
  try {
    await fetch(`/api/noriarm/games/store-play/sessions/${sid}`, { method: 'DELETE' });
  } catch {
    /* ignore */
  }
}

// ───────────────── lifecycle ─────────────────

watch(isActive, async (active, prev) => {
  if (!active && prev) {
    await endSession();
    phase.value = 'intro';
    selectedItem.value = null;
    error.value = null;
  }
  if (active && !prev) {
    phase.value = 'intro';
  }
});

onUnmounted(() => {
  void endSession();
});
</script>

<template>
  <Teleport to="body">
    <Transition name="sp-fade">
      <div v-if="isActive" class="sp-overlay" :data-phase="phase">

        <div v-if="phase === 'intro'" class="card">
          <h1>가게놀이</h1>
          <p>준비됐어? 시작하면 로봇이 깰 거야!</p>
          <button class="primary" @click="bootSession">시작</button>
          <button class="ghost" @click="exitToIdle">취소</button>
        </div>

        <div v-else-if="phase === 'loading'" class="card">
          <h2>준비 중…</h2>
          <p class="hint">로봇이 깨어나고 있어. 잠깐만 기다려!</p>
          <div class="spinner" />
        </div>

        <div v-else-if="phase === 'ready'" class="card">
          <h2>어떤 거 줄까?</h2>
          <div class="item-grid">
            <button
              v-for="item in ITEMS"
              :key="item.id"
              class="item-btn"
              @click="serveItem(item)"
            >
              {{ item.label }}
            </button>
          </div>
          <button class="ghost" @click="exitToIdle">끝내기</button>
        </div>

        <div v-else-if="phase === 'serving'" class="card playing">
          <h2>서빙 중!</h2>
          <p class="item-name">{{ selectedItem?.label }}</p>
          <p class="hint">로봇 팔이 물건을 가져가고 있어…</p>
          <button class="ghost" @click="abortServe">그만</button>
        </div>

        <div v-else-if="phase === 'done'" class="card">
          <h2>다 됐어! 🎉</h2>
          <p>{{ selectedItem?.label }} 받아봐!</p>
          <button class="primary" @click="phase = 'ready'">또 하기</button>
          <button class="ghost" @click="exitToIdle">끝내기</button>
        </div>

        <div v-if="error" class="error">{{ error }}</div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.sp-overlay {
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
.card.playing { min-width: 320px; }
.item-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}
.item-btn {
  padding: 14px 8px;
  font-size: 1rem;
  font-weight: 600;
  background: #eff6ff;
  border: 2px solid #bfdbfe;
  border-radius: 10px;
  cursor: pointer;
  transition: background 0.15s;
}
.item-btn:hover {
  background: #dbeafe;
}
.item-name {
  font-size: 2rem;
  font-weight: 800;
}
.primary {
  padding: 12px 32px;
  font-size: 1.1rem;
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
.hint { color: #666; }
.error { color: #dc2626; margin-top: 8px; }
.spinner {
  width: 36px;
  height: 36px;
  margin: 0 auto;
  border: 4px solid #e5e7eb;
  border-top-color: #3b82f6;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.sp-fade-enter-active,
.sp-fade-leave-active {
  transition: opacity 0.3s;
}
.sp-fade-enter-from,
.sp-fade-leave-to {
  opacity: 0;
}
</style>
