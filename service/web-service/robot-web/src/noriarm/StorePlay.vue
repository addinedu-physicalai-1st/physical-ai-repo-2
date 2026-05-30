<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue';
import { storeToRefs } from 'pinia';
import { useModeStore } from '@/stores/mode';
import { useVoiceStore } from '@/stores/voice';
import { useModeIntents } from '@/composables/useModeIntents';

// 5종 과일 — game.yaml 의 paraphrases 와 1:1.
const ITEMS: { id: string; label: string; emoji: string; prompts: string[] }[] = [
  { id: 'strawberry', label: '딸기',     emoji: '🍓', prompts: ['give me strawberry', 'bring me strawberry', 'pass me the strawberry', 'I want strawberry'] },
  { id: 'grape',      label: '포도',     emoji: '🍇', prompts: ['give me grape', 'bring me grape', 'pass me the grape', 'I want grape'] },
  { id: 'kiwi',       label: '키위',     emoji: '🥝', prompts: ['give me kiwi', 'bring me kiwi', 'pass me the kiwi', 'I want kiwi'] },
  { id: 'broccoli',   label: '브로콜리', emoji: '🥦', prompts: ['give me broccoli', 'bring me broccoli', 'pass me the broccoli', 'I want broccoli'] },
  { id: 'pineapple',  label: '파인애플', emoji: '🍍', prompts: ['give me pineapple', 'bring me pineapple', 'pass me the pineapple', 'I want pineapple'] },
];
// ── 커스텀 SVG 일러스트 (이모지 대신, 손그림풍 flat) — 과일 5종 + 접시 ──
const FRUIT_SVG: Record<string, string> = {
  strawberry: `<svg viewBox="0 0 56 56" class="ill"><path d="M28 15c11 0 18 6 18 16 0 12-10 23-18 23S10 43 10 31c0-10 7-16 18-16z" fill="#fb4e5f"/><path d="M28 15c8 0 14 4 16 11-5-2-11-3-16-3s-11 1-16 3c2-7 8-11 16-11z" fill="#ff7280"/><path d="M19 9c3 1 6 4 9 8 3-4 6-7 9-8 1 4-1 8-5 9 5 0 9 2 10 6-7-4-14-5-14-5s-7 1-14 5c1-4 5-6 10-6-4-1-6-5-5-9z" fill="#36b56b"/><g fill="#ffe07a"><ellipse cx="20" cy="33" rx="1.5" ry="2.2" transform="rotate(-20 20 33)"/><ellipse cx="29" cy="30" rx="1.5" ry="2.2"/><ellipse cx="37" cy="33" rx="1.5" ry="2.2" transform="rotate(20 37 33)"/><ellipse cx="24" cy="40" rx="1.5" ry="2.2" transform="rotate(-15 24 40)"/><ellipse cx="33" cy="40" rx="1.5" ry="2.2" transform="rotate(15 33 40)"/><ellipse cx="28" cy="47" rx="1.5" ry="2.2"/></g></svg>`,
  grape: `<svg viewBox="0 0 56 56" class="ill"><path d="M28 6c0 4 1 7 3 9" stroke="#7c4a2c" stroke-width="2.4" fill="none" stroke-linecap="round"/><path d="M31 9c3-4 9-4 12 0-3 4-9 4-12 0z" fill="#36b56b"/><g fill="#8559d6"><circle cx="28" cy="20" r="6"/><circle cx="20" cy="25" r="6"/><circle cx="36" cy="25" r="6"/><circle cx="28" cy="30" r="6"/><circle cx="21" cy="36" r="6"/><circle cx="35" cy="36" r="6"/><circle cx="28" cy="42" r="6"/></g><g fill="#ab87ee"><circle cx="26" cy="18" r="1.7"/><circle cx="18" cy="23" r="1.7"/><circle cx="34" cy="23" r="1.7"/><circle cx="26" cy="28" r="1.7"/><circle cx="19" cy="34" r="1.7"/><circle cx="33" cy="34" r="1.7"/><circle cx="26" cy="40" r="1.7"/></g></svg>`,
  kiwi: `<svg viewBox="0 0 56 56" class="ill"><circle cx="28" cy="28" r="21" fill="#8a6a3c"/><circle cx="28" cy="28" r="18" fill="#a8cf57"/><circle cx="28" cy="28" r="7" fill="#f4f7e6"/><g fill="#33352e"><circle cx="28" cy="15" r="1.5"/><circle cx="37" cy="19" r="1.5"/><circle cx="41" cy="28" r="1.5"/><circle cx="37" cy="37" r="1.5"/><circle cx="28" cy="41" r="1.5"/><circle cx="19" cy="37" r="1.5"/><circle cx="15" cy="28" r="1.5"/><circle cx="19" cy="19" r="1.5"/></g></svg>`,
  broccoli: `<svg viewBox="0 0 56 56" class="ill"><path d="M24 33h8v11a4 4 0 0 1-8 0z" fill="#bfe08a"/><g fill="#3f9e54"><circle cx="18" cy="25" r="9"/><circle cx="28" cy="18" r="10"/><circle cx="38" cy="25" r="9"/><circle cx="23" cy="30" r="8"/><circle cx="33" cy="30" r="8"/></g><g fill="#54b869"><circle cx="16" cy="22" r="3"/><circle cx="27" cy="15" r="3"/><circle cx="38" cy="22" r="3"/><circle cx="29" cy="27" r="3"/></g></svg>`,
  pineapple: `<svg viewBox="0 0 56 56" class="ill"><g fill="#3f9e54"><path d="M28 4c2 5 2 9 0 14-2-5-2-9 0-14z"/><path d="M28 10c4-3 8-3 11-1-2 5-7 6-11 1z"/><path d="M28 10c-4-3-8-3-11-1 2 5 7 6 11 1z"/></g><path d="M28 16c10 0 15 7 15 18s-5 18-15 18-15-7-15-18 5-18 15-18z" fill="#f5c33a"/><g stroke="#dca21f" stroke-width="1.6" stroke-linecap="round"><path d="M18 26l8 8M26 22l10 10M34 24l6 6M16 34l8 8M24 32l10 10M34 34l6 6"/></g></svg>`,
  plate: `<svg viewBox="0 0 56 56" class="ill"><ellipse cx="28" cy="34" rx="22" ry="9" fill="#dfe6ee"/><ellipse cx="28" cy="32" rx="22" ry="9" fill="#eef3f8"/><ellipse cx="28" cy="31" rx="14" ry="5.5" fill="#cfd8e3"/></svg>`,
};
function fruitSvg(id: string): string { return FRUIT_SVG[id] ?? ''; }

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
// 서빙 시작 게이트 — runner 가 접시/target 미검출 시 gate_waiting(미검출 라벨), 검출 시 gate_ready.
// 카메라 미리보기는 UI 에서 제거하고 runner 의 rerun 네이티브 창으로 대체.
const gateMissing = ref<string[]>([]);  // 미검출 라벨(접시/과일) — 배너 텍스트용
const gateMissingIds = ref<string[]>([]);  // 미검출 id (접시/과일) — 배너 SVG 표시용

