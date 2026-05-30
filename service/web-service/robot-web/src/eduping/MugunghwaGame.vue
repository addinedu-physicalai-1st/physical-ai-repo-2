<script setup lang="ts">
/**
 * 무궁화꽃이 피었습니다 (SR-PLAY-004) — EduPing 동명 모드 진입 시 표시.
 *
 * 레이아웃:
 *   - 상단 바: [☰ 메뉴]  [현재 단계 + helper]  [카메라 PIP]  [× 닫기]
 *   - 메인  : OpenarmViewer (전체) + 노래 단계 동안 tempo HUD/progress 오버레이
 *   - 하단  : 참가자 스트립 (DB 명단 전체) + alive/eliminated 카운트
 *   - 드로어: ☰ 클릭 → 좌측 슬라이드. 단계 타임라인 + (DEV) 단계 전환 / 탈락 토글
 *
 * 본 컴포넌트는 단계 머신의 UI 만 구현. face/pose/track_id 파이프라인이 붙기 전까지는
 * dev 패널 (import.meta.env.DEV) 으로 단계 전환·탈락을 수동 트리거. 노래 단계는
 * 가상 타이머 + 선택 가능한 tempo 패턴 + 선택적 mp3 재생.
 */
import { computed, inject, onMounted, onUnmounted, ref, watch } from 'vue';
import type { EmotionId } from '@/config/robots';
import { useModeStore } from '@/stores/mode';
import { useVoiceStore } from '@/stores/voice';
import { useModeIntents } from '@/composables/useModeIntents';
import { VOICE_CONTROLLER_KEY } from '@/composables/voiceControllerKey';
import { useEmotionCapture } from '@/composables/useEmotionCapture';
import { useEdupingStateWs } from '@/composables/useEdupingStateWs';
import { useProximityOverride } from '@/composables/useProximityOverride';
import { useMugunghwaPerception } from './useMugunghwaPerception';
import OpenarmViewer from './OpenarmViewer.vue';
import type { JointSnapshot as StreamJointSnapshot } from './useDanceStream';

type Stage = 'entry' | 'ready' | 'song' | 'observation' | 'eliminationWait' | 'end';

interface StageMeta {
  emotion: EmotionId;
  label: string;
  helper: string;
  accent: string; // 상단 단계 인디케이터 + 참가자 프레임 색
}

const STAGE_META: Record<Stage, StageMeta> = {
  entry:           { emotion: 'hello',    label: '참가자 확인', helper: '카메라 앞에 모인 친구들을 확인하고 있어요.',  accent: '#ec4899' },
  ready:           { emotion: 'basic',    label: '준비',        helper: '모두 출발선 뒤로 멀리 가서 서주세요!',          accent: '#0ea5e9' },
  song:            { emotion: 'fun',      label: '노래',        helper: '무궁화꽃이 피었습니다 — 마음껏 움직여요!',      accent: '#f59e0b' },
  observation:     { emotion: 'interest', label: '관찰',        helper: '지금은 움직이면 안 돼요! 가만히 멈춰요.',        accent: '#dc2626' },
  eliminationWait: { emotion: 'sad',      label: '탈락 대기',   helper: '탈락한 친구가 시야 밖으로 나갈 때까지 기다려요.', accent: '#7c3aed' },
  end:             { emotion: 'happy',    label: '놀이 끝!',    helper: '재미있게 잘 놀았어요. 다음에 또 만나요!',        accent: '#16a34a' },
};

const STAGES: Stage[] = ['entry', 'ready', 'song', 'observation', 'eliminationWait', 'end'];

interface ChildRoster { id: number; name: string; photo_url?: string | null }
interface Participant {
  id: number;
  name: string;
  /** 진입 단계에서 카메라가 얼굴을 매칭한 순간 true. 미등록은 회색 대기 프레임. */
  registered: boolean;
  /** 관찰 단계에서 움직임이 임계 초과한 경우 true. 빨간 X 프레임. */
  eliminated: boolean;
  /** 교사가 카드를 터치 → 골인 처리. 금색 트로피 프레임. */
  reached: boolean;
  /** 도착한 순서 (1, 2, 3...). 도착 토글 해제 시 null. */
  place: number | null;
  /** 등록된 얼굴 사진 (/api/face-images/...). 없으면 이니셜 표시. */
  faceUrl?: string;
}

const DEVICE_TOKEN = import.meta.env.VITE_ROBOT_TOKEN ?? 'dev-robot-token-change-me';

const mode = useModeStore();
const voice = useVoiceStore();
const voiceController = inject(VOICE_CONTROLLER_KEY);

// 게임 종료 확인 popup — useModeIntents.onModeExit 가 voiceController.startConfirm
// 으로 confirm 사이클 시작. voice.confirm 이 set 되어 있으면 popup 표시.
// confirm_yes/no intent 가 도착하면 useVoiceController 가 stored callback 실행.
const showExitConfirm = computed(() => voice.confirm !== null);

function onConfirmExitClick(): void {
  const c = voice.confirm;
  voice.clearConfirm();
  if (c) void c.onConfirm();
}
function onCancelExitClick(): void {
  const c = voice.confirm;
  voice.clearConfirm();
  if (c) void c.onCancel();
}

useModeIntents('무궁화꽃이 피었습니다', {
  onModeExit: () => {
    // end (놀이 끝) 단계에선 이미 게임 종료 — 추가 confirm 없이 바로 대기.
    if (stage.value === 'end') {
      mode.setMode('대기');
      return;
    }
    voiceController?.startConfirm({
      context: 'game_exit',
      prompt: '게임을 그만할까요?',
      onConfirm: () => mode.setMode('대기'),
      onCancel: () => voiceController?.speak('알겠어요. 계속할게요.'),
    });
  },
  onStart: () => {
    // entry: 참가자 등록 → ready (준비).
    // ready: 준비 단계 건너뛰기 → song (곡 시작).
    // end: 놀이 끝 popup → '다시하기' → 참가자 초기화 후 entry 로 복귀.
    // 그 외 stage (song / observation / eliminationWait) 는 음성 진행점 정의 안 됨.
    if (stage.value === 'entry') {
      startEntryGame();
    } else if (stage.value === 'ready') {
      setStage('song');
    } else if (stage.value === 'end') {
      restartGame();
    }
  },
});
const tts = {
  speak: (text: string) => { voiceController?.speak(text); return Promise.resolve(); },
  cancel: () => { voiceController?.cancelSpeak(); },
};

// ---- touchdown 사운드 (Web Audio API 합성, 외부 asset 없음) ------------------
let audioContext: AudioContext | null = null;
function playTouchdownSound(): void {
  try {
    if (!audioContext) audioContext = new AudioContext();
    if (audioContext.state === 'suspended') void audioContext.resume();
    const ctx = audioContext;
    const now = ctx.currentTime;
    // 두 음 chime — C5 → G5 (위로 올라가는 fanfare 느낌)
    [523.25, 783.99].forEach((freq, i) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.value = freq;
      osc.connect(gain).connect(ctx.destination);
      const t0 = now + i * 0.10;
      gain.gain.setValueAtTime(0, t0);
      gain.gain.linearRampToValueAtTime(0.35, t0 + 0.015);
      gain.gain.exponentialRampToValueAtTime(0.001, t0 + 0.40);
      osc.start(t0);
      osc.stop(t0 + 0.42);
    });
  } catch { /* AudioContext 차단된 환경에서는 silent fail */ }
}

// ---- toast (등록 성공 알림 등) -----------------------------------------------
interface Toast { id: number; text: string; faceUrl?: string }
const toasts = ref<Toast[]>([]);
let toastSeq = 0;
function pushToast(text: string, faceUrl?: string, durationMs = 3500): void {
  const id = ++toastSeq;
  toasts.value.push({ id, text, faceUrl });
  window.setTimeout(() => {
    toasts.value = toasts.value.filter((t) => t.id !== id);
  }, durationMs);
}

const stage = ref<Stage>('entry');
const meta = computed(() => STAGE_META[stage.value]);

const participants = ref<Participant[]>([]);
const rosterError = ref<string>('');

async function loadRoster(): Promise<void> {
  try {
    const res = await fetch('/api/children/roster', {
      headers: { 'X-Device-Token': DEVICE_TOKEN },
    });
    if (!res.ok) {
      rosterError.value = `명단을 불러오지 못했어요 (HTTP ${res.status})`;
      return;
    }
    const roster = (await res.json()) as ChildRoster[];
    participants.value = roster.map((c) => ({
      id: c.id,
      name: c.name,
      registered: false,
      eliminated: false,
      reached: false,
      place: null,
      faceUrl: c.photo_url ?? undefined,
    }));
    if (participants.value.length === 0) {
      rosterError.value = '등록된 어린이가 없어요. 포털에서 먼저 등록해주세요.';
    }
  } catch (e) {
    rosterError.value = `명단을 불러오지 못했어요: ${(e as Error).message}`;
  }
}

// 진입 단계에선 전체 명단 보여줘 등록 진행을 시각화. 이후는 등록된 친구만 게임 참가자.
const visibleParticipants = computed(() =>
  stage.value === 'entry'
    ? participants.value
    : participants.value.filter((p) => p.registered),
);
// 노래 단계 URDF 오버레이용 — 아직 살아있는 (탈락 X) 등록 아이만 터치 타겟.
const aliveTouchTargets = computed(() =>
  participants.value.filter((p) => p.registered && !p.eliminated),
);
const registeredCount = computed(() => participants.value.filter((p) => p.registered).length);
const aliveCount = computed(
  () => participants.value.filter((p) => p.registered && !p.eliminated && !p.reached).length,
);
const eliminatedCount = computed(
  () => participants.value.filter((p) => p.registered && p.eliminated).length,
);
const reachedCount = computed(
  () => participants.value.filter((p) => p.registered && p.reached).length,
);

// ---- 가리기 모션 (registration 으로 녹화된 양팔 모션) -----------------------------
// 노래 단계: 정방향 (가리기) — audio progress (audio.currentTime / duration) 에 lock 된
//   motion progress 로 keyframe 보간. 노래의 slow_to_fast 패턴이면 audio 가 느릴 때
//   motion 도 느려지고, 빨라질 때 같이 빨라짐 — playbackRate 가 audio 와 motion 양쪽에
//   동일 적용된 효과.
// 관찰 단계: 역재생 (떼기) — observationRemainingMs / dur 비율로 motion 시간을 거꾸로.
// 다른 단계에서는 externalSnapshot=null 로 두어 follower WS 채널이 viewer 를 그리게 한다.
interface MotionKeyframe { t: number; pos: number[] }
interface MotionData {
  duration_s: number;
  sample_hz: number;
  joint_names: string[];
  keyframes: MotionKeyframe[];
}
const motion = ref<MotionData | null>(null);
const armSnapshot = ref<StreamJointSnapshot | null>(null);

