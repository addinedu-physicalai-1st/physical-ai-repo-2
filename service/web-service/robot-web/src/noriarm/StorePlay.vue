<script setup lang="ts">
import { computed, inject, onUnmounted, ref, watch } from 'vue';
import { storeToRefs } from 'pinia';
import { useModeStore } from '@/stores/mode';
import { useVoiceStore } from '@/stores/voice';
import { useModeIntents } from '@/composables/useModeIntents';
import { VOICE_CONTROLLER_KEY } from '@/composables/voiceControllerKey';

// 5종 과일 — game.yaml 의 paraphrases 와 1:1.
const ITEMS: { id: string; label: string; prompts: string[] }[] = [
  { id: 'broccoli',   label: '브로콜리', prompts: ['give me broccoli', 'bring me broccoli', 'pass me the broccoli', 'I want broccoli'] },
  { id: 'grape',      label: '포도',     prompts: ['give me grape', 'bring me grape', 'pass me the grape', 'I want grape'] },
  { id: 'kiwi',       label: '키위',     prompts: ['give me kiwi', 'bring me kiwi', 'pass me the kiwi', 'I want kiwi'] },
  { id: 'strawberry', label: '딸기',     prompts: ['give me strawberry', 'bring me strawberry', 'pass me the strawberry', 'I want strawberry'] },
  { id: 'pineapple',  label: '파인애플', prompts: ['give me pineapple', 'bring me pineapple', 'pass me the pineapple', 'I want pineapple'] },
];

// STT 동적 힌트 — 가게놀이 모드일 때 whisper initial_prompt 에 주입 (stt_hints_set).
// 짧은 발화 오인식 방지. 음식 단어 + 시나리오 명령어("시작"/"또 할래"/"그만") 둘 다.
// 명령어 없으면 small 모델이 "또 할래"를 '잘래/오할로래' 로 오인식 → start 매칭 실패.
const STT_FOOD_HINTS: string[] = [
  // 음식
  '딸기', '포도', '키위', '브로콜리', '파인애플',
  '딸기 줘', '포도 줘', '키위 줘', '브로콜리 줘', '파인애플 줘',
  '딸기 주세요', '줘', '주세요',
  // 시나리오 명령어
  '시작', '시작할게', '취소',
  '또 할래', '더 할래', '또 해', '또 하자',
  '그만', '그만하기', '끝내기',
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
const voice = useVoiceStore();
const { currentMode, requestedStoreItem } = storeToRefs(mode);
const isActive = computed(() => currentMode.value === '가게놀이');

const phase = ref<Phase>('intro');
const sessionId = ref<string | null>(null);
const selectedItem = ref<(typeof ITEMS)[number] | null>(null);
const error = ref<string | null>(null);
let eventSource: EventSource | null = null;

// 카메라 미리보기 — runner 가 ROI masked 프레임을 /tmp JPEG 로 저장, control_service 가 서빙.
// 5fps 로 img cache-bust 해서 polling. cam 키는 학습 모델 key.
const PREVIEW_CAMS = [
  { key: 'top', label: '탑뷰' },
  { key: 'wrist_left', label: '왼손목' },
  { key: 'wrist_right', label: '오른손목' },
];
const previewTick = ref(0);
let previewTimer: number | null = null;

// 서빙 BGM — serving phase 동안 loop 재생. public/audio/storeplay_bgm.mp3 (사용자 제공).
// 멘트(서버 WebRTC TTS)는 BGM(브라우저 로컬 오디오)과 별개 스트림이라 BGM 음량이 크면
// 묻힘. 로봇이 말하는 동안(voice.state==='speaking') BGM 을 BGM_DUCK 으로 낮추고 복구.
const BGM_VOLUME = 0.45;
const BGM_DUCK = 0.0;  // 멘트 중엔 완전 음소거 — 0.1 로는 센 BGM 에 "주문 나왔습니다" 가 묻혀서.
let bgm: HTMLAudioElement | null = null;
function startBgm(): void {
  if (!bgm) {
    bgm = new Audio('/audio/storeplay_bgm.mp3');
    bgm.loop = true;
  }
  bgm.volume = voice.state === 'speaking' ? BGM_DUCK : BGM_VOLUME;
  void bgm.play().catch(() => { /* 음원 없거나 자동재생 차단 — 무시 */ });
}
function stopBgm(): void {
  if (bgm) {
    bgm.pause();
    bgm.currentTime = 0;
  }
  if (bellSfx) {
    bellSfx.pause();
    bellSfx.currentTime = 0;
  }
}

// 벨 누름 효과음 — bell_rung 시점에 재생 (음성 멘트 대신, 사용자 선택). 사용자 제공
// public/audio/storeplay_bell.mp3. 재생 동안 서빙 BGM 음소거 → 효과음 끝나면 복구.
let bellSfx: HTMLAudioElement | null = null;
function restoreServingBgm(): void {
  if (bgm && phase.value === 'serving') bgm.volume = BGM_VOLUME;
}
function playBellSfx(): void {
  if (!bellSfx) {
    bellSfx = new Audio('/audio/storeplay_bell.mp3');
    bellSfx.addEventListener('ended', restoreServingBgm);
  }
  if (bgm) bgm.volume = 0.0;  // 효과음 안 묻히게 BGM 음소거
  bellSfx.currentTime = 0;
  void bellSfx.play().catch(() => { restoreServingBgm(); });  // 음원 없음/차단 시 BGM 복구
}

function previewUrl(cam: string): string {
  if (!sessionId.value) return '';
  return `/api/noriarm/games/store-play/sessions/${sessionId.value}/preview/${cam}?t=${previewTick.value}`;
}
function startPreview(): void {
  stopPreview();
  previewTimer = window.setInterval(() => { previewTick.value++; }, 200);
}
function stopPreview(): void {
  if (previewTimer !== null) {
    window.clearInterval(previewTimer);
    previewTimer = null;
  }
}

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
      const payload = JSON.parse(ev.data) as { type: string; prompt?: string; what?: string };
      switch (payload.type) {
        case 'ready':
          // start 완료 — bootSession 에서 phase 처리하지만 보강.
          if (phase.value === 'loading') phase.value = 'ready';
          break;
        case 'task_started':
          // 클라이언트가 이미 'serving' 으로 갱신했지만 일관성 위해 보강.
          break;
        case 'bell_rung':
          // 로봇이 벨 누른 시점 — 효과음만 재생 (음성 멘트 생략, 사용자 선택). task 당 1회.
          playBellSfx();
          break;
        case 'missing': {
          // serve 시작 시 target/plate 미검출 — 멘트만 (serve 는 그대로 진행).
          const ko = payload.what === 'plate'
            ? '접시'
            : (ITEMS.find((it) => it.id === payload.what)?.label ?? payload.what ?? '물건');
          speak(`${ko}가 없어요. ${ko}를 놓아주세요`);
          break;
        }
        case 'task_done':
          // 홈 복귀 = 완료 → done 화면. 멘트는 bell_rung 에서 이미 함.
          phase.value = 'done';
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
    voice.setSttHints([]);  // 가게놀이 나가면 음식 힌트 제거
    stopPreview();
    stopBgm();
    await endSession();
    phase.value = 'intro';
    selectedItem.value = null;
    error.value = null;
  }
  if (active && !prev) {
    voice.setSttHints(STT_FOOD_HINTS);  // 음식 단어 STT 힌트 주입 (짧은 발화 오인식 방지)
    phase.value = 'intro';
  }
}, { immediate: true });