// ── 로봇 마스코트 SVG (무드별 표정) — phase 에 따라 ──
type Mood = 'hi' | 'sleepy' | 'happy' | 'work' | 'party';
const mood = computed<Mood>(() => (({
  intro: 'hi', loading: 'sleepy', ready: 'happy', serving: 'work', done: 'party',
} as Record<string, Mood>)[phase.value] ?? 'happy'));
const _ROBOT_FACE: Record<Mood, string> = {
  hi: `<circle cx="26" cy="31" r="3" fill="#fff"/><circle cx="38" cy="31" r="3" fill="#fff"/><path d="M27 37q5 4 10 0" stroke="#fff" stroke-width="2.2" fill="none" stroke-linecap="round"/>`,
  sleepy: `<path d="M23 32q3 3 6 0" stroke="#fff" stroke-width="2.2" fill="none" stroke-linecap="round"/><path d="M35 32q3 3 6 0" stroke="#fff" stroke-width="2.2" fill="none" stroke-linecap="round"/><circle cx="32" cy="38" r="1.6" fill="#fff"/>`,
  happy: `<circle cx="26" cy="31" r="3" fill="#fff"/><circle cx="38" cy="31" r="3" fill="#fff"/><path d="M25 35q7 7 14 0" stroke="#fff" stroke-width="2.4" fill="none" stroke-linecap="round"/>`,
  work: `<rect x="23" y="30" width="6" height="3" rx="1.5" fill="#fff"/><rect x="35" y="30" width="6" height="3" rx="1.5" fill="#fff"/><rect x="29" y="37" width="6" height="2.4" rx="1.2" fill="#fff"/>`,
  party: `<path d="M23 33q3-5 6 0" stroke="#fff" stroke-width="2.2" fill="none" stroke-linecap="round"/><path d="M35 33q3-5 6 0" stroke="#fff" stroke-width="2.2" fill="none" stroke-linecap="round"/><path d="M26 36q6 7 12 0z" fill="#fff"/>`,
};
function robotSvg(m: Mood): string {
  return `<svg viewBox="0 0 64 64" class="ill"><line x1="32" y1="16" x2="32" y2="8" stroke="#3aa99b" stroke-width="3" stroke-linecap="round"/><circle cx="32" cy="6" r="4" fill="#ffd35c"/><rect x="8" y="30" width="6" height="13" rx="3" fill="#3aa99b"/><rect x="50" y="30" width="6" height="13" rx="3" fill="#3aa99b"/><rect x="12" y="15" width="40" height="35" rx="15" fill="#4ec6b8"/><rect x="14" y="17" width="36" height="31" rx="13" fill="#69dccd"/><rect x="18" y="23" width="28" height="19" rx="9.5" fill="#28323a"/><circle cx="17" cy="40" r="3.2" fill="#ff9aa8" opacity="0.75"/><circle cx="47" cy="40" r="3.2" fill="#ff9aa8" opacity="0.75"/>${_ROBOT_FACE[m]}</svg>`;
}