// 게임 시작 (entry/ready) 시 양팔을 자연 하강 자세 (모든 joint = 0) 로 강제. follower WS
// 가 직전 세션의 잔존 pose (가리기 자세 등) 를 들고 있어도 viewer 가 거기에 끌려가지
// 않도록 — 사용자가 명시적으로 "처음에는 이 [하강] 자세" 라고 요청.
const REST_JOINT_NAMES: readonly string[] = [
  'openarm_right_joint1', 'openarm_right_joint2', 'openarm_right_joint3', 'openarm_right_joint4',
  'openarm_right_joint5', 'openarm_right_joint6', 'openarm_right_joint7', 'openarm_right_finger_joint1',
  'openarm_left_joint1', 'openarm_left_joint2', 'openarm_left_joint3', 'openarm_left_joint4',
  'openarm_left_joint5', 'openarm_left_joint6', 'openarm_left_joint7', 'openarm_left_finger_joint1',
];
function makeRestSnapshot(): StreamJointSnapshot {
  return {
    jointNames: [...REST_JOINT_NAMES],
    positions: new Float32Array(REST_JOINT_NAMES.length),  // all zeros
    tMs: 0,
  };
}

async function loadMotion(): Promise<void> {
  try {
    const res = await fetch('/api/eduping/mugunghwa/motion/data');
    if (!res.ok) return;
    motion.value = (await res.json()) as MotionData;
  } catch {
    /* motion 없이도 게임은 동작 — 외부 snapshot 없으면 viewer 가 follower WS 폴백 */
  }
}

function interpolateMotion(t: number): StreamJointSnapshot | null {
  const m = motion.value;
  if (!m || m.keyframes.length === 0) return null;
  const tt = Math.max(0, Math.min(m.duration_s, t));
  const kfs = m.keyframes;
  // 선형 탐색 (1~2K keyframe 정도면 충분히 빠름; 필요시 binary search 로 교체)
  let i = 0;
  while (i < kfs.length - 1 && kfs[i + 1].t <= tt) i++;
  const a = kfs[i];
  const b = kfs[Math.min(i + 1, kfs.length - 1)];
  const span = b.t - a.t;
  const r = span > 0 ? (tt - a.t) / span : 0;
  const positions = new Float32Array(a.pos.length);
  for (let k = 0; k < a.pos.length; k++) positions[k] = a.pos[k] + (b.pos[k] - a.pos[k]) * r;
  return { jointNames: m.joint_names, positions, tMs: tt * 1000 };
}

// ---- 노래 stage: 고정 속도 + 실 오디오 진행 추적 -----------------------------
// `yeonghui_mugunghwa.mp3` (자연 속도 ~4.6s) 가 진행률의 단일 진실의 원천.
// 속도는 고정(자연 속도 1.0×) — sim 모션·오디오·실물 팔 play 가 모두 같은 속도라 별도
// 동기 로직 불필요. (이전엔 quintic/random 동적 템포였으나 실물 팔과 sim 동기 단순화 위해 고정.)
const TICK_MS = 80;
const SONG_AUDIO_URL = '/sounds/yeonghui_mugunghwa.mp3';

const songProgressRatio = ref(0);  // audio.currentTime / audio.duration, live updated
const songProgressPct = computed(() => Math.min(100, songProgressRatio.value * 100));

let songTimer: number | null = null;        // 음악 진행률 timer
let coverTimer: number | null = null;        // 가리기 애니메이션 timer (sim)
let coverStartTimer: number | null = null;   // 가리기 완료 → 음악 시작 짧은 텀
let songAudio: HTMLAudioElement | null = null;

const COVER_HOLD_BUFFER_MS = 250;   // 가리기 끝나고 음악 시작 전 짧은 텀
const COVER_FALLBACK_S = 2.5;       // motion 미로딩 시 가리기 추정 시간

function ensureSongAudio(): HTMLAudioElement {
  if (songAudio) return songAudio;
  const a = new Audio(SONG_AUDIO_URL);
  a.preload = 'auto';
  songAudio = a;
  return a;
}

// 실물 팔 — song(가리기 forward) / observation(떼기 reverse) 시 녹화된 mugunghwa 모션을
// follower 로 재생. realActive 일 때만 — sim 은 realActive 면 패널이 숨겨지므로 불필요.
// speed=1.0(자연 속도) 고정 — 실물 안전상 자연 속도 110% 를 넘기지 않는다.
async function playArmMotion(reverse: boolean): Promise<void> {
  if (!stateWs.realActive.value) return;
  try {
    await fetch('/api/eduping/mugunghwa/motion/play', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target: 'real', speed: 1.0, reverse }),
    });
  } catch { /* 실물 재생 실패는 게임 진행을 막지 않음 */ }
}

// 게임 종료/나가기 시 양팔을 부드럽게 home pose 로 복귀 (율동 정지와 동일 메커니즘 —
// trapezoidal velocity profile). 가리기 자세로 멈춰 끝나도 제자리로 돌아온다.
async function returnArmHome(): Promise<void> {
  if (!stateWs.realActive.value) return;
  try {
    await fetch('/api/eduping/arm/return-home', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target: 'real' }),
    });
  } catch { /* noop */ }
}

// 새 흐름: 1) 가리기 동작이 끝나면 → 2) 음악 재생 (팔은 가리기 자세로 정지 유지,
// 음악 중에만 이동 허용) → 3) 음악 종료 → 관찰(떼기 + 프리즈, 움직이면 탈락).
function startSongStage(): void {
  stopSongStage();
  songProgressRatio.value = 0;
  armSnapshot.value = interpolateMotion(0);  // 팔 내림 자세에서 시작
  // 1) 가리기 — 실물 forward play + sim 1회 보간 (coverDur 동안 0→full).
  void playArmMotion(false);
  const coverDur = motion.value?.duration_s ?? COVER_FALLBACK_S;
  const startAt = performance.now();
  coverTimer = window.setInterval(() => {
    const elapsed = (performance.now() - startAt) / 1000;
    const p = coverDur > 0 ? Math.min(1, elapsed / coverDur) : 1;
    if (motion.value) armSnapshot.value = interpolateMotion(coverDur * p);
    if (p >= 1) {
      if (coverTimer !== null) { window.clearInterval(coverTimer); coverTimer = null; }
      if (motion.value) armSnapshot.value = interpolateMotion(coverDur);  // 가리기 자세 유지
      // 2) 가리기 완료 → 짧은 텀 후 음악 재생.
      coverStartTimer = window.setTimeout(() => {
        coverStartTimer = null;
        if (stage.value === 'song') startMusicPhase();
      }, COVER_HOLD_BUFFER_MS);
    }
  }, TICK_MS);
}

function startMusicPhase(): void {
  const audio = ensureSongAudio();
  try { audio.pause(); } catch { /* noop */ }
  try { audio.currentTime = 0; } catch { /* noop */ }
  audio.playbackRate = 1.0;  // 고정 속도
  audio.onended = () => {
    // 3) 음악 종료 → 관찰(떼기 + 프리즈). 음악 중에만 이동 허용, 이후 움직이면 탈락.
    if (stage.value === 'song') setStage('observation');
  };
  const pr = audio.play();
  if (pr && typeof pr.catch === 'function') {
    pr.catch((err: unknown) => {
      const name = (err as { name?: string } | null)?.name;
      if (name === 'AbortError' || name === 'NotAllowedError') return;
      console.warn('[mugunghwa-song] play failed', err);
    });
  }
  // 음악 진행률 (progress bar) 만 갱신. 팔은 가리기 자세로 정지 유지 (armSnapshot update 안 함).
  songTimer = window.setInterval(() => {
    const dur = audio.duration;
    if (Number.isFinite(dur) && dur > 0) {
      songProgressRatio.value = Math.min(1, audio.currentTime / dur);
    }
  }, TICK_MS);
}

function stopSongStage(): void {
  for (const t of [songTimer, coverTimer]) {
    if (t !== null) window.clearInterval(t);
  }
  songTimer = null;
  coverTimer = null;
  if (coverStartTimer !== null) {
    window.clearTimeout(coverStartTimer);
    coverStartTimer = null;
  }
  if (songAudio) {
    songAudio.onended = null;
    try { songAudio.pause(); } catch { /* noop */ }
    try { songAudio.currentTime = 0; } catch { /* noop */ }
  }
  songProgressRatio.value = 0;
}

// 참가자(등록된 어린이)가 한 명도 없으면 게임 시작 불가 — entry 에 머물며 안내.
function startEntryGame(): void {
  if (registeredCount.value === 0) {
    pushToast('참가자를 먼저 등록해주세요 — 카메라 앞에 친구가 인식되어야 시작할 수 있어요');
    return;
  }
  setStage('ready');
}

// ---- stage transitions ------------------------------------------------------
function setStage(next: Stage): void {
  stage.value = next;
  mode.currentEmotion = STAGE_META[next].emotion;
  if (next === 'song') startSongStage();
  else stopSongStage();
}

function toggleRegistered(id: number): void {
  const p = participants.value.find((x) => x.id === id);
  if (!p) return;
  p.registered = !p.registered;
  // 등록 해제 시 다른 플래그도 같이 풀어준다 — 등록 안 된 아이는 게임 밖.
  if (!p.registered) {
    p.eliminated = false;
    p.reached = false;
    p.place = null;
    densifyPlaces();
  }
}

function toggleEliminated(id: number): void {
  const p = participants.value.find((x) => x.id === id);
  if (!p) return;
  // 미등록은 탈락 토글 무시 — 게임에 참여하고 있어야 탈락도 가능.
  if (!p.registered) return;
  p.eliminated = !p.eliminated;
  if (p.eliminated) {
    p.reached = false;
    p.place = null;
    densifyPlaces();
  }
}

// 도착한 아이들의 place 번호를 1..N 으로 빽빽하게 재배열 (도착 순서 기준 유지).
function densifyPlaces(): void {
  const placed = participants.value
    .filter((x) => x.reached && x.place != null)
    .sort((a, b) => (a.place ?? 0) - (b.place ?? 0));
  placed.forEach((p, idx) => { p.place = idx + 1; });
}