// 서빙 중에만 카메라 미리보기 polling + BGM. 그 외 정지.
watch(phase, (p) => {
  if (p === 'serving') {
    startPreview();
    startBgm();
  } else {
    stopPreview();
    stopBgm();
  }
});

// BGM ducking — 로봇이 말하는 동안 BGM 낮춰 멘트가 안 묻히게. serving 외엔 bgm null/정지라 noop.
watch(() => voice.state, (s) => {
  if (bgm) bgm.volume = s === 'speaking' ? BGM_DUCK : BGM_VOLUME;
});

// 음성 명령 ("딸기 줘") — store_item intent 가 mode.requestedStoreItem 채움.
// 가게놀이 모드 + ready 일 때만 serve. ts 로 같은 item 연속 발화도 트리거.
watch(requestedStoreItem, (req) => {
  if (!req || !isActive.value) return;
  if (phase.value !== 'ready') {
    // loading/serving/done 중이면 음성 무시 (또는 큐잉 안 함 — 단순화).
    return;
  }
  const item = ITEMS.find((it) => it.id === req.item);
  if (item) void serveItem(item);
});

// 음성 sub_command — useVoiceController 가 호출.
//   onStart  (sub_command 'start': "시작", "또 할래" 등) → phase 별 시작/또하기
//   onModeExit (sub_command 'stop': "취소", "그만"; 또는 mode_change '대기') → 중단/끝내기
useModeIntents('가게놀이', {
  onStart: () => {
    if (phase.value === 'intro') void bootSession();      // "시작"
    else if (phase.value === 'done') phase.value = 'ready'; // "또 할래"
  },
  onModeExit: () => {
    if (phase.value === 'serving') void abortServe();      // "그만" — task 중단
    else exitToIdle();                                     // "취소"/"끝내기" — 모드 종료
  },
});

onUnmounted(() => {
  stopPreview();
  stopBgm();
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
          <div class="cam-grid">
            <div v-for="cam in PREVIEW_CAMS" :key="cam.key" class="cam-cell">
              <img
                class="cam-img"
                :src="previewUrl(cam.key)"
                :alt="cam.label"
                @error="(e) => ((e.target as HTMLImageElement).style.visibility = 'hidden')"
                @load="(e) => ((e.target as HTMLImageElement).style.visibility = 'visible')"
              />
              <span class="cam-label">{{ cam.label }}</span>
            </div>
          </div>
          <p class="cam-note">로봇이 보는 화면 (ROI)</p>
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
.card.playing { min-width: 360px; }
.cam-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px;
  margin: 4px 0;
}
.cam-cell {
  position: relative;
  aspect-ratio: 4 / 3;
  background: #111;
  border-radius: 6px;
  overflow: hidden;
}
.cam-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.cam-label {
  position: absolute;
  bottom: 2px;
  left: 4px;
  font-size: 10px;
  color: #fff;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.8);
}
.cam-note {
  font-size: 11px;
  color: #999;
  margin: 0;
}
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