// 로봇 자막 — 멘트/안내를 화면 말풍선으로도 표시 (안 들릴 때 + 시각 피드백). 자동 사라짐.
const robotCaption = ref('');
let captionTimer: number | null = null;
function setCaption(text: string, ms = 5000): void {
  robotCaption.value = text;
  if (captionTimer !== null) window.clearTimeout(captionTimer);
  captionTimer = window.setTimeout(() => { robotCaption.value = ''; }, ms);
}

// 서빙 BGM — serving phase 동안 loop 재생. public/audio/storeplay_bgm.mp3 (사용자 제공).
// 멘트(서버 WebRTC TTS)는 BGM(브라우저 로컬 오디오)과 별개 스트림이라 BGM 음량이 크면
// 안내 음성(voiceClip) 재생 중이면 BGM 을 BGM_DUCK 으로 살짝 낮춰 배경만 깔리게. ducking 은
// voicePlaying 플래그 기준 — 옛 voice.state(TTS) 는 로컬 음성클립엔 안 바뀌어서 BGM 이 안 줄던 버그.
const BGM_VOLUME = 0.7;
const BGM_DUCK = 0.16;
const voicePlaying = ref(false);  // 안내 음성 클립 재생 중 여부
let bgm: HTMLAudioElement | null = null;
function applyBgmVolume(): void {
  if (bgm) bgm.volume = voicePlaying.value ? BGM_DUCK : BGM_VOLUME;
}
watch(voicePlaying, applyBgmVolume);  // 음성 시작/끝날 때 BGM 자동 ducking/복구
function startBgm(): void {
  if (!bgm) {
    bgm = new Audio('/audio/storeplay_bgm.mp3');
    bgm.loop = true;
  }
  applyBgmVolume();  // 이미 음성 재생 중이면 ducked 로 시작 (서빙 음성과 안 겹치게)
  void bgm.play().catch(() => { /* 음원 없거나 자동재생 차단 — 무시 */ });
}
function stopBgm(): void {
  // BGM(배경음악) 만 정지. 안내 음성(voiceClip)은 끄지 않음 — phase 가 'done' 으로 바뀌면
  // watch(phase) 가 stopBgm 을 부르는데, 그 직후 재생되는 엔딩 음성(voice_done)까지 죽이면 안 됨.
  if (bgm) {
    bgm.pause();
    bgm.currentTime = 0;
  }
}