// 카드 터치 → 골인 토글 (등록 + 탈락 아닌 아이만 가능)
function toggleReached(id: number): void {
  const p = participants.value.find((x) => x.id === id);
  if (!p || !p.registered || p.eliminated) return;
  if (p.reached) {
    p.reached = false;
    p.place = null;
    densifyPlaces();
  } else {
    p.reached = true;
    const maxPlace = participants.value.reduce(
      (m, x) => Math.max(m, x.place ?? 0),
      0,
    );
    p.place = maxPlace + 1;
    playTouchdownSound();
    void tts.speak(`${p.name} ${p.place}등`).catch(() => { /* noop */ });
  }
}

const KOREAN_PLACE_SUFFIX = '등';
function placeLabel(p: Participant): string | null {
  if (p.place == null) return null;
  return `${p.place}${KOREAN_PLACE_SUFFIX}`;
}
function placeRank(p: Participant): string {
  if (p.place == null) return '';
  if (p.place === 1) return 'gold';
  if (p.place === 2) return 'silver';
  if (p.place === 3) return 'bronze';
  return 'rank-n';
}
function placeEmoji(p: Participant): string {
  if (p.place == null) return '';
  if (p.place === 1) return '🥇';
  if (p.place === 2) return '🥈';
  if (p.place === 3) return '🥉';
  return '🏅';
}

function close(): void {
  mode.setMode('대기');
}

// 종료 화면 정렬 — 도착한 아이 (place asc) → 아직 둘 다 아님 (생존) → 탈락
const sortedResults = computed(() => {
  const all = participants.value.filter((p) => p.registered);
  const reached = all
    .filter((p) => p.reached)
    .sort((a, b) => (a.place ?? 9999) - (b.place ?? 9999));
  const survivors = all.filter((p) => !p.reached && !p.eliminated);
  const eliminated = all.filter((p) => p.eliminated);
  return [...reached, ...survivors, ...eliminated];
});

function restartGame(): void {
  for (const p of participants.value) {
    p.registered = false;
    p.eliminated = false;
    p.reached = false;
    p.place = null;
  }
  perception.reset();  // 노드 bindings 초기화 — 새 게임에서 다시 바인딩 (end 에서 idle 였음)
  setStage('entry');
}

// 게임 종료 조건: (1) 1명이라도 도달 → onPhysicalReach 가 setStage('end'). (2) 전원 탈락
// (등록자 전원 eliminated) → 아래 watcher. 부분 탈락(일부만)으론 안 끝남 — 나머지는 계속.
// (이전엔 alive===0 으로 "도달자 포함" 이라, 등록자가 적으면 한 명 탈락에 끝나버렸음.)
watch([eliminatedCount, registeredCount], ([elim, reg]) => {
  if (
    reg > 0 && elim === reg
    && stage.value !== 'end'
    && stage.value !== 'entry'
    && stage.value !== 'ready'
  ) {
    setStage('end');
  }
});

// ---- hamburger drawer -------------------------------------------------------
const drawerOpen = ref(false);
function toggleDrawer(): void { drawerOpen.value = !drawerOpen.value }

// ---- 시뮬레이션 패널 (실물 follower 미연결 시만) --------------------------------
// 메인 화면은 이전 풀스크린 카드 디자인 그대로 유지하되, OpenarmViewer 는 좌하단 플로팅
// 패널로 분리. realActive=true 면 패널 자체를 unmount (실물 팔이 움직이니 사용자는 직접 봄).
// 시뮬은 보조 정보라 default 최소화. 첫 펼침 전엔 three.js/URDF/STL 로드 자체를 안 함.
const stateWs = useEdupingStateWs();
stateWs.start();

// 무궁화는 "사람이 다가오는 것"이 게임 목표라, 근접을 팔/음악 정지가 아니라 도달(게임 종료)
// 신호로 쓴다. 따라서 전역 proximity 정지(bridge pause)는 이 모드 동안 override 로 끄고
// (가리기/떼기가 끊기거나 떨리지 않도록), 도달 판정은 perception 노드의 reached 이벤트로 받는다.
useProximityOverride();

const simMinimized = ref(true);
const simEverOpened = ref(false);
watch(simMinimized, (m) => { if (!m) simEverOpened.value = true; });

// ---- perception (camera PIP + person/motion judgment via ROS2 node) ---------
// 브라우저는 카메라를 직접 취득하지 않는다. useMugunghwaPerception 이 WS 로
// JPEG 프레임을 수신해 pipCanvas 에 그리고, 노드로부터 등록/탈락/모션 이벤트를 수신.
const emotionVideoRef = ref<HTMLVideoElement | null>(null);
const motionFlash = ref(false);

// 자연 촬영 — 진행 단계(노래/관찰/탈락 대기)에서 PIP canvas 위에 5fps 추론을 얹어
// happy/sad 표정 캡처 → /api/photos/natural 업로드.
const captureArmed = computed(
  () =>
    stage.value === 'song'
    || stage.value === 'observation'
    || stage.value === 'eliminationWait',
);
const naturalShotCount = ref(0);
const emotionCapture = useEmotionCapture({
  robot: 'eduping',
  mode: 'mugunghwa',
  enabled: () => captureArmed.value,
  onCaptured: () => { naturalShotCount.value += 1; },
});

const perception = useMugunghwaPerception({
  onRegistered: (childId) => {
    const p = participants.value.find((x) => x.id === childId);
    if (!p || p.registered) return;
    p.registered = true;
    pushToast(`${p.name} 등록!`, p.faceUrl);
    void tts.speak(`${p.name} 등록 완료`).catch(() => { /* TTS off */ });
  },
  onEliminated: (childIds) => {
    const names: string[] = [];
    for (const id of childIds) {
      const p = participants.value.find((x) => x.id === id);
      if (!p || p.eliminated) continue;
      p.eliminated = true;
      if (p.reached) p.reached = false;
      names.push(p.name);
    }
    if (names.length === 0) return;
    const joined = names.join(', ');
    pushToast(`${joined} 어린이 탈락했습니다`);
    void tts.speak(`${joined} 어린이 탈락했습니다`).catch(() => { /* noop */ });
    setStage('eliminationWait');
  },
  onMotion: () => {
    motionFlash.value = true;
    window.setTimeout(() => { motionFlash.value = false; }, 400);
  },
  onReached: (childId) => { onPhysicalReach(childId); },
});

// 근접 도달 — perception 노드가 사람이 1m 이내(디바운스됨)로 다가오면 보내는 신호.
// **노래(song) 단계에서만** "로봇 도달=승리"로 인정. 관찰(freeze) 중엔 움직여서 다가가면
// 그건 도달이 아니라 탈락이어야 하므로 도달 신호를 무시한다. ready/entry/observation/end 무시.
function onPhysicalReach(childId: number | null): void {
  if (stage.value !== 'song') return;
  // 무궁화 규칙: 1명이라도 로봇에 도달하면 잡히지 않은 생존자 전원 승리. 도달한 아이를
  // 1등으로, 나머지 생존자도 순서대로 승자 처리. (탈락자는 그대로 패.)
  const survivors = participants.value.filter((p) => p.registered && !p.eliminated);
  const reacher = childId != null ? survivors.find((p) => p.id === childId) : undefined;
  const ordered = reacher ? [reacher, ...survivors.filter((p) => p !== reacher)] : survivors;
  ordered.forEach((p, i) => { p.reached = true; p.place = i + 1; });
  const name = reacher?.name ?? null;
  playTouchdownSound();
  pushToast(name ? `${name} 로봇 도착! 생존자 전원 승리!` : '로봇 도착! 생존자 전원 승리!');
  void tts.speak(name ? `${name} 도착! 생존자 전원 승리!` : '로봇에 도착했어요! 생존자 전원 승리!')
    .catch(() => { /* noop */ });
  setStage('end');
}

// ---- perception stage signals -----------------------------------------------
// observation 진입/이탈 및 end 단계에서 노드에 신호를 보낸다.
watch(stage, (s, prev) => {
  // recognize 는 참가자 확인(entry) 단계에만. 초기 entry 는 노드가 peer 접속 시 처리하고,
  // 여기선 재진입(다시하기) 시 켜고, entry 를 벗어나면 끈다 → song/종료 중 recognize 중단.
  if (s === 'entry') perception.registerStart();
  else if (prev === 'entry') perception.registerStop();
  if (s === 'observation') perception.observeStart();
  else if (prev === 'observation') perception.observeStop();
  if (s === 'end') {
    // 놀이 끝 — perception 노드 idle 로(YOLO/recognize·attendance POST 정지). 팔 복귀는
    // 모드 이탈(onUnmounted)에서 하므로 여기선 안 함. bindings reset 은 다시하기(restart)에서.
    perception.idle();
  }
});


const observationLike = computed(
  () => stage.value === 'observation' || stage.value === 'eliminationWait',
);

// ---- 준비 countdown (60초 자동 진행) --------------------------------------
const READY_DURATION_MS = 30_000;
const readyRemainingMs = ref(0);
const readyCountdownSec = computed(
  () => Math.max(0, Math.ceil(readyRemainingMs.value / 1000)),
);
let readyTimer: number | null = null;

function startReadyCountdown(): void {
  stopReadyCountdown();
  const startedAt = performance.now();
  readyRemainingMs.value = READY_DURATION_MS;
  readyTimer = window.setInterval(() => {
    if (stage.value !== 'ready') return;
    const elapsed = performance.now() - startedAt;
    const remaining = READY_DURATION_MS - elapsed;
    if (remaining <= 0) {
      readyRemainingMs.value = 0;
      stopReadyCountdown();
      setStage('song');
    } else {
      readyRemainingMs.value = remaining;
    }
  }, 200);
}

function stopReadyCountdown(): void {
  if (readyTimer !== null) {
    window.clearInterval(readyTimer);
    readyTimer = null;
  }
}

watch(stage, (s, prev) => {
  if (s === 'ready') startReadyCountdown();
  else if (prev === 'ready') stopReadyCountdown();
});

// ---- 관찰 countdown (3~5초 정지 → 자동 전이) -------------------------------
// 자동 전이 규칙 (spec SR-PLAY-004 의 관찰 단계와 동일):
//   - 카운트다운 중에 누구라도 탈락 (motion / 교사 ✕) → 'eliminationWait'
//   - 아무도 탈락 안 함 → 다시 'song' 으로 루프
const OBS_DURATION_MIN_MS = 3000;
const OBS_DURATION_MAX_MS = 5000;
const observationRemainingMs = ref(0);
const observationCountdownSec = computed(
  () => Math.max(0, Math.ceil(observationRemainingMs.value / 1000)),
);
let observationTimer: number | null = null;
let observationEndAt = 0;
let observationDur = 0;  // 이 관찰 라운드의 총 duration (역재생 비율 계산용)
let observationEliminatedBefore = 0;

function countEliminated(): number {
  return participants.value.filter((p) => p.registered && p.eliminated).length;
}

function startObservationCountdown(): void {
  stopObservationCountdown();
  // 실물 팔: 떼기(reverse) 재생 (realActive 일 때만, 고정 속도).
  void playArmMotion(true);
  observationEliminatedBefore = countEliminated();
  observationDur = OBS_DURATION_MIN_MS + Math.random() * (OBS_DURATION_MAX_MS - OBS_DURATION_MIN_MS);
  observationEndAt = performance.now() + observationDur;
  observationRemainingMs.value = observationDur;
  observationTimer = window.setInterval(() => {
    const remaining = observationEndAt - performance.now();
    if (remaining <= 0) {
      observationRemainingMs.value = 0;
      stopObservationCountdown();
      const eliminatedDuring = countEliminated() - observationEliminatedBefore;
      setStage(eliminatedDuring > 0 ? 'eliminationWait' : 'song');
    } else {
      observationRemainingMs.value = remaining;
      // 관찰 중에는 팔 정지 — 실물 안전 + 음악만으로 정지/움직임 신호. armSnapshot 은
      // 노래 끝의 가리기 자세에서 그대로 멈춘다 (update 안 함).
    }
  }, 100);
}

function stopObservationCountdown(): void {
  if (observationTimer !== null) {
    window.clearInterval(observationTimer);
    observationTimer = null;
  }
}

watch(stage, (s, prev) => {
  if (s === 'observation') startObservationCountdown();
  else if (prev === 'observation') stopObservationCountdown();
});

// ---- 탈락 대기 — 탈락 확인 후 교사가 직접 ✕ 또는 다음 라운드로 이동 --------
// 브라우저 face-tracking 이 제거되어 "탈락자가 시야 밖으로 나갔는지" 를 자동 판단할 수
// 없다. 탈락 대기는 교사가 드로어의 DEV 패널이나 setStage 로 수동 전환하거나,
// 4초 후 자동으로 노래 단계로 복귀한다.
const ELIM_WAIT_AUTO_RESUME_MS = 4000;
let eliminationWaitTimer: number | null = null;

function startEliminationWait(): void {
  stopEliminationWait();
  const hasPending = participants.value.some((p) => p.registered && p.eliminated);
  if (!hasPending) {
    setStage('song');
    return;
  }
  pushToast('탈락한 친구는 자리에서 벗어나주세요');
  eliminationWaitTimer = window.setTimeout(() => {
    eliminationWaitTimer = null;
    if (stage.value === 'eliminationWait') setStage('song');
  }, ELIM_WAIT_AUTO_RESUME_MS);
}

function stopEliminationWait(): void {
  if (eliminationWaitTimer !== null) {
    window.clearTimeout(eliminationWaitTimer);
    eliminationWaitTimer = null;
  }
}

watch(stage, (s, prev) => {
  if (s === 'eliminationWait') startEliminationWait();
  else if (prev === 'eliminationWait') stopEliminationWait();
});

// 단계별 viewer 입력:
//   entry / ready / end / eliminationWait — rest snapshot (자연 하강 자세). follower WS
//     가 잔존 pose 를 들고 있어도 명시적으로 zero pose 로 덮어쓴다.
//   song — 가리기 1회 보간 후 가리기 자세 유지 (startSongStage 의 coverTimer)
//   observation — 노래 끝 자세 (가리기) 에서 정지 (update 안 함)
watch(stage, (s) => {
  if (s === 'entry' || s === 'ready' || s === 'end' || s === 'eliminationWait') {
    armSnapshot.value = makeRestSnapshot();
  }
});

const isDev = import.meta.env.DEV;

onMounted(() => {
  mode.currentEmotion = STAGE_META[stage.value].emotion;
  void loadRoster();
  // 마운트 시 노래 오디오 + 가리기 모션 데이터 preload — 첫 song stage 진입 시 지연 없게.
  ensureSongAudio();
  void loadMotion();
  // 첫 mount 단계가 entry 면 stage watch 가 한 번 안 돌므로 직접 rest pose 적용.
  armSnapshot.value = makeRestSnapshot();
  // perception WS 연결 + emotion capture 를 PIP canvas 스트림에 연결.
  perception.connect();
  const stream = perception.captureStream(5);
  if (stream && emotionVideoRef.value) {
    emotionVideoRef.value.srcObject = stream;
    void emotionVideoRef.value.play();
    // TODO: captureStream 이 canvas 에 첫 프레임이 그려지기 전에 호출되면 감정 캡처
    // 추론 루프가 빈 프레임을 볼 수 있다. 실 운용 시 timing 을 확인할 것.
    emotionCapture.attach(emotionVideoRef.value);
  }
});

// STT prompt hint — stage 별 expected 단어들.
const _STAGE_HINTS: Record<Stage, string[]> = {
  entry:           ['시작', '시작해', '출발', '준비됐어', '준비완료', '그만', '대기'],
  ready:           ['바로 시작', '바로시작', '준비됐어', '시작', '한번더', '그만'],
  song:            ['그만', '정지', '멈춰', '대기'],
  observation:     ['그만', '정지', '멈춰', '대기'],
  eliminationWait: ['그만', '정지', '멈춰', '대기'],
  end:             ['다시하기', '다시해', '재시작', '한번더', '끝내기', '대기'],
};
watch(
  stage,
  (next) => {
    voice.setSttHints(_STAGE_HINTS[next] ?? []);
  },
  { immediate: true },
);

onUnmounted(() => {
  voice.setSttHints([]);
  // 어떤 경로로 나가든(종료·대기·언마운트) 실물 팔을 제자리로 복귀 — stateWs.stop() 전에 호출.
  void returnArmHome();
  stopSongStage();
  if (songAudio) {
    try { songAudio.pause(); } catch { /* noop */ }
    songAudio.src = '';
    songAudio = null;
  }
  stopObservationCountdown();
  stopEliminationWait();
  stopReadyCountdown();
  if (audioContext) {
    try { void audioContext.close(); } catch { /* noop */ }
    audioContext = null;
  }
  emotionCapture.detach();
  // perception WS 는 useMugunghwaPerception 의 onUnmounted 훅이 disconnect() 를 호출.
  stateWs.stop();
});
</script>