// 벨 누름(종 침) 후 딜레이 뒤 "주문하신 ~ 나왔습니다" 음성. 종 효과음은 없음(불필요).
const ORDER_VOICE_DELAY_MS = 1500;  // 벨 감지(팔이 종에 접근)는 실제 종치기보다 빨라서, 더 뒤로
function playOrderVoiceDelayed(file: string): void {
  window.setTimeout(() => playVoice(file), ORDER_VOICE_DELAY_MS);
}

// 안내 음성 클립 — 사전 녹음 mp3 (TTS 대체, 인터넷 무관). 재생 동안 BGM ducking (voicePlaying watch).
let voiceClip: HTMLAudioElement | null = null;
function playVoice(file: string): void {
  if (voiceClip) voiceClip.pause();
  voiceClip = new Audio(`/audio/${file}`);
  const onEnd = (): void => { voicePlaying.value = false; };  // → watch 가 BGM 복구
  voiceClip.addEventListener('ended', onEnd);
  voicePlaying.value = true;       // → watch 가 BGM duck (bgm 아직 없어도 startBgm 이 반영)
  voiceClip.currentTime = 0;
  void voiceClip.play().catch(onEnd);  // 파일 없음/차단 시 복구
}
function announce(file: string, caption: string): void {  // 음성 클립 + 자막 (TTS 대체)
  playVoice(file);
  setCaption(caption);
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
  // 추론 준비중(trajectory 재생) 음성 — 3초 뒤에 틀어줌. 그 사이 ready 로 갔으면 스킵.
  window.setTimeout(() => {
    if (phase.value === 'loading') playVoice('voice_loading.mp3');
  }, 3000);
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
    announce('voice_greeting.mp3', '손님, 어떤 것을 드릴까요?');
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
    announce(`voice_serve_${item.id}.mp3`, `주문하신 ${item.label} 드릴게요!`);
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
      const payload = JSON.parse(ev.data) as {
        type: string; prompt?: string; what?: string; missing?: string[];
      };
      switch (payload.type) {
        case 'ready':
          // start 완료 — bootSession 에서 phase 처리하지만 보강.
          if (phase.value === 'loading') phase.value = 'ready';
          break;
        case 'task_started':
          // 클라이언트가 이미 'serving' 으로 갱신했지만 일관성 위해 보강.
          break;
        case 'bell_rung': {
          // 로봇이 종 친 시점 — 자막 즉시 + ~0.5초 뒤 "주문하신 {과일} 나왔습니다" 음성 (종효과음 없음).
          const id = selectedItem.value?.id;
          setCaption(`주문하신 ${selectedItem.value?.label ?? ''} 나왔습니다!`, 6000);
          if (id) playOrderVoiceDelayed(`voice_order_${id}.mp3`);
          break;
        }
        case 'gate_waiting': {
          // 접시/target 미검출 → robot 정지(hold) 중. UI 배너 + 음성 안내 (runner 가 변할 때만 emit).
          const ids = payload.missing ?? [];
          gateMissingIds.value = ids;  // SVG 표시용 (id 그대로)
          gateMissing.value = ids.map((c) =>
            c === 'plate' ? '접시' : (ITEMS.find((it) => it.id === c)?.label ?? c));
          const fruit = ids.find((c) => ITEMS.some((it) => it.id === c));
          if (fruit) {
            playVoice(`voice_missing_${fruit}.mp3`);          // 사전 녹음 "X가 없어요"
          } else if (ids.includes('plate')) {
            playVoice('voice_missing_plate.mp3');             // 사전 녹음 "접시가 없어요"
          }
          if (gateMissing.value.length) {
            setCaption(`${gateMissing.value.join(', ')}가 없어요. 놓아주세요`);
          }
          break;
        }
        case 'gate_ready':
          gateMissing.value = [];  // 접시+물건 검출 완료 → 배너 해제, 로봇 서빙 시작
          break;
        case 'gate_timeout':
          gateMissing.value = [];
          phase.value = 'ready';
          error.value = '접시랑 물건을 못 찾았어 — 다시 해줘';
          break;
        case 'task_done':
          // 홈 복귀 = 완료 → done 화면 + 엔딩 음성.
          phase.value = 'done';
          playVoice('voice_done.mp3');
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
    stopBgm();
    gateMissing.value = [];
    await endSession();
    phase.value = 'intro';
    selectedItem.value = null;
    error.value = null;
  }
  if (active && !prev) {
    voice.setSttHints(STT_FOOD_HINTS);  // 음식 단어 STT 힌트 주입 (짧은 발화 오인식 방지)
    phase.value = 'intro';
    playVoice('voice_intro.mp3');  // 가게놀이 진입 인트로 음성 (autoplay 차단 시 catch — 무시)
  }
}, { immediate: true });