<template>
  <Transition name="fade">
    <div class="popup-overlay">
      <!-- 게임 종료 확인 — voice.confirm 이 set 되어 있을 때 표시. useModeIntents.onModeExit
           가 voiceController.startConfirm 으로 confirm 사이클 시작. -->
      <Transition name="pop">
        <div v-if="showExitConfirm" class="exit-confirm" role="alertdialog" aria-label="게임 종료 확인">
          <div class="exit-confirm-card">
            <p class="exit-confirm-title">{{ voice.confirm?.prompt }}</p>
            <p class="exit-confirm-hint">"응" 또는 "아니" 로 답해주세요</p>
            <div class="exit-confirm-actions">
              <button type="button" class="btn-confirm" @click="onConfirmExitClick">예</button>
              <button type="button" class="btn-cancel" @click="onCancelExitClick">아니오</button>
            </div>
          </div>
        </div>
      </Transition>
      <Transition name="pop" appear>
        <div class="popup-card" role="dialog" aria-modal="true" aria-label="무궁화꽃이 피었습니다">
          <!-- 상단 바: 햄버거 / 단계 인디케이터 / 카메라 / 닫기 -->
          <header class="top-bar" :style="{ borderBottomColor: meta.accent + '33' }">
            <button
              type="button"
              class="btn-icon hamburger"
              :class="{ active: drawerOpen }"
              aria-label="메뉴 열기"
              @click="toggleDrawer"
            >
              <span /><span /><span />
            </button>

            <div class="stage-indicator" :style="{ '--accent': meta.accent }">
              <div class="stage-pulse" />
              <div class="stage-text">
                <div class="stage-label">{{ meta.label }}</div>
                <div class="stage-helper">{{ meta.helper }}</div>
              </div>
            </div>


            <button type="button" class="btn-icon close-btn" aria-label="닫기" @click="close">×</button>
          </header>

          <!-- 메인: 카메라가 중앙을 채움. 게임 단계별 오버레이는 카메라 위에 렌더링. -->
          <main class="main-area">
            <div class="arm-wrap" :class="{ 'motion-flash': motionFlash }">
              <!-- PIP canvas — JPEG 프레임이 perception composable 에 의해 그려진다 -->
              <canvas
                :ref="(el) => (perception.pipCanvas.value = el as HTMLCanvasElement | null)"
                class="center-cam"
              />
              <!-- 감정 캡처용 hidden video — PIP canvas stream 을 srcObject 로 사용 -->
              <video ref="emotionVideoRef" class="emotion-hidden" muted playsinline />

              <!-- 셔터 플래시 -->
              <div
                v-if="emotionCapture.flashTick.value > 0"
                :key="emotionCapture.flashTick.value"
                class="cam-shutter"
              />
              <!-- 감정 캡처 라벨 -->
              <div
                v-if="emotionCapture.lastEmotion.value !== null"
                class="cam-emotion-tag"
                :class="`is-${emotionCapture.lastEmotion.value}`"
              >
                📸 {{ emotionCapture.lastEmotion.value === 'happy' ? '활짝!' : '시무룩' }}
              </div>
              <!-- 라이브 HUD -->
              <div
                v-if="captureArmed && emotionCapture.ready.value && !emotionCapture.inCaptureCooldown.value"
                class="cam-live-hud"
                :class="{ 'has-face': emotionCapture.faceDetected.value }"
              >
                <template v-if="!emotionCapture.faceDetected.value">얼굴 찾는 중…</template>
                <template v-else>
                  웃음 {{ (emotionCapture.liveHappy.value * 100).toFixed(0) }}%
                  · 슬픔 {{ (emotionCapture.liveSad.value * 100).toFixed(0) }}%
                </template>
              </div>
              <!-- 누적 캡처 수 -->
              <div v-if="naturalShotCount > 0" class="cam-shot-count">
                📸 {{ naturalShotCount }}
              </div>

              <!-- 참가자 확인 단계 하단 컨트롤 -->
              <footer v-if="stage === 'entry'" class="cam-stage-foot">
                <div class="entry-info">
                  <div class="entry-line">참가자 확인 중</div>
                  <div class="entry-sub">
                    로봇 카메라가 인식한 친구는 자동으로 등록돼요.
                    <strong>{{ registeredCount }}</strong> / {{ participants.length }} 명 등록됨
                  </div>
                </div>
                <button type="button" class="btn-start" :disabled="registeredCount === 0" @click="startEntryGame">시작</button>
              </footer>

              <!-- 준비 단계 하단 컨트롤 -->
              <footer v-else-if="stage === 'ready'" class="cam-stage-foot">
                <div class="entry-info">
                  <div class="entry-line">준비 — 출발선 뒤로 멀리 가서 자리잡으세요</div>
                  <div class="entry-sub">
                    <strong class="ready-num">{{ readyCountdownSec }}</strong> 초 후 자동 시작
                  </div>
                </div>
                <button type="button" class="btn-start" @click="setStage('song')">바로 시작</button>
              </footer>

              <div v-if="stage === 'song'" class="arm-overlay">
                <div class="song-bar" role="progressbar" aria-label="노래 진행">
                  <div class="song-fill" :style="{ width: `${songProgressPct}%` }" />
                </div>
              </div>

              <!-- 노래 단계: URDF 위에 반투명 터치 타겟 — 자기 얼굴 누르면 도착 처리 -->
              <div v-if="stage === 'song'" class="touch-overlay">
                <div class="touch-overlay-header">
                  <span class="touch-banner-icon">🏁</span>
                  <span>자기 얼굴 터치하면 도착!</span>
                </div>
                <ul class="touch-grid">
                  <li
                    v-for="p in aliveTouchTargets"
                    :key="p.id"
                    class="touch-target"
                    :class="[{ reached: p.reached }, p.place != null ? placeRank(p) : '']"
                    :title="`${p.name} — 터치해서 도착`"
                    @click="toggleReached(p.id)"
                  >
                    <div class="touch-avatar">
                      <img v-if="p.faceUrl" :src="p.faceUrl" :alt="p.name" />
                      <span v-else class="touch-initial">{{ p.name.charAt(0) }}</span>
                      <span v-if="p.place != null" class="place-badge" :class="placeRank(p)">
                        <span class="badge-emoji">{{ placeEmoji(p) }}</span>
                        <span class="badge-text">{{ placeLabel(p) }}</span>
                      </span>
                    </div>
                    <div class="touch-name">{{ p.name }}</div>
                  </li>
                </ul>
              </div>

              <!-- 관찰 단계: 3~5초 카운트다운 + 빨강 비네트 -->
              <div v-if="stage === 'observation'" class="obs-overlay">
                <div class="obs-vignette" />
                <div class="obs-countdown">
                  <div class="obs-num" :class="{ pulse: observationCountdownSec > 0 }">
                    {{ observationCountdownSec }}
                  </div>
                  <div class="obs-label">움직이지 마세요!</div>
                </div>
              </div>
            </div>

            <!-- 하단 참가자 strip — 단계별 상태 한눈에 보기 (노래 단계의 큰 터치 타겟은
                 URDF 위에 별도 오버레이로 표시). -->
            <div class="bottom-strip">
              <ul v-if="visibleParticipants.length > 0" class="participants">
                <li
                  v-for="p in visibleParticipants"
                  :key="p.id"
                  class="participant"
                  :class="[
                    {
                      eliminated: p.eliminated,
                      reached: p.registered && p.reached && !p.eliminated,
                      registered: p.registered && !p.eliminated && !p.reached,
                      waiting: !p.registered && !p.eliminated,
                      clickable: p.registered && !p.eliminated,
                    },
                    p.place != null ? placeRank(p) : '',
                  ]"
                  :title="p.registered && !p.eliminated ? '터치하면 도착(골인) 처리' : ''"
                  @click="toggleReached(p.id)"
                >
                  <div class="avatar">
                    <img v-if="p.faceUrl" :src="p.faceUrl" :alt="p.name" class="face-img" />
                    <span v-else class="initial">{{ p.name.charAt(0) }}</span>
                    <span v-if="p.eliminated" class="x-stamp">✕</span>
                    <span v-else-if="p.reached" class="trophy-stamp">★</span>
                    <span v-else-if="p.registered" class="check-stamp">✓</span>
                    <span v-if="p.place != null" class="place-badge small" :class="placeRank(p)">
                      <span class="badge-emoji">{{ placeEmoji(p) }}</span>
                      <span class="badge-text">{{ placeLabel(p) }}</span>
                    </span>
                    <button
                      v-if="p.registered && !p.eliminated && observationLike"
                      type="button"
                      class="elim-btn"
                      aria-label="탈락 처리"
                      title="탈락 처리"
                      @click.stop="toggleEliminated(p.id)"
                    >✕</button>
                  </div>
                  <div class="p-name">{{ p.name }}</div>
                </li>
              </ul>
              <div v-else class="roster-empty">
                {{ rosterError || '명단 불러오는 중…' }}
              </div>
              <div class="counts">
                <span v-if="stage === 'entry'" class="count reg">
                  등록 <strong>{{ registeredCount }}</strong> / {{ participants.length }}
                </span>
                <template v-else>
                  <span class="count alive">남은 친구 <strong>{{ aliveCount }}</strong></span>
                  <span class="count reach">도착 <strong>{{ reachedCount }}</strong></span>
                  <span class="count out">탈락 <strong>{{ eliminatedCount }}</strong></span>
                </template>
              </div>
            </div>
          </main>

          <!-- 종료 단계: 등수 결과 오버레이 -->
          <Transition name="fade">
            <div v-if="stage === 'end'" class="results-overlay">
              <div class="results-card">
                <header class="results-head">
                  <h2>🎉 놀이 끝!</h2>
                  <p>오늘 친구들 다 같이 놀아줘서 고마워요!</p>
                </header>
                <ol v-if="sortedResults.length > 0" class="results-list">
                  <li
                    v-for="(p, idx) in sortedResults"
                    :key="p.id"
                    class="result-row"
                    :class="[
                      p.place != null ? placeRank(p) : '',
                      { reached: p.reached, eliminated: p.eliminated, top: idx < 3 },
                    ]"
                  >
                    <div class="result-place">
                      <span class="result-emoji">
                        {{ p.place != null ? placeEmoji(p) : (p.eliminated ? '❌' : '👋') }}
                      </span>
                      <span class="result-place-text">
                        {{ placeLabel(p) ?? (p.eliminated ? '탈락' : '참가') }}
                      </span>
                    </div>
                    <div class="result-avatar">
                      <img v-if="p.faceUrl" :src="p.faceUrl" :alt="p.name" />
                      <span v-else>{{ p.name.charAt(0) }}</span>
                    </div>
                    <div class="result-name">{{ p.name }}</div>
                  </li>
                </ol>
                <p v-else class="results-empty">등록된 친구가 없어요.</p>
                <div class="results-actions">
                  <button type="button" class="btn-restart" @click="restartGame">
                    다시 하기
                  </button>
                  <button type="button" class="btn-close-game" @click="close">
                    끝내기
                  </button>
                </div>
              </div>
            </div>
          </Transition>

          <!-- 좌하단: 시뮬레이션 패널 — 실물 follower 미연결 시만, default 최소화, lazy mount -->
          <section
            v-if="!stateWs.realActive.value"
            class="sim-panel"
            :class="{ minimized: simMinimized }"
            aria-label="시뮬레이션"
          >
            <header class="sim-panel-head" @click="simMinimized = !simMinimized">
              <span class="sim-panel-emoji" aria-hidden="true">🤖</span>
              <span class="sim-panel-title">시뮬레이션</span>
              <button
                type="button"
                class="btn-sim-min"
                :aria-label="simMinimized ? '펼치기' : '최소화'"
                @click.stop="simMinimized = !simMinimized"
              >{{ simMinimized ? '+' : '–' }}</button>
            </header>
            <div v-show="!simMinimized" class="sim-panel-body">
              <OpenarmViewer
                v-if="simEverOpened"
                source="follower"
                :external-snapshot="armSnapshot"
                :extra-yaw-deg="-45"
              />
            </div>
          </section>

          <!-- 토스트 (등록 알림 등) — z-index 1000 으로 카메라 모달/드로어 위에 강제 표시 -->
          <Teleport to="body">
            <div class="mugung-toast-stack" aria-live="polite">
              <TransitionGroup name="toast">
                <div v-for="t in toasts" :key="t.id" class="mugung-toast">
                  <div v-if="t.faceUrl" class="mt-face">
                    <img :src="t.faceUrl" :alt="t.text" />
                  </div>
                  <div v-else class="mt-icon">✓</div>
                  <div class="mt-body">
                    <div class="mt-title">{{ t.text }}</div>
                    <div class="mt-sub">참가자 등록 완료</div>
                  </div>
                </div>
              </TransitionGroup>
            </div>
          </Teleport>

          <!-- 드로어 (햄버거) -->
          <Transition name="drawer-fade">
            <div v-if="drawerOpen" class="drawer-backdrop" @click.self="drawerOpen = false" />
          </Transition>
          <Transition name="drawer-slide">
            <aside v-if="drawerOpen" class="drawer">
              <header class="drawer-head">
                <h3>단계</h3>
                <button type="button" class="btn-icon close-btn small" @click="drawerOpen = false">×</button>
              </header>
              <ol class="timeline">
                <li v-for="s in STAGES" :key="s" class="t-item" :class="{ active: stage === s }" :style="{ '--dot': STAGE_META[s].accent }">
                  <span class="t-dot" />
                  <span class="t-label">{{ STAGE_META[s].label }}</span>
                </li>
              </ol>

              <div v-if="isDev" class="dev-section">
                <h4>DEV — 단계 전환</h4>
                <div class="dev-buttons">
                  <button
                    v-for="s in STAGES"
                    :key="s"
                    type="button"
                    class="dev-btn"
                    :class="{ active: stage === s }"
                    @click="setStage(s)"
                  >
                    {{ STAGE_META[s].label }}
                  </button>
                </div>
                <h4 v-if="participants.length > 0">DEV — 등록 토글 (얼굴 인식 시뮬레이션)</h4>
                <div v-if="participants.length > 0" class="dev-buttons">
                  <button
                    v-for="p in participants"
                    :key="`reg-${p.id}`"
                    type="button"
                    class="dev-btn small"
                    :class="{ active: p.registered }"
                    @click="toggleRegistered(p.id)"
                  >
                    {{ p.name }}
                  </button>
                </div>
                <h4 v-if="participants.length > 0">DEV — 탈락 토글</h4>
                <div v-if="participants.length > 0" class="dev-buttons">
                  <button
                    v-for="p in participants"
                    :key="`elim-${p.id}`"
                    type="button"
                    class="dev-btn small"
                    :class="{ active: p.eliminated, disabled: !p.registered }"
                    :disabled="!p.registered"
                    @click="toggleEliminated(p.id)"
                  >
                    {{ p.name }}
                  </button>
                </div>
              </div>
            </aside>
          </Transition>
        </div>
      </Transition>
    </div>
  </Transition>
</template>

<style scoped>
.popup-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  z-index: 60;
}
.popup-card {
  background: #fff7fb;
  width: 100dvw;
  height: 100dvh;
  display: grid;
  grid-template-rows: auto 1fr;
  overflow: hidden;
}

/* ---------------- top bar ---------------- */
.top-bar {
  display: grid;
  grid-template-columns: auto 1fr auto;
  /* [hamburger] [stage] [close] */
  align-items: center;
  gap: 16px;
  padding: 14px 20px;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(8px);
  border-bottom: 2px solid transparent;
  transition: border-color 0.25s ease;
  min-height: 92px;
}
.btn-icon {
  width: 52px;
  height: 52px;
  border-radius: 14px;
  border: 1px solid rgba(190, 24, 93, 0.18);
  background: white;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: #be185d;
  font-family: inherit;
  flex-shrink: 0;
}
.btn-icon:hover { background: #fce7f3; }
.btn-icon.close-btn { font-size: 28px; line-height: 1; }
.btn-icon.close-btn.small { width: 36px; height: 36px; font-size: 22px; border-radius: 10px; }

.hamburger {
  flex-direction: column;
  gap: 5px;
}
.hamburger span {
  display: block;
  width: 22px;
  height: 2.5px;
  background: #be185d;
  border-radius: 999px;
  transition: transform 0.2s ease, opacity 0.2s ease;
}
.hamburger.active span:nth-child(1) { transform: translateY(7.5px) rotate(45deg); }
.hamburger.active span:nth-child(2) { opacity: 0; }
.hamburger.active span:nth-child(3) { transform: translateY(-7.5px) rotate(-45deg); }

.stage-indicator {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 8px 18px;
  background: white;
  border-radius: 14px;
  border-left: 6px solid var(--accent);
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.06);
  min-width: 0;
  overflow: hidden;
}
.stage-pulse {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 0 0 var(--accent);
  animation: pulse 1.6s ease-out infinite;
  flex-shrink: 0;
}
@keyframes pulse {
  0%   { box-shadow: 0 0 0 0 color-mix(in srgb, var(--accent) 50%, transparent); }
  70%  { box-shadow: 0 0 0 14px color-mix(in srgb, var(--accent) 0%, transparent); }
  100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--accent) 0%, transparent); }
}
.stage-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.stage-label {
  font-size: 28px;
  font-weight: 800;
  color: var(--accent);
  letter-spacing: -0.02em;
  line-height: 1;
}
.stage-helper {
  font-size: 13px;
  color: #6b4258;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}


/* 중앙 카메라 (PIP canvas) */
.center-cam {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
/* 감정 캡처용 hidden video — PIP canvas 스트림의 화면 외 처리용 */
.emotion-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
  pointer-events: none;
}
.arm-wrap.motion-flash {
  animation: motion-flash 0.55s ease-in-out infinite;
  outline: 4px solid #dc2626;
}

.cam-shutter {
  position: absolute;
  inset: 0;
  background: white;
  opacity: 0;
  pointer-events: none;
  animation: cam-shutter-flash 0.6s ease-out;
  animation-iteration-count: 1;
  z-index: 3;
}
@keyframes cam-shutter-flash {
  0%   { opacity: 0; }
  10%  { opacity: 0.95; }
  100% { opacity: 0; }
}
.cam-emotion-tag {
  position: absolute;
  bottom: 72px;
  left: 12px;
  font-size: 13px;
  font-weight: 700;
  padding: 4px 10px;
  border-radius: 999px;
  color: white;
  pointer-events: none;
  z-index: 3;
}
.cam-emotion-tag.is-happy { background: rgba(45, 139, 87, 0.92); }
.cam-emotion-tag.is-sad   { background: rgba(193, 69, 69, 0.92); }
.cam-live-hud {
  position: absolute;
  left: 12px;
  right: 12px;
  bottom: 72px;
  z-index: 3;
  font-size: 12px;
  font-weight: 600;
  padding: 4px 8px;
  border-radius: 6px;
  color: rgba(255, 255, 255, 0.95);
  background: rgba(30, 45, 58, 0.7);
  pointer-events: none;
  line-height: 1.4;
  text-align: center;
  max-width: 280px;
}
.cam-live-hud.has-face { background: rgba(45, 110, 75, 0.8); }
.cam-shot-count {
  position: absolute;
  top: 12px;
  left: 12px;
  font-size: 12px;
  font-weight: 700;
  padding: 4px 10px;
  border-radius: 8px;
  color: white;
  background: rgba(0, 0, 0, 0.6);
  pointer-events: none;
  z-index: 3;
}

/* 참가자 확인/준비 단계 하단 컨트롤 바 */
.cam-stage-foot {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 20px;
  background: rgba(15, 23, 42, 0.72);
  backdrop-filter: blur(6px);
  z-index: 4;
}

@keyframes motion-flash {
  0%, 100% {
    box-shadow: 0 0 0 0 rgba(220, 38, 38, 0.65), 0 2px 8px rgba(15, 23, 42, 0.18);
  }
  50% {
    box-shadow: 0 0 0 12px rgba(220, 38, 38, 0), 0 4px 14px rgba(220, 38, 38, 0.5);
  }
}
/* ---------------- main area ---------------- */
.main-area {
  display: grid;
  grid-template-rows: 1fr auto;
  min-height: 0;
  overflow: hidden;
}
.arm-wrap {
  position: relative;
  margin: 16px 20px 0;
  border-radius: 18px;
  overflow: hidden;
  background: #eaf3fa;
  min-height: 0;
}
.arm-wrap :deep(.openarm-viewer-wrap) { border-radius: 0; }

/* ---- 시뮬레이션 플로팅 패널 (좌하단) ------------------------------------------ */
.sim-panel {
  position: absolute;
  bottom: 18px;
  left: 18px;
  width: 340px;
  background: rgba(255, 255, 255, 0.97);
  border-radius: 16px;
  border: 1px solid rgba(190, 24, 93, 0.12);
  box-shadow: 0 18px 40px -12px rgba(15, 23, 42, 0.35);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  backdrop-filter: blur(6px);
  z-index: 65;  /* 메인 화면 위, 토스트(1000)·드로어·결과 오버레이 아래 */
}
.sim-panel-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: linear-gradient(135deg, #fce7f3 0%, #fbcfe8 100%);
  color: #9d174d;
  cursor: pointer;
  user-select: none;
  border-bottom: 1px solid rgba(190, 24, 93, 0.10);
}
.sim-panel-emoji { font-size: 16px; line-height: 1; }
.sim-panel-title {
  font-weight: 800;
  font-size: 14px;
  letter-spacing: 0.01em;
  flex: 1;
}
.btn-sim-min {
  border: none;
  background: rgba(255, 255, 255, 0.7);
  color: #9d174d;
  width: 26px;
  height: 26px;
  border-radius: 8px;
  font-size: 16px;
  font-weight: 800;
  line-height: 1;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.btn-sim-min:hover { background: white; }
.sim-panel-body { height: 240px; display: flex; }
.sim-panel-body :deep(.openarm-viewer-wrap) { border-radius: 0; flex: 1; }
.sim-panel.minimized .sim-panel-body { display: none; }
.arm-overlay {
  position: absolute;
  left: 16px;
  right: 16px;
  bottom: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  pointer-events: none;
}
.tempo-badge {
  align-self: flex-start;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 6px 14px;
  background: rgba(255, 255, 255, 0.96);
  border-radius: 999px;
  font-size: 13px;
  font-weight: 700;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.15);
}
.tempo-badge.tempo-random       { color: #7c3aed; }
.tempo-badge.tempo-slow_to_fast { color: #ec4899; }
.tempo-badge.tempo-fast_to_slow { color: #0d9488; }
.tempo-rate {
  font-variant-numeric: tabular-nums;
  color: #475569;
  font-weight: 600;
}
.song-bar {
  height: 8px;
  background: rgba(252, 231, 243, 0.85);
  border-radius: 999px;
  overflow: hidden;
}
.song-fill {
  height: 100%;
  background: linear-gradient(90deg, #ec4899, #f59e0b);
  border-radius: 999px;
  transition: width 0.08s linear;
}

/* ---- 관찰 카운트다운 오버레이 ---- */
.obs-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}
.obs-vignette {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(circle at center,
      rgba(220, 38, 38, 0) 35%,
      rgba(220, 38, 38, 0.20) 65%,
      rgba(127, 29, 29, 0.45) 100%);
  animation: obs-vignette-pulse 1.2s ease-in-out infinite;
}
@keyframes obs-vignette-pulse {
  0%, 100% { opacity: 0.7; }
  50% { opacity: 1; }
}
.obs-countdown {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}
.obs-num {
  font-size: clamp(140px, 22vw, 280px);
  font-weight: 900;
  color: #fee2e2;
  letter-spacing: -0.05em;
  line-height: 1;
  text-shadow:
    0 0 30px rgba(220, 38, 38, 0.9),
    0 0 70px rgba(220, 38, 38, 0.6),
    0 8px 24px rgba(0, 0, 0, 0.45);
  font-variant-numeric: tabular-nums;
}
.obs-num.pulse {
  animation: obs-num-pulse 1s cubic-bezier(.16, 1, .3, 1) infinite;
}
@keyframes obs-num-pulse {
  0%   { transform: scale(0.92); }
  20%  { transform: scale(1.08); }
  100% { transform: scale(1.0); }
}
.obs-label {
  font-size: clamp(20px, 2.6vw, 32px);
  font-weight: 800;
  color: white;
  text-shadow: 0 2px 8px rgba(0, 0, 0, 0.7), 0 0 18px rgba(220, 38, 38, 0.55);
  letter-spacing: 0.02em;
}

/* ---------------- bottom strip ---------------- */
.bottom-strip {
  padding: 14px 20px 18px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}

/* ---- 노래 단계의 URDF 위 터치 오버레이 ---- */
.touch-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  gap: 22px;
  padding: 32px 24px;
  pointer-events: none;
}
.touch-overlay-header {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 8px 18px;
  background: rgba(245, 158, 11, 0.92);
  color: white;
  font-size: clamp(15px, 1.8vw, 20px);
  font-weight: 800;
  border-radius: 999px;
  box-shadow: 0 6px 18px rgba(245, 158, 11, 0.45);
  letter-spacing: 0.02em;
}
.touch-banner-icon { font-size: 18px; line-height: 1; }
.touch-grid {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  /* 모니터 가로형 (landscape) — 3열 × 2행. 6명 표시 시 깔끔하게 한 화면. */
  grid-template-columns: repeat(3, auto);
  grid-auto-rows: auto;
  justify-content: center;
  align-content: center;
  justify-items: center;
  gap: clamp(14px, 2vmin, 26px);
  pointer-events: auto;
  max-width: min(960px, 88%);
}
@media (orientation: portrait) {
  /* 모니터 세로형 — 2열 × 3행. 좁은 가로공간을 보호. */
  .touch-grid {
    grid-template-columns: repeat(2, auto);
    max-width: min(640px, 92%);
  }
}
.touch-target {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  opacity: 0.85;
  transition: opacity 0.15s ease, transform 0.12s ease;
  animation: touch-target-bob 1.6s ease-in-out infinite;
}
.touch-target:hover { opacity: 1; }
.touch-target:active { transform: scale(0.94); }
.touch-target.reached { animation: none; opacity: 1; }
.touch-target.reached .touch-avatar {
  border-color: #f59e0b;
  background: #fffbeb;
  box-shadow: 0 0 0 6px rgba(245, 158, 11, 0.28), 0 10px 26px rgba(245, 158, 11, 0.55);
  color: #b45309;
}
.touch-avatar {
  position: relative;
  width: clamp(88px, 11vw, 120px);
  height: clamp(88px, 11vw, 120px);
  border-radius: 50%;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.94);
  border: 5px solid #16a34a;
  box-shadow: 0 0 0 5px rgba(22, 163, 74, 0.20), 0 8px 22px rgba(22, 163, 74, 0.40);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #15803d;
  font-size: 44px;
  font-weight: 800;
}
.touch-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  /* 카메라 비디오를 mirror 캡처했으니 썸네일도 mirror 표시 */
  transform: scaleX(-1);
}
/* place 뱃지 — 등수 (1등, 2등, ...). gold/silver/bronze, 큰 medal + 텍스트 2줄.
   아바타 프레임을 살짝 침범해 prominent 하게 배치. */
.place-badge {
  position: absolute;
  top: -18px;
  right: -18px;
  min-width: 64px;
  height: 64px;
  padding: 6px 10px;
  border-radius: 999px;
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1px;
  color: white;
  letter-spacing: -0.02em;
  border: 5px solid white;
  box-shadow: 0 8px 22px rgba(15, 23, 42, 0.45), 0 0 0 2px rgba(15, 23, 42, 0.08);
  z-index: 4;
  line-height: 1;
  font-family: inherit;
}
.place-badge .badge-emoji {
  font-size: 24px;
  line-height: 1;
}
.place-badge .badge-text {
  font-size: 13px;
  font-weight: 900;
  letter-spacing: 0;
}
.place-badge.gold   { background: linear-gradient(135deg, #fcd34d, #d97706); }
.place-badge.silver { background: linear-gradient(135deg, #e2e8f0, #64748b); }
.place-badge.bronze { background: linear-gradient(135deg, #fbbf24, #92400e); color: #fff7e6; }
.place-badge.rank-n { background: linear-gradient(135deg, #94a3b8, #475569); }
/* 작은 배지 (compact 하단 strip 용) */
.place-badge.small {
  min-width: 38px;
  height: 38px;
  padding: 2px 6px;
  border-width: 3px;
  top: -10px;
  right: -10px;
  gap: 0;
}
.place-badge.small .badge-emoji { font-size: 14px; }
.place-badge.small .badge-text { font-size: 9px; font-weight: 800; }

/* 등수 별 외곽 발광 — 프레임 자체를 두껍게 + 큰 halo 로 conspicuous 하게 */
.touch-target.gold .touch-avatar {
  border-color: #f59e0b;
  border-width: 7px;
  box-shadow: 0 0 0 10px rgba(245, 158, 11, 0.40), 0 16px 40px rgba(245, 158, 11, 0.65);
}
.touch-target.silver .touch-avatar {
  border-color: #94a3b8;
  border-width: 7px;
  box-shadow: 0 0 0 10px rgba(148, 163, 184, 0.35), 0 14px 30px rgba(100, 116, 139, 0.55);
}
.touch-target.bronze .touch-avatar {
  border-color: #b45309;
  border-width: 7px;
  box-shadow: 0 0 0 10px rgba(180, 83, 9, 0.30), 0 14px 30px rgba(180, 83, 9, 0.55);
}
/* compact 하단 strip 카드에도 medal 프레임 적용 (작게) */
.participant.gold .avatar {
  border-color: #f59e0b !important;
  border-width: 5px;
  box-shadow: 0 0 0 6px rgba(245, 158, 11, 0.30), 0 6px 16px rgba(245, 158, 11, 0.45) !important;
}
.participant.silver .avatar {
  border-color: #94a3b8 !important;
  border-width: 5px;
  box-shadow: 0 0 0 6px rgba(148, 163, 184, 0.30), 0 6px 16px rgba(100, 116, 139, 0.40) !important;
}
.participant.bronze .avatar {
  border-color: #b45309 !important;
  border-width: 5px;
  box-shadow: 0 0 0 6px rgba(180, 83, 9, 0.30), 0 6px 16px rgba(180, 83, 9, 0.45) !important;
}

.touch-target .trophy-stamp {
  /* 도착 상태에서 우하단 트로피 — 작은 흰 배지 */
  position: absolute;
  font-size: 22px;
  width: 30px;
  height: 30px;
  inset: auto -2px -2px auto;
  background: white;
  border-radius: 50%;
  color: #b45309;
  border: 2px solid #f59e0b;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.2);
  display: flex;
  align-items: center;
  justify-content: center;
}
.touch-name {
  font-size: 16px;
  font-weight: 800;
  color: white;
  background: rgba(15, 23, 42, 0.62);
  padding: 3px 12px;
  border-radius: 999px;
  letter-spacing: 0.02em;
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
@keyframes touch-target-bob {
  0%, 100% { transform: translateY(0); }
  50%     { transform: translateY(-6px); }
}
.participants {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
  justify-content: center;
}
.participant {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  width: 76px;
  position: relative;
  transition: filter 0.25s ease, opacity 0.25s ease;
}
.participant.waiting {
  opacity: 0.6;
  filter: grayscale(0.5);
}
.participant.eliminated {
  opacity: 0.55;
  filter: grayscale(0.4);
}
.participant.clickable { cursor: pointer; }
.participant.clickable .avatar:hover {
  transform: scale(1.04);
}
.avatar {
  position: relative;
  width: 60px;
  height: 60px;
  border-radius: 50%;
  background: white;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  font-size: 24px;
  font-weight: 800;
  border: 4px solid #cbd5e1;
  color: #64748b;
  box-shadow: none;
  transition: border-color 0.25s ease, box-shadow 0.25s ease, color 0.25s ease, background 0.25s ease, transform 0.12s ease;
}
.face-img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  /* 카메라 비디오가 mirror 되어 있어 — 썸네일도 mirror 로 통일 */
  transform: scaleX(-1);
}
.participant.waiting .avatar {
  border-style: dashed;
  border-color: #94a3b8;
  color: #94a3b8;
}
.participant.registered .avatar {
  border-color: #16a34a;
  color: #15803d;
  background: #f0fdf4;
  box-shadow: 0 0 0 4px rgba(22, 163, 74, 0.15), 0 4px 14px rgba(22, 163, 74, 0.30);
}
.participant.reached .avatar {
  border-color: #f59e0b;
  color: #b45309;
  background: #fffbeb;
  box-shadow: 0 0 0 4px rgba(245, 158, 11, 0.18), 0 6px 18px rgba(245, 158, 11, 0.45);
}
.participant.eliminated .avatar {
  border-style: dashed;
  border-color: #b91c1c;
  color: #b91c1c;
  background: white;
  box-shadow: none;
}
.initial { line-height: 1; }
.x-stamp,
.check-stamp {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 900;
  line-height: 1;
  pointer-events: none;
}
.x-stamp {
  color: #b91c1c;
  font-size: 56px;
  text-shadow: 0 2px 4px rgba(255, 255, 255, 0.8);
}
.check-stamp,
.trophy-stamp {
  font-size: 18px;
  width: 22px;
  height: 22px;
  inset: auto -4px -6px auto;
  background: white;
  border-radius: 50%;
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.15);
}
.elim-btn {
  position: absolute;
  top: -6px;
  right: -6px;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  border: 2px solid #b91c1c;
  background: white;
  color: #b91c1c;
  font-size: 13px;
  font-weight: 800;
  line-height: 1;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-family: inherit;
  box-shadow: 0 2px 6px rgba(185, 28, 28, 0.35);
  z-index: 3;
  padding: 0;
}
.elim-btn:hover {
  background: #fee2e2;
}
.elim-btn:active {
  transform: scale(0.92);
}
.check-stamp {
  color: rgba(22, 163, 74, 0.95);
  border: 2px solid #16a34a;
}
.trophy-stamp {
  color: #b45309;
  border: 2px solid #f59e0b;
  font-size: 16px;
}
.p-name {
  font-size: 13px;
  font-weight: 700;
  color: #475569;
  max-width: 76px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.roster-empty {
  font-size: 13px;
  color: #94a3b8;
  padding: 12px 0;
}

.counts {
  display: flex;
  gap: 22px;
  margin-top: 4px;
}
.count {
  font-size: 13px;
  color: #64748b;
}
.count strong {
  font-size: 16px;
  margin-left: 6px;
  font-variant-numeric: tabular-nums;
}
.count.alive strong { color: #15803d; }
.count.out strong { color: #b91c1c; }
.count.reach strong { color: #b45309; }
.count.reg strong { color: #16a34a; }

/* toast styles for the Teleport target — defined in the un-scoped <style> block at bottom */

/* ---------------- 종료 단계 결과 오버레이 ---------------- */
.results-overlay {
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, rgba(252, 231, 243, 0.97), rgba(253, 242, 248, 0.97));
  z-index: 70;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px;
  overflow-y: auto;
}
.results-card {
  background: white;
  border-radius: 24px;
  padding: 30px 36px 28px;
  box-shadow: 0 24px 64px rgba(190, 24, 93, 0.25);
  width: min(720px, 96%);
  max-height: 92dvh;
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.results-head {
  text-align: center;
}
.results-head h2 {
  margin: 0 0 6px;
  font-size: clamp(32px, 4vw, 48px);
  font-weight: 900;
  color: #be185d;
  letter-spacing: -0.02em;
}
.results-head p {
  margin: 0;
  color: #6b4258;
  font-size: 15px;
}
.results-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow-y: auto;
  min-height: 0;
}
.result-row {
  display: grid;
  grid-template-columns: 92px 64px 1fr;
  align-items: center;
  gap: 16px;
  padding: 12px 14px;
  border-radius: 14px;
  background: #fdf2f8;
  border: 2px solid transparent;
}
.result-row.eliminated {
  opacity: 0.7;
  background: #fef2f2;
}
.result-row.gold   { background: linear-gradient(135deg, #fef3c7, #fcd34d); border-color: #f59e0b; }
.result-row.silver { background: linear-gradient(135deg, #f1f5f9, #cbd5e1); border-color: #94a3b8; }
.result-row.bronze { background: linear-gradient(135deg, #ffedd5, #fdba74); border-color: #c2410c; }
.result-row.top {
  padding: 14px 16px;
}
.result-place {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
.result-emoji {
  font-size: 36px;
  line-height: 1;
}
.result-row.top .result-emoji { font-size: 44px; }
.result-place-text {
  font-size: 14px;
  font-weight: 900;
  color: #6b4258;
  letter-spacing: -0.01em;
}
.result-row.gold   .result-place-text { color: #92400e; }
.result-row.silver .result-place-text { color: #475569; }
.result-row.bronze .result-place-text { color: #7c2d12; }
.result-row.eliminated .result-place-text { color: #991b1b; }

.result-avatar {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  overflow: hidden;
  background: white;
  border: 3px solid currentColor;
  color: #be185d;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  font-weight: 800;
}
.result-row.gold   .result-avatar { color: #f59e0b; }
.result-row.silver .result-avatar { color: #94a3b8; }
.result-row.bronze .result-avatar { color: #c2410c; }
.result-row.eliminated .result-avatar { color: #b91c1c; filter: grayscale(0.4); }
.result-avatar img {
  width: 100%; height: 100%;
  object-fit: cover;
  transform: scaleX(-1);
}
.result-name {
  font-size: 18px;
  font-weight: 800;
  color: #1e293b;
  letter-spacing: -0.01em;
}
.result-row.top .result-name {
  font-size: 22px;
}
.results-empty {
  margin: 0;
  text-align: center;
  color: #94a3b8;
  font-size: 14px;
}
.results-actions {
  display: flex;
  gap: 12px;
  justify-content: center;
  padding-top: 8px;
}
.btn-restart, .btn-close-game {
  padding: 12px 32px;
  font-size: 18px;
  font-weight: 800;
  font-family: inherit;
  border: none;
  border-radius: 14px;
  cursor: pointer;
  letter-spacing: 0.02em;
  transition: transform 0.08s ease, box-shadow 0.18s ease;
}
.btn-restart {
  background: linear-gradient(135deg, #ec4899, #be185d);
  color: white;
  box-shadow: 0 6px 18px rgba(236, 72, 153, 0.45);
}
.btn-restart:hover { transform: translateY(-1px); box-shadow: 0 8px 22px rgba(236, 72, 153, 0.55); }
.btn-close-game {
  background: white;
  color: #6b4258;
  border: 2px solid #f9a8d4;
}
.btn-close-game:hover { background: #fdf2f8; }

.entry-info {
  color: white;
  text-align: left;
  min-width: 0;
  flex: 1;
}
.entry-line {
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 0.02em;
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.entry-sub {
  margin-top: 2px;
  font-size: 12px;
  color: #cbd5e1;
}
.entry-sub strong {
  color: #4ade80;
  font-variant-numeric: tabular-nums;
}
.ready-num {
  font-size: 32px;
  font-weight: 900;
  color: #fbbf24;
  text-shadow: 0 0 12px rgba(251, 191, 36, 0.6);
  margin-right: 4px;
}
.btn-start {
  flex-shrink: 0;
  background: linear-gradient(135deg, #16a34a, #15803d);
  color: white;
  border: none;
  border-radius: 14px;
  padding: 12px 28px;
  font-size: 18px;
  font-weight: 800;
  font-family: inherit;
  letter-spacing: 0.02em;
  cursor: pointer;
  box-shadow: 0 6px 16px rgba(22, 163, 74, 0.45);
  transition: transform 0.08s ease, box-shadow 0.18s ease;
}
.btn-start:hover { transform: translateY(-1px); box-shadow: 0 8px 20px rgba(22, 163, 74, 0.55); }
.btn-start:active { transform: translateY(1px); box-shadow: 0 3px 8px rgba(22, 163, 74, 0.45); }

/* ---------------- drawer ---------------- */
.drawer-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.35);
  z-index: 70;
}
.drawer {
  position: fixed;
  top: 0;
  left: 0;
  bottom: 0;
  width: min(360px, 86vw);
  background: white;
  z-index: 71;
  box-shadow: 4px 0 24px rgba(15, 23, 42, 0.18);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px;
  background: linear-gradient(135deg, rgba(252, 231, 243, 0.9) 0%, rgba(253, 242, 248, 0.95) 100%);
  border-bottom: 1px solid rgba(236, 72, 153, 0.12);
}
.drawer-head h3 { margin: 0; font-size: 18px; color: #be185d; }

.timeline {
  list-style: none;
  margin: 0;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.t-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 10px;
  color: #94a3b8;
  font-size: 15px;
  font-weight: 600;
}
.t-item.active {
  background: color-mix(in srgb, var(--dot) 12%, white);
  color: var(--dot);
  font-weight: 800;
}
.t-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--dot);
  opacity: 0.35;
}
.t-item.active .t-dot { opacity: 1; }

.dev-section {
  padding: 14px 18px;
  border-top: 1px dashed #f9a8d4;
  background: #fdf2f8;
  overflow-y: auto;
}
.dev-section h4 {
  margin: 0 0 8px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: #be185d;
  text-transform: uppercase;
}
.dev-section h4:not(:first-child) { margin-top: 14px; }
.dev-buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.dev-btn {
  background: white;
  border: 1px solid #f9a8d4;
  border-radius: 8px;
  padding: 6px 10px;
  font-size: 12px;
  font-weight: 600;
  color: #be185d;
  cursor: pointer;
  font-family: inherit;
}
.dev-btn:hover { background: #fbcfe8; }
.dev-btn.active {
  background: #ec4899;
  color: white;
  border-color: #be185d;
}
.dev-btn.small { padding: 4px 8px; font-size: 11px; }
.dev-btn[disabled],
.dev-btn.disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* ---------------- responsive ---------------- */
@media (max-width: 720px) {
  .top-bar { padding: 10px 12px; gap: 10px; min-height: 80px; }
  .stage-label { font-size: 22px; }
  .stage-helper { font-size: 11px; }
  .btn-icon { width: 44px; height: 44px; border-radius: 12px; }
  .arm-wrap { margin: 12px 12px 0; }
  .bottom-strip { padding: 10px 12px 14px; }
  .avatar { width: 52px; height: 52px; font-size: 20px; border-width: 3px; }
  .participant { width: 64px; }
}

/* ---------------- transitions ---------------- */
.fade-enter-active, .fade-leave-active { transition: opacity 0.18s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
.pop-enter-active { transition: opacity 0.22s ease, transform 0.22s cubic-bezier(.16,1,.3,1); }
.pop-leave-active { transition: opacity 0.16s ease, transform 0.16s ease; }
.pop-enter-from { opacity: 0; transform: scale(0.94) translateY(10px); }
.pop-leave-to { opacity: 0; transform: scale(0.97); }

.drawer-fade-enter-active, .drawer-fade-leave-active { transition: opacity 0.18s ease; }
.drawer-fade-enter-from, .drawer-fade-leave-to { opacity: 0; }
.drawer-slide-enter-active { transition: transform 0.24s cubic-bezier(.16,1,.3,1); }
.drawer-slide-leave-active { transition: transform 0.20s ease; }
.drawer-slide-enter-from, .drawer-slide-leave-to { transform: translateX(-100%); }

/* ---- 게임 종료 확인 popup ---- */
.exit-confirm {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10000;
}
.exit-confirm-card {
  background: #fff;
  border-radius: 16px;
  padding: 28px 32px;
  min-width: 320px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.25);
  text-align: center;
}
.exit-confirm-title {
  font-size: 22px;
  font-weight: 700;
  margin: 0 0 8px;
  color: #111;
}
.exit-confirm-hint {
  font-size: 14px;
  color: #666;
  margin: 0 0 20px;
}
.exit-confirm-actions {
  display: flex;
  gap: 12px;
  justify-content: center;
}
.btn-confirm, .btn-cancel {
  flex: 1;
  padding: 12px 24px;
  border-radius: 8px;
  border: none;
  font-size: 16px;
  font-weight: 600;
  cursor: pointer;
}
.btn-confirm {
  background: #ef4444;
  color: white;
}
.btn-cancel {
  background: #e5e7eb;
  color: #111;
}
</style>

<!--
  toast styles are NOT scoped because the elements are teleported to <body> and the
  scoped CSS hash wouldn't match them. Prefix .mugung- to avoid leaking into other
  components.
-->
<style>
.mugung-toast-stack {
  position: fixed;
  top: 32px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  flex-direction: column;
  gap: 10px;
  z-index: 1000;
  pointer-events: none;
}
.mugung-toast {
  display: inline-flex;
  align-items: center;
  gap: 14px;
  padding: 14px 24px 14px 14px;
  min-width: 280px;
  background: rgba(15, 23, 42, 0.95);
  color: white;
  border-radius: 18px;
  box-shadow: 0 16px 40px rgba(15, 23, 42, 0.45), 0 0 0 4px rgba(74, 222, 128, 0.18);
  border: 2px solid #16a34a;
  font-family: inherit;
}
.mt-face,
.mt-icon {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  flex-shrink: 0;
  overflow: hidden;
  background: #16a34a;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 28px;
  font-weight: 800;
  color: white;
  box-shadow: 0 0 0 3px rgba(22, 163, 74, 0.35);
}
.mt-face img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  /* 카메라 비디오를 mirror 한 썸네일이라 같은 방향으로 보이게 */
  transform: scaleX(-1);
}
.mt-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.mt-title {
  font-size: 20px;
  font-weight: 800;
  letter-spacing: -0.01em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.mt-sub {
  font-size: 12px;
  font-weight: 600;
  color: #86efac;
  letter-spacing: 0.04em;
}

.toast-enter-active {
  transition: opacity 0.28s ease, transform 0.32s cubic-bezier(.16,1,.3,1);
}
.toast-leave-active {
  transition: opacity 0.20s ease, transform 0.22s ease;
}
.toast-enter-from {
  opacity: 0;
  transform: translateY(-32px) scale(0.92);
}
.toast-leave-to {
  opacity: 0;
  transform: translateY(-12px) scale(0.98);
}
</style>