// 서빙 중에만 BGM. 카메라 미리보기는 제거(runner rerun 창으로 대체).
watch(phase, (p) => {
  if (p === 'serving') {
    gateMissing.value = [];  // 새 서빙 시작 — 이전 게이트 배너 초기화
    startBgm();
  } else {
    stopBgm();
    gateMissing.value = [];
  }
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
  stopBgm();
  void endSession();
});
</script>

<template>
  <Teleport to="body">
    <Transition name="sp-fade">
      <div v-if="isActive" class="sp-overlay" :data-phase="phase">
        <div class="card" :class="{ wide: phase === 'ready' || phase === 'serving', done: phase === 'done' }">
          <!-- 과일 좌판 차양 -->
          <div class="awning"><div class="scallops"><i v-for="n in 9" :key="n" /></div></div>

          <!-- intro — 환영 + 규칙 -->
          <div v-if="phase === 'intro'" class="phase">
            <div class="mascot floaty" v-html="robotSvg(mood)" />
            <h1 class="title">노리 과일가게</h1>
            <ul class="rules">
              <li><span class="rule-no">1</span><span class="rule-tx">먹고 싶은 과일을 누르거나 <b>“딸기 줘”</b> 라고 말해요</span></li>
              <li><span class="rule-no">2</span><span class="rule-tx">로봇이 과일을 골라서 가져다 줘요</span></li>
              <li><span class="rule-no">3</span><span class="rule-tx"><b>종이 울리면</b> 과일을 받아가세요!</span></li>
            </ul>
            <button class="primary big" @click="bootSession">시작하기</button>
            <button class="ghost" @click="exitToIdle">취소</button>
          </div>

          <!-- loading — 깨어나는 중 -->
          <div v-else-if="phase === 'loading'" class="phase">
            <div class="mascot wake" v-html="robotSvg(mood)" />
            <h2 class="title">로봇이 깨어나고 있어요</h2>
            <p class="big-hint">조금만 기다려 줘!</p>
            <div class="dots big"><i /><i /><i /></div>
          </div>

          <!-- ready — 과일 고르기 -->
          <div v-else-if="phase === 'ready'" class="phase">
            <div class="head"><span class="mascot sm bob" v-html="robotSvg(mood)" /><h2 class="title">어떤 거 줄까?</h2></div>
            <p v-if="robotCaption" class="caption">{{ robotCaption }}</p>
            <div class="item-grid">
              <button v-for="item in ITEMS" :key="item.id" class="item-btn" @click="serveItem(item)">
                <span class="fruit" v-html="fruitSvg(item.id)" />
                <span class="item-label">{{ item.label }}</span>
              </button>
            </div>
            <p class="voice-hint">
              <svg class="mic" viewBox="0 0 24 24"><rect x="9" y="3.5" width="6" height="10.5" rx="3" fill="currentColor"/><path d="M6 11a6 6 0 0 0 12 0" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><line x1="12" y1="17" x2="12" y2="20.5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
              <span>“딸기 줘” 라고 말해도 돼요!</span>
            </p>
            <button class="ghost" @click="exitToIdle">끝내기</button>
          </div>

          <!-- serving — 게이트 대기 / 준비 중 -->
          <div v-else-if="phase === 'serving'" class="phase">
            <template v-if="gateMissing.length">
              <div class="gate-ills">
                <span v-for="mid in gateMissingIds" :key="mid" class="fruit gate-ill" v-html="fruitSvg(mid)" />
              </div>
              <div class="gate-banner">
                <p class="gate-title">{{ gateMissing.join(', ') }}가 없어요!</p>
                <p class="gate-sub">{{ gateMissing.join(', ') }}를 놓아주세요. 놓을 때까지 기다릴게요</p>
              </div>
            </template>
            <template v-else>
              <div class="serve-stage">
                <span class="mascot sm bob" v-html="robotSvg(mood)" />
                <span class="fruit big-fruit bounce" v-html="fruitSvg(selectedItem?.id ?? '')" />
              </div>
              <h2 class="title">{{ selectedItem?.label }} 준비 중!</h2>
              <p v-if="robotCaption" class="caption">{{ robotCaption }}</p>
              <div class="dots"><i /><i /><i /></div>
            </template>
            <button class="ghost" @click="abortServe">그만</button>
          </div>

          <!-- done — 완료 축하 -->
          <div v-else-if="phase === 'done'" class="phase">
            <div class="confetti"><i v-for="n in 14" :key="n" :style="{ '--i': n }" /></div>
            <div class="serve-stage">
              <span class="fruit big-fruit pop" v-html="fruitSvg(selectedItem?.id ?? '')" />
              <span class="mascot sm bob" v-html="robotSvg(mood)" />
            </div>
            <h2 class="title">다 됐어요!</h2>
            <p class="big-hint">{{ selectedItem?.label }} 받아봐!</p>
            <button class="primary big" @click="phase = 'ready'">또 하기</button>
            <button class="ghost" @click="exitToIdle">끝내기</button>
          </div>

          <div v-if="error" class="error">{{ error }}</div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.sp-overlay {
  position: fixed; inset: 0; z-index: 50;
  display: flex; align-items: center; justify-content: center;
  background: radial-gradient(120% 120% at 50% 0%, rgba(60,34,28,0.42), rgba(28,16,20,0.62));
}
/* ─── 과일 좌판 카드 ─── */
.card {
  position: relative; box-sizing: border-box;
  width: 380px; max-width: 92vw;
  background: linear-gradient(180deg, #fff9ef 0%, #fff1df 100%);
  padding: 60px 28px 26px;            /* 상단은 차양(awning) 공간 */
  border-radius: 30px;
  text-align: center;
  box-shadow: 0 22px 60px rgba(60, 32, 24, 0.34);
  font-family: 'Jua', 'Apple SD Gothic Neo', 'Malgun Gothic', system-ui, sans-serif;
  word-break: keep-all; overflow-wrap: break-word; line-height: 1.5;
}
.card.wide { width: 432px; }
.card.done { overflow: hidden; }
.phase { display: flex; flex-direction: column; align-items: center; gap: 15px; }

/* 차양 (스트라이프 + 스캘럽) */
.awning {
  position: absolute; top: 0; left: 0; right: 0; height: 30px;
  border-radius: 30px 30px 0 0;
  background: repeating-linear-gradient(90deg, #e3573e 0 26px, #fff4e6 26px 52px);
  box-shadow: inset 0 -3px 6px rgba(0,0,0,0.06);
}
.scallops { position: absolute; left: 0; right: 0; top: 30px; height: 15px; display: flex; }
.scallops i { flex: 1; border-radius: 0 0 60% 60%; }
.scallops i:nth-child(odd) { background: #e3573e; }
.scallops i:nth-child(even) { background: #fff4e6; }

.title { margin: 0; font-size: 1.85rem; font-weight: 800; color: #d8503a; letter-spacing: -0.5px; }
h1.title { font-size: 2.25rem; }
.big-hint { margin: 0; font-size: 1.1rem; color: #8a6e5a; }
.head { display: flex; align-items: center; gap: 10px; justify-content: center; }

/* 로봇 마스코트 (인라인 SVG, v-html → :deep 로 사이즈) */
.mascot { width: 96px; height: 96px; }
.mascot.sm { width: 56px; height: 56px; }
.mascot :deep(svg) { width: 100%; height: 100%; display: block; }
.floaty { animation: floaty 2.8s ease-in-out infinite; }
.wake { animation: wake 1.2s ease-in-out infinite; }
.bob { animation: bob 1.7s ease-in-out infinite; }

/* 과일 일러스트 */
.fruit { width: 56px; height: 56px; display: block; }
.fruit :deep(svg) { width: 100%; height: 100%; display: block; }
.big-fruit { width: 90px; height: 90px; }
.bounce { animation: bounce 0.95s ease-in-out infinite; }
.pop { animation: pop 0.5s cubic-bezier(.2,1.5,.4,1) both; }

/* 게임 규칙 — 번호 뱃지 */
.rules {
  list-style: none; margin: 2px 0; padding: 16px 18px; width: 100%;
  box-sizing: border-box; text-align: left;
  background: #fffdf6; border: 2px solid #f1dcb8; border-radius: 20px;
  display: flex; flex-direction: column; gap: 13px;
}
.rules li { display: flex; align-items: flex-start; gap: 11px; }
.rule-no {
  flex: none; width: 24px; height: 24px; margin-top: 1px; border-radius: 50%;
  background: #e3573e; color: #fff; font-size: 0.85rem; font-weight: 800;
  display: flex; align-items: center; justify-content: center;
}
.rule-tx { font-size: 1.02rem; color: #5f5044; line-height: 1.45; }
.rules b { color: #d8503a; font-weight: 800; }

/* 자막 말풍선 */
.caption {
  margin: 0; box-sizing: border-box; max-width: 100%;
  background: #fff; border: 2px solid #ffd9c2; border-radius: 16px;
  padding: 10px 16px; font-size: 1.05rem; font-weight: 700; color: #d8503a;
}

/* 과일 고르기 그리드 */
.item-grid { display: flex; flex-wrap: wrap; justify-content: center; gap: 12px; width: 100%; }
.item-btn {
  width: 102px; box-sizing: border-box;
  display: flex; flex-direction: column; align-items: center; gap: 6px;
  padding: 13px 6px 11px;
  background: #fff; border: 2px solid #f1ddc2; border-radius: 20px;
  cursor: pointer; box-shadow: 0 4px 0 #ecceA3;
  transition: transform 0.12s, box-shadow 0.12s, background 0.12s, border-color 0.12s;
}
.item-btn:hover { background: #fffaf1; transform: translateY(-3px); border-color: #e3573e; }
.item-btn:active { transform: translateY(2px); box-shadow: 0 1px 0 #ecceA3; }
.item-label { font-size: 1.05rem; font-weight: 800; color: #6b5141; }

/* 음성 힌트 */
.voice-hint {
  margin: 2px 0 0; display: inline-flex; align-items: center; gap: 7px;
  font-size: 0.96rem; color: #2f9e6e; font-weight: 700;
  background: #eaf7ee; border-radius: 999px; padding: 8px 16px;
}
.mic { width: 17px; height: 17px; color: #2f9e6e; flex: none; }

/* 서빙 무대 (로봇 + 과일) */
.serve-stage { display: flex; align-items: center; justify-content: center; gap: 6px; }

/* 점 3개 (로딩/서빙) */
.dots { display: inline-flex; gap: 6px; }
.dots i { width: 9px; height: 9px; border-radius: 50%; background: #e98a6f; animation: dot 1.2s infinite; }
.dots.big i { width: 12px; height: 12px; }
.dots i:nth-child(2) { animation-delay: 0.2s; }
.dots i:nth-child(3) { animation-delay: 0.4s; }

/* 게이트 (접시/물건 없음) */
.gate-ills { display: flex; gap: 8px; align-items: center; justify-content: center; }
.gate-ill { width: 60px; height: 60px; animation: bob 1.5s ease-in-out infinite; }
.gate-banner {
  width: 100%; box-sizing: border-box;
  background: #fff6dd; border: 2px dashed #f0b93b; border-radius: 20px; padding: 14px 18px;
}
.gate-title { margin: 0 0 5px; font-size: 1.2rem; font-weight: 800; color: #c5851a; }
.gate-sub { margin: 0; font-size: 0.95rem; color: #997a3a; line-height: 1.4; }

/* 완료 컨페티 */
.confetti { position: absolute; inset: 0; pointer-events: none; }
.confetti i {
  position: absolute; top: -12%; left: calc(var(--i) * 7%);
  width: 9px; height: 15px; border-radius: 2px;
  background: hsl(calc(var(--i) * 47), 88%, 62%);
  animation: confetti-fall 1.7s ease-in calc(var(--i) * 0.07s) infinite;
}

/* 버튼 */
.primary {
  padding: 13px 36px; font-size: 1.18rem; font-weight: 800;
  background: #e3573e; color: #fff; border: none; border-radius: 18px;
  cursor: pointer; box-shadow: 0 5px 0 #b8402c; transition: transform 0.12s, box-shadow 0.12s, filter 0.12s;
}
.primary.big { font-size: 1.35rem; padding: 15px 46px; }
.primary:hover { filter: brightness(1.04); }
.primary:active { transform: translateY(4px); box-shadow: 0 1px 0 #b8402c; }
.ghost {
  padding: 9px 20px; background: transparent; border: 2px solid #e6d6c4;
  border-radius: 16px; color: #9a8270; font-weight: 700; cursor: pointer;
}
.ghost:hover { background: #fdf6ec; }
.error { color: #dc2626; margin-top: 6px; font-weight: 700; }

@keyframes floaty { 0%,100%{transform:translateY(0)} 50%{transform:translateY(-9px)} }
@keyframes wake { 0%,100%{transform:rotate(-5deg)} 50%{transform:rotate(5deg) scale(1.04)} }
@keyframes bob { 0%,100%{transform:translateY(0)} 50%{transform:translateY(-6px)} }
@keyframes bounce { 0%,100%{transform:translateY(0) scale(1)} 50%{transform:translateY(-16px) scale(1.05)} }
@keyframes pop { 0%{transform:scale(0)} 100%{transform:scale(1)} }
@keyframes dot { 0%,100%{transform:translateY(0);opacity:0.45} 50%{transform:translateY(-6px);opacity:1} }
@keyframes confetti-fall {
  0% { transform: translateY(-12%) rotate(0); opacity: 1; }
  100% { transform: translateY(400px) rotate(560deg); opacity: 0; }
}
.sp-fade-enter-active, .sp-fade-leave-active { transition: opacity 0.3s; }
.sp-fade-enter-from, .sp-fade-leave-to { opacity: 0; }
</style>
