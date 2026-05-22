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
import { computed, inject, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import type { EmotionId } from '@/config/robots';
import { useModeStore } from '@/stores/mode';
import { VOICE_CONTROLLER_KEY } from '@/composables/voiceControllerKey';
import { useEmotionCapture } from '@/composables/useEmotionCapture';
import { pickExternalCamera } from '@/composables/selectExternalCamera';
import { useFaceDetector } from '@/composables/useFaceDetector';
import { useFaceTracker, type Bbox, type TrackedFace } from '@/composables/useFaceTracker';
import { useFaceIdentityCache, type IdentityResult } from '@/composables/useFaceIdentityCache';
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

interface ChildRoster { id: number; name: string }
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
  /** 등록 시 카메라에서 잘라낸 얼굴 썸네일 (data URL). 없으면 이니셜 표시. */
  faceUrl?: string;
}

const DEVICE_TOKEN = import.meta.env.VITE_ROBOT_TOKEN ?? 'dev-robot-token-change-me';

const mode = useModeStore();
const voiceController = inject(VOICE_CONTROLLER_KEY);
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

// ---- 노래 stage: tempo variation + 실 오디오 진행 추적 -----------------------
// `yeonghui_mugunghwa.mp3` (자연 속도 ~4.6s) 가 단일 진실의 원천 (single source of truth).
// `audio.currentTime / audio.duration` 으로 진행률을 그리고, `audio.ended` 가 발화하면
// 짧은 꼬리 후 관찰 단계로 전이. 이전엔 TTS 발화 vs. 가상 타이머 두 경주를 돌리느라
// 빠른 tempo 에서 가상 시간이 먼저 만료돼 "무궁화" 도중 끊기는 버그가 있었음.
type TempoPattern = 'random' | 'slow_to_fast' | 'fast_to_slow';

const TEMPO_LABEL: Record<TempoPattern, string> = {
  random: '빨랐다 느렸다',
  slow_to_fast: '점점 빠르게',
  fast_to_slow: '점점 느리게',
};

// 0.6 = 늘어진 슬로우모, 1.1 = 자연 속도 + 10%. 실물 로봇팔 안전상 RATE_MAX 는
// 자연 속도 110% 를 넘기지 않는다 — 모터 부하·관성 우려 + 어린이 손이 닿는 거리.
// 슬로우 쪽은 모터에 무해하므로 RATE_MIN 은 충분히 낮게 유지.
const RATE_MIN = 0.6;
const RATE_MAX = 1.1;
const RATE_MID = (RATE_MIN + RATE_MAX) / 2;
// 'random' 패턴의 속도 갱신 간격도 무작위 — 일정 주기로 바뀌면 거기에 적응당함.
const RANDOM_RATE_MIN_REFRESH_MS = 220;
const RANDOM_RATE_MAX_REFRESH_MS = 700;
const TICK_MS = 80;
const SONG_AUDIO_URL = '/sounds/yeonghui_mugunghwa.mp3';

const tempoPattern = ref<TempoPattern>('slow_to_fast');
const currentRate = ref(1.0);
const songProgressRatio = ref(0);  // audio.currentTime / audio.duration, live updated
const songProgressPct = computed(() => Math.min(100, songProgressRatio.value * 100));

let songTimer: number | null = null;
let songTailTimer: number | null = null;
let lastTickAt = 0;
let lastRandomChangeAt = 0;
let nextRandomRefreshMs = RANDOM_RATE_MIN_REFRESH_MS;
let songAudio: HTMLAudioElement | null = null;

function pickTempoPattern(): TempoPattern {
  const r = Math.random();
  if (r < 1 / 3) return 'random';
  if (r < 2 / 3) return 'slow_to_fast';
  return 'fast_to_slow';
}

function pickRandomRefreshMs(): number {
  return (
    RANDOM_RATE_MIN_REFRESH_MS
    + Math.random() * (RANDOM_RATE_MAX_REFRESH_MS - RANDOM_RATE_MIN_REFRESH_MS)
  );
}

function ensureSongAudio(): HTMLAudioElement {
  if (songAudio) return songAudio;
  const a = new Audio(SONG_AUDIO_URL);
  a.preload = 'auto';
  songAudio = a;
  return a;
}

function startSongStage(): void {
  stopSongStage();
  tempoPattern.value = pickTempoPattern();
  nextRandomRefreshMs = pickRandomRefreshMs();
  songProgressRatio.value = 0;
  currentRate.value =
    tempoPattern.value === 'fast_to_slow' ? RATE_MAX
    : tempoPattern.value === 'slow_to_fast' ? RATE_MIN
    : RATE_MID;
  // 노래 시작 = t=0 keyframe (≈ 팔 내림 자세) 부터 시작. 직전 관찰 단계에서 가리기
  // 자세로 멈춰있던 viewer 가 갑자기 점프하지 않도록 즉시 reset — 첫 songTick 까지의
  // 80ms 갭에서 발생하던 visual jump 제거.
  armSnapshot.value = interpolateMotion(0);

  const audio = ensureSongAudio();
  try { audio.pause(); } catch { /* noop */ }
  try { audio.currentTime = 0; } catch { /* noop */ }
  audio.playbackRate = currentRate.value;
  audio.onended = () => {
    if (stage.value !== 'song') return;
    // 짧은 꼬리 — 아이가 멈출 0.2~0.8초 반응 시간. 가속/감속 패턴 모두 자연스럽게.
    songTailTimer = window.setTimeout(() => {
      songTailTimer = null;
      if (stage.value === 'song') setStage('observation');
    }, 200 + Math.random() * 600);
  };
  const p = audio.play();
  if (p && typeof p.catch === 'function') {
    p.catch((err: unknown) => {
      const name = (err as { name?: string } | null)?.name;
      if (name === 'AbortError' || name === 'NotAllowedError') return;
      console.warn('[mugunghwa-song] play failed', err);
    });
  }

  lastTickAt = performance.now();
  lastRandomChangeAt = lastTickAt;
  songTimer = window.setInterval(songTick, TICK_MS);
}

function stopSongStage(): void {
  if (songTimer !== null) {
    window.clearInterval(songTimer);
    songTimer = null;
  }
  if (songTailTimer !== null) {
    window.clearTimeout(songTailTimer);
    songTailTimer = null;
  }
  if (songAudio) {
    songAudio.onended = null;
    try { songAudio.pause(); } catch { /* noop */ }
    try { songAudio.currentTime = 0; } catch { /* noop */ }
  }
  songProgressRatio.value = 0;
}

function songTick(): void {
  const audio = songAudio;
  if (!audio) return;
  const now = performance.now();
  lastTickAt = now;

  // 진행률 — duration 이 metadata 로딩 전엔 NaN 이므로 가드.
  const dur = audio.duration;
  if (Number.isFinite(dur) && dur > 0) {
    songProgressRatio.value = Math.min(1, audio.currentTime / dur);
  }

  // 가리기 모션 정방향 — audio progress 에 lock 된 motion 시간으로 keyframe 보간.
  // audio.playbackRate 가 동적으로 변하면 audio.currentTime 도 같은 속도로 변하므로
  // motion 도 자동으로 같은 tempo 로 재생됨.
  if (motion.value) {
    armSnapshot.value = interpolateMotion(motion.value.duration_s * songProgressRatio.value);
  }

  // 패턴별 rate. slow_to_fast / fast_to_slow 는 **quintic** 커브 (t⁵) — 실제 무궁화꽃이
  // 피었습니다 놀이의 술래 가락은 "무우구웅화 꼬오치이" 늘어진 슬로우모로 끌다 끝에 가서
  // "피었습니다!" 휘몰아치는 형태. 선형 ramp 는 중간부터 이미 보통 속도가 돼버려서
  // 슬로우모 느낌이 안 남. 5제곱 곡선이면 t=0.7 까지 rate < 0.75× 로 늘어진 채 유지되고,
  // 마지막 ~25% 구간에서 가속해 RATE_MAX 에 도달.
  //   t=0.50 → rate ≈ 0.46  (거의 RATE_MIN — 늘어진 슬로우모)
  //   t=0.70 → rate ≈ 0.74  (여전히 느림)
  //   t=0.85 → rate ≈ 1.29
  //   t=1.00 → rate = RATE_MAX
  // random 은 무작위 간격으로 새 값.
  if (tempoPattern.value === 'random') {
    if (now - lastRandomChangeAt >= nextRandomRefreshMs) {
      currentRate.value = RATE_MIN + (RATE_MAX - RATE_MIN) * Math.random();
      lastRandomChangeAt = now;
      nextRandomRefreshMs = pickRandomRefreshMs();
    }
  } else {
    const t = songProgressRatio.value;
    const eased = t * t * t * t * t;  // t^5 — 슬로우 구간이 곡선의 대부분
    if (tempoPattern.value === 'slow_to_fast') {
      // 거의 RATE_MIN 유지하다 끝에서 가속.
      currentRate.value = RATE_MIN + (RATE_MAX - RATE_MIN) * eased;
    } else {
      // fast_to_slow — 대칭형. 거의 RATE_MAX 유지하다 끝에서 늘어짐.
      currentRate.value = RATE_MAX - (RATE_MAX - RATE_MIN) * eased;
    }
  }
  try { audio.playbackRate = currentRate.value; } catch { /* noop */ }
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
    p.faceUrl = undefined;
  }
  setStage('entry');
}

// 모든 등록된 친구가 도착 OR 탈락 → 자동으로 종료 단계로. entry/ready 에서는 발동 안 함.
watch([aliveCount, registeredCount], ([alive, reg]) => {
  if (
    reg > 0 && alive === 0
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

// ---- camera PIP -------------------------------------------------------------
const videoRef = ref<HTMLVideoElement | null>(null);
const expandedVideoRef = ref<HTMLVideoElement | null>(null);
const cameraReady = ref(false);
const cameraError = ref('');
const cameraExpanded = ref(false);
let cameraStream: MediaStream | null = null;

// 카메라 선택 — AttendanceCamera/IntegratedCameraPreview 와 동일 패턴.
// 기본은 외장 USB (회의실 카메라 등) 가 있으면 그 첫 후보를, 없으면 첫 video device.
// 사용자가 dropdown 으로 직접 바꿀 수 있다 — 기본 선택이 실패한 경우 (다른 앱이 점유,
// 권한 거부 등) 사용자가 다른 카메라로 즉시 전환 가능.
const cameras = ref<MediaDeviceInfo[]>([]);
const selectedDeviceId = ref<string>('');
const hasCameras = computed(() => cameras.value.length > 0);

// 자연 촬영 — 진행 단계(노래/관찰/탈락 대기)에서 PIP 비디오 위에 5fps 추론을 얹어
// happy/sad 표정 캡처 → /api/photos/natural 업로드. 보고서는 같은 child_id+date 의
// 모든 photo 를 모아 AI 가 합성하므로 별도 서버 변경 불필요. OXQuiz 와 동일한 흐름.
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

function toggleCamera(): void {
  if (!cameraReady.value && !cameraError.value) return;
  cameraExpanded.value = !cameraExpanded.value;
}

// 진입 (얼굴 매칭) + 준비 (위치 확인) 단계에서 자동 확대. 노래 시작 이전엔 교사가
// 카메라로 누가 들어왔는지 / 어디 서 있는지 봐야 하므로 PIP 보다 큰 화면이 필요.
const STAGES_WITH_AUTO_CAMERA: Stage[] = ['entry', 'ready'];
watch(stage, (s, prev) => {
  const wantsCamera = STAGES_WITH_AUTO_CAMERA.includes(s);
  const wasCamera = !!prev && STAGES_WITH_AUTO_CAMERA.includes(prev);
  if (wantsCamera) cameraExpanded.value = true;
  else if (wasCamera) cameraExpanded.value = false;
});

// 확대 모달의 video 에 stream attach. 모달이 열렸을 때 + stream 이 준비됐을 때 둘 다
// 필요하므로 두 신호를 같이 본다 — 어느 쪽이 늦게 도착해도 한 번은 attach 가 실행됨.
// v-if 로 element 가 매번 새로 생기므로 srcObject 가 null 일 때만 세팅 (재진입 안전).
watch([cameraExpanded, cameraReady], async ([expanded, ready]) => {
  if (!expanded || !ready || !cameraStream) return;
  await nextTick();
  const el = expandedVideoRef.value;
  if (el && !el.srcObject) {
    el.srcObject = cameraStream;
    try { await el.play(); } catch { /* noop */ }
  }
});

async function listCameras(): Promise<void> {
  try {
    let devs = await navigator.mediaDevices.enumerateDevices();
    if (devs.filter((d) => d.kind === 'videoinput').every((d) => !d.label)) {
      // 라벨이 비어 있으면 권한 트리거 후 다시 enumerate.
      try {
        const tmp = await navigator.mediaDevices.getUserMedia({ video: true });
        tmp.getTracks().forEach((t) => t.stop());
      } catch {
        /* 권한 거부해도 enumerate 는 가능 (라벨 빈 채로) */
      }
      devs = await navigator.mediaDevices.enumerateDevices();
    }
    cameras.value = devs.filter((d) => d.kind === 'videoinput');
    const stillValid = cameras.value.some((c) => c.deviceId === selectedDeviceId.value);
    if (!selectedDeviceId.value || !stillValid) {
      // 기본은 외장 USB — 무궁화 놀이에선 노트북 내장 카메라보다 큰 외장이 보통 더 적합.
      const ext = await pickExternalCamera();
      selectedDeviceId.value = ext?.deviceId ?? cameras.value[0]?.deviceId ?? '';
    }
  } catch (e) {
    cameraError.value = `카메라 목록 실패: ${e instanceof Error ? e.message : String(e)}`;
  }
}

async function setupCamera(): Promise<void> {
  cameraError.value = '';
  if (!selectedDeviceId.value) {
    await listCameras();
  }
  if (!selectedDeviceId.value) {
    cameraError.value = '사용 가능한 카메라가 없어요';
    return;
  }
  try {
    cameraStream = await navigator.mediaDevices.getUserMedia({
      // 얼굴 인식이 작은 얼굴도 잡을 수 있도록 640x480 로. PIP CSS 가 축소 표시.
      video: {
        deviceId: { exact: selectedDeviceId.value },
        width: { ideal: 640 },
        height: { ideal: 480 },
      },
      audio: false,
    });
    if (videoRef.value) {
      videoRef.value.srcObject = cameraStream;
      await videoRef.value.play();
      cameraReady.value = true;
      emotionCapture.attach(videoRef.value);
    }
  } catch (e) {
    cameraError.value = (e as Error).message || '카메라 접근 실패';
  }
}

async function restartStream(): Promise<void> {
  // device 변경 시 — emotion capture detach + 기존 track stop → 새 device 로 재시작.
  emotionCapture.detach();
  if (cameraStream) {
    cameraStream.getTracks().forEach((t) => t.stop());
    cameraStream = null;
  }
  cameraReady.value = false;
  // expanded 모달의 video element 도 srcObject 가 무효해지므로 다음 watch 사이클에서 재 attach.
  if (expandedVideoRef.value) expandedVideoRef.value.srcObject = null;
  await setupCamera();
}

async function onCameraChange(): Promise<void> {
  await restartStream();
}

async function rescanCameras(): Promise<void> {
  await listCameras();
}

let deviceChangeDebounce: number | null = null;
function scheduleListCamerasOnDeviceChange(): void {
  if (deviceChangeDebounce !== null) {
    window.clearTimeout(deviceChangeDebounce);
  }
  deviceChangeDebounce = window.setTimeout(() => {
    deviceChangeDebounce = null;
    void listCameras();
  }, 400);
}

function teardownCamera(): void {
  emotionCapture.detach();
  if (cameraStream) {
    cameraStream.getTracks().forEach((t) => t.stop());
    cameraStream = null;
  }
  cameraReady.value = false;
}

// ---- face recognition (tracker + identity cache) ---------------------------
// 모든 단계 (entry / observation / eliminationWait) 가 동일한 detector + tracker +
// identity cache 파이프라인을 공유한다. detector loop 는 entry 진입 시 시작돼
// end 단계에서 종료되며, 그 사이에는 latestTracks 와 identityCache 가 항상 최신.
const recognitionActive = ref(false);

const tracker = useFaceTracker();
let latestTracks: TrackedFace[] = [];

const identityCache = useFaceIdentityCache({
  stableFramesRequired: 5,
  identify: async (tracks): Promise<IdentityResult[]> => identifyTracks(tracks),
});

const detector = useFaceDetector({
  onDetections: (faces) => {
    latestTracks = tracker.update(faces.map((f) => ({ bbox: f.bbox })));
    void identityCache.feed(latestTracks).then(() => {
      if (stage.value === 'entry') applyEntryBindings();
    });
  },
});

async function captureFullFrame(): Promise<Blob | null> {
  const v = videoRef.value;
  if (!v || v.readyState < 2) return null;
  const canvas = document.createElement('canvas');
  canvas.width = v.videoWidth;
  canvas.height = v.videoHeight;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  ctx.drawImage(v, 0, 0);
  return new Promise((resolve) => canvas.toBlob((b) => resolve(b), 'image/jpeg', 0.9));
}

function cropFaceDataUrl(bitmap: ImageBitmap, bbox: number[]): string {
  // bbox = [x1, y1, x2, y2] in source-pixel coords. 15% 패딩으로 머리/얼굴 좀 넉넉히.
  const [x1, y1, x2, y2] = bbox;
  const w = x2 - x1;
  const h = y2 - y1;
  const padX = w * 0.15;
  const padY = h * 0.15;
  const sx = Math.max(0, x1 - padX);
  const sy = Math.max(0, y1 - padY);
  const sw = Math.min(bitmap.width - sx, w + padX * 2);
  const sh = Math.min(bitmap.height - sy, h + padY * 2);
  // 썸네일 128 정사각으로 cover-crop. 디스플레이도 원형 아바타.
  const target = 128;
  const canvas = document.createElement('canvas');
  canvas.width = target;
  canvas.height = target;
  const ctx = canvas.getContext('2d');
  if (!ctx) return '';
  // 종횡비 보존하며 cover (가운데 정렬).
  const scale = Math.max(target / sw, target / sh);
  const drawW = sw * scale;
  const drawH = sh * scale;
  const dx = (target - drawW) / 2;
  const dy = (target - drawH) / 2;
  ctx.drawImage(bitmap, sx, sy, sw, sh, dx, dy, drawW, drawH);
  return canvas.toDataURL('image/jpeg', 0.85);
}

async function identifyTracks(tracks: TrackedFace[]): Promise<IdentityResult[]> {
  const video = videoRef.value;
  if (!video || video.readyState < 2) return [];
  // crop bitmap 도 같이 만들어 register 시 썸네일 즉시 확보.
  let bitmap: ImageBitmap | null = null;
  try {
    const fullBlob = await captureFullFrame();
    if (fullBlob) bitmap = await createImageBitmap(fullBlob);
  } catch { /* noop */ }
  const form = new FormData();
  const trackOrder: TrackedFace[] = [];
  for (const t of tracks) {
    const blob = await cropTrack(video, t.bbox);
    if (!blob) continue;
    form.append('files', blob, `track-${t.trackId}.jpg`);
    trackOrder.push(t);
  }
  if (trackOrder.length === 0) { bitmap?.close?.(); return []; }
  try {
    const res = await fetch('/api/attendance/recognize-crops', {
      method: 'POST',
      headers: { 'X-Device-Token': DEVICE_TOKEN },
      body: form,
    });
    if (!res.ok) { bitmap?.close?.(); return []; }
    const body = await res.json() as {
      matches: Array<{ matched: boolean; child_id: number | null; child_name: string | null; distance: number | null }>;
    };
    const results: IdentityResult[] = body.matches.map((m, i) => ({
      trackId: trackOrder[i].trackId,
      childId: m.matched ? m.child_id : null,
      childName: m.matched ? m.child_name : null,
      distance: m.distance,
    }));
    // bitmap + bbox 로 썸네일 즉시 등록 (registered 토글은 applyEntryBindings 에서).
    if (bitmap) {
      for (let i = 0; i < results.length; i++) {
        const r = results[i];
        const t = trackOrder[i];
        if (!r.childId) continue;
        const p = participants.value.find((x) => x.id === r.childId);
        if (p && !p.faceUrl) {
          try { p.faceUrl = cropFaceDataUrl(bitmap, t.bbox); } catch { /* noop */ }
        }
      }
      bitmap.close?.();
    }
    return results;
  } catch {
    bitmap?.close?.();
    return [];
  }
}

function applyEntryBindings(): void {
  for (const t of latestTracks) {
    const childId = identityCache.getChildId(t.trackId);
    if (childId == null) continue;
    const p = participants.value.find((x) => x.id === childId);
    if (!p || p.registered) continue;
    p.registered = true;
    pushToast(`${p.name} 등록!`, p.faceUrl);
    void tts.speak(`${p.name} 등록 완료`).catch(() => { /* TTS off */ });
  }
}

async function cropTrack(video: HTMLVideoElement, bbox: Bbox): Promise<Blob | null> {
  const [x1, y1, x2, y2] = bbox;
  const padX = (x2 - x1) * 0.15;
  const padY = (y2 - y1) * 0.15;
  const sx = Math.max(0, x1 - padX);
  const sy = Math.max(0, y1 - padY);
  const sw = Math.min(video.videoWidth - sx, (x2 - x1) + padX * 2);
  const sh = Math.min(video.videoHeight - sy, (y2 - y1) + padY * 2);
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(sw);
  canvas.height = Math.round(sh);
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  ctx.drawImage(video, sx, sy, sw, sh, 0, 0, sw, sh);
  return new Promise((resolve) => canvas.toBlob((b) => resolve(b), 'image/jpeg', 0.85));
}

let detectorRafId: number | null = null;

function startDetectorLoop(): void {
  if (detectorRafId !== null) return;
  detector.start();
  recognitionActive.value = true;
  const tick = async (): Promise<void> => {
    if (videoRef.value && videoRef.value.readyState >= 2) {
      try { await detector.send(videoRef.value); } catch { /* noop */ }
    }
    detectorRafId = requestAnimationFrame(() => void tick());
  };
  detectorRafId = requestAnimationFrame(() => void tick());
}

function stopDetectorLoop(): void {
  if (detectorRafId !== null) {
    cancelAnimationFrame(detectorRafId);
    detectorRafId = null;
  }
  detector.close();
  tracker.reset();
  identityCache.reset();
  latestTracks = [];
  recognitionActive.value = false;
}

watch(stage, (s, prev) => {
  // detector 루프는 entry 부터 시작, end 시 정지. observation 에선 entry 의 캐시를
  // 그대로 사용해야 하므로 루프 유지.
  if (s === 'entry' && prev !== 'entry') startDetectorLoop();
  if (s === 'end') stopDetectorLoop();
});

// ---- motion detection during 관찰 ------------------------------------------
// 가벼운 binary 알람: 관찰 진입 시점 프레임을 baseline 으로 캡처 → 8Hz 로 현재 프레임과의
// SAD (Sum of Absolute Differences, 그레이스케일 다운샘플 160x90) 비교 → 임계 초과 시
// 카메라 PIP 빨강 플래시 + "움직였어요!" TTS (쿨다운). 누가 움직였는지는 식별하지 않고
// 교사가 카드의 ✕ 버튼으로 직접 탈락 처리. 추후 YOLO-Pose + ByteTrack 으로 per-kid 자동화 예정.
const MOTION_DOWNSAMPLE_W = 160;
const MOTION_DOWNSAMPLE_H = 90;
// 평균 픽셀 변화율 임계 — 0..1 범위 (255 정규화 후 평균). 작을수록 민감.
const MOTION_THRESHOLD = 0.015;
const MOTION_TICK_MS = 125;          // 8 Hz
const MOTION_TTS_COOLDOWN_MS = 2000;

const motionDetected = ref(false);
let motionTimer: number | null = null;
let motionBaseline: ImageData | null = null;
let motionCanvas: HTMLCanvasElement | null = null;
let motionCtx: CanvasRenderingContext2D | null = null;
let lastMotionAnnouncementAt = 0;
// 관찰 진입 시 캡처한 각 등록 아이의 bbox 중심점 — 이후 motion 이벤트마다 비교.
const observationBasePositions = new Map<number, { x: number; y: number }>();
// recognize-multi inflight 가드 — 모션 이벤트가 빠르게 연속될 때 서버 중복 호출 차단.
let moverProbeInflight = false;
// 픽셀 단위 변위 임계. 640x480 기준 ~1.6%. strict 이상이면 즉시 탈락.
const MOVER_DISPLACEMENT_PX = 10;
// loose fallback — strict 미만이지만 motion 이 분명히 발생했을 때 "가장 많이 움직인 한 명"을
// 탈락시키기 위한 최소 변위. 노이즈와 진짜 움직임을 구분.
const MOVER_DISPLACEMENT_LOOSE_PX = 4;

function ensureMotionCanvas(): void {
  if (motionCanvas) return;
  motionCanvas = document.createElement('canvas');
  motionCanvas.width = MOTION_DOWNSAMPLE_W;
  motionCanvas.height = MOTION_DOWNSAMPLE_H;
  motionCtx = motionCanvas.getContext('2d', { willReadFrequently: true });
}

function captureMotionFrame(): ImageData | null {
  if (!videoRef.value || videoRef.value.readyState < 2) return null;
  ensureMotionCanvas();
  if (!motionCtx) return null;
  motionCtx.drawImage(videoRef.value, 0, 0, MOTION_DOWNSAMPLE_W, MOTION_DOWNSAMPLE_H);
  return motionCtx.getImageData(0, 0, MOTION_DOWNSAMPLE_W, MOTION_DOWNSAMPLE_H);
}

function frameDiffNormalized(a: ImageData, b: ImageData): number {
  const aData = a.data;
  const bData = b.data;
  // RGBA 4-byte stride → 그레이스케일은 (R+G+B)/3 평균
  let sad = 0;
  const n = aData.length;
  for (let i = 0; i < n; i += 4) {
    const ga = (aData[i] + aData[i + 1] + aData[i + 2]) / 3;
    const gb = (bData[i] + bData[i + 1] + bData[i + 2]) / 3;
    sad += Math.abs(ga - gb);
  }
  return sad / ((n / 4) * 255);
}

function captureObservationBaseline(): void {
  // 관찰 진입 순간의 tracker bbox 중심을 child_id 별로 기록. 식별된 트랙만 baseline 으로
  // 쓰고, 누락된 child 는 probeMoversAndMaybeEliminate 가 다음 frame 에서 지연 채움.
  observationBasePositions.clear();
  for (const t of latestTracks) {
    const childId = identityCache.getChildId(t.trackId);
    if (childId == null) continue;
    const [x1, y1, x2, y2] = t.bbox;
    observationBasePositions.set(childId, { x: (x1 + x2) / 2, y: (y1 + y2) / 2 });
  }
}

function probeMoversAndMaybeEliminate(): void {
  if (moverProbeInflight) return;  // 짧은 재진입 차단 (TTS race)
  if (stage.value !== 'observation') return;
  moverProbeInflight = true;
  try {
    // 등록된 아이 중 baseline 누락된 것이 있으면 지연 baseline (이번 frame 의 bbox 로).
    for (const t of latestTracks) {
      const childId = identityCache.getChildId(t.trackId);
      if (childId == null) continue;
      if (observationBasePositions.has(childId)) continue;
      const [x1, y1, x2, y2] = t.bbox;
      observationBasePositions.set(childId, { x: (x1 + x2) / 2, y: (y1 + y2) / 2 });
    }

    type Candidate = { id: number; name: string; dist: number };
    const candidates: Candidate[] = [];
    for (const t of latestTracks) {
      const childId = identityCache.getChildId(t.trackId);
      if (childId == null) continue;
      const base = observationBasePositions.get(childId);
      if (!base) continue;
      const [x1, y1, x2, y2] = t.bbox;
      const cx = (x1 + x2) / 2;
      const cy = (y1 + y2) / 2;
      const dist = Math.hypot(cx - base.x, cy - base.y);
      const p = participants.value.find((x) => x.id === childId);
      if (!p || !p.registered || p.eliminated) continue;
      candidates.push({ id: childId, name: p.name, dist });
    }
    if (candidates.length === 0) return;

    let toEliminate = candidates.filter((c) => c.dist >= MOVER_DISPLACEMENT_PX);
    if (toEliminate.length === 0) {
      const maxDist = Math.max(...candidates.map((c) => c.dist));
      if (maxDist >= MOVER_DISPLACEMENT_LOOSE_PX) {
        toEliminate = candidates.filter((c) => c.dist === maxDist);
      }
    }
    if (toEliminate.length === 0) {
      const maxDist = candidates.length
        ? Math.max(...candidates.map((c) => c.dist))
        : 0;
      pushToast(`움직임 감지 — 식별 실패 (최대 ${maxDist.toFixed(0)}px)`);
      return;
    }

    for (const { id } of toEliminate) {
      const p = participants.value.find((x) => x.id === id);
      if (!p) continue;
      p.eliminated = true;
      if (p.reached) p.reached = false;
    }
    const names = toEliminate.map((m) => m.name).join(', ');
    pushToast(`${names} 어린이 탈락했습니다`);
    void tts.speak(`${names} 어린이 탈락했습니다`).catch(() => { /* noop */ });
    setStage('eliminationWait');
  } finally {
    moverProbeInflight = false;
  }
}

function startMotionDetection(): void {
  stopMotionDetection();
  // baseline 즉시 캡처. 비디오 readyState 가 아직 낮을 수 있으니 첫 tick 에서 재시도.
  motionBaseline = captureMotionFrame();
  motionDetected.value = false;
  // 등록 아이들의 bbox 중심 baseline — tracker 캐시에서 즉시 동기로 채움.
  captureObservationBaseline();
  motionTimer = window.setInterval(() => {
    if (stage.value !== 'observation') return;
    if (!motionBaseline) {
      motionBaseline = captureMotionFrame();
      return;
    }
    const cur = captureMotionFrame();
    if (!cur) return;
    const diff = frameDiffNormalized(motionBaseline, cur);
    if (diff > MOTION_THRESHOLD) {
      motionDetected.value = true;
      const now = performance.now();
      if (now - lastMotionAnnouncementAt > MOTION_TTS_COOLDOWN_MS) {
        lastMotionAnnouncementAt = now;
        // tracker bbox + identity cache 로 누가 움직였는지 식별 → 자동 탈락 + 전이 시도.
        // 식별 실패하면 카메라 flash 만 남고 교사가 직접 ✕ 로 처리.
        probeMoversAndMaybeEliminate();
      }
    } else {
      motionDetected.value = false;
    }
  }, MOTION_TICK_MS);
}

function stopMotionDetection(): void {
  if (motionTimer !== null) {
    window.clearInterval(motionTimer);
    motionTimer = null;
  }
  motionBaseline = null;
  motionDetected.value = false;
  observationBasePositions.clear();
  moverProbeInflight = false;
}

watch(stage, (s, prev) => {
  if (s === 'observation') startMotionDetection();
  else if (prev === 'observation') stopMotionDetection();
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

// ---- 탈락 대기 — 탈락한 친구가 시야 밖으로 나가면 자동으로 노래 단계 재개 -------
// 식별 (recognize) 은 자세·조명·거리 영향으로 같은 사람을 잠깐 놓치기도 한다. 그래서
// "탈락 ID 가 안 보임" 한 신호만으로 advance 하면, 실제 탈락자가 여전히 화면에 있어도
// 가끔 게임이 재개되는 false negative 가 발생. 이를 보완하기 위해 신호를 두 개 OR:
//   (a) 매칭된 face 중 eliminationWaitIds 에 포함된 ID 가 발견됨 (강한 신호)
//   (b) detect 된 총 face 개수가 남아있어야 할 인원 (registered AND !eliminated) 을
//       초과 → 식별 실패하더라도 추가 사람이 화면에 있음 (= 탈락자 미퇴장)
// 또한 연속 absent 카운트를 2→3 으로 늘려 통계적 안정성 확보.
const ELIM_WAIT_POLL_MS = 1500;
const ELIM_WAIT_REQUIRED_ABSENT_CHECKS = 3;
const eliminationWaitIds = new Set<number>();
let eliminationWaitTimer: number | null = null;
let elimAbsentStreak = 0;

function eliminationWaitTick(): void {
  if (stage.value !== 'eliminationWait') return;
  if (eliminationWaitIds.size === 0) {
    // 안전망 — 새로 탈락한 아이가 없는 상태로 진입했으면 즉시 노래로 복귀
    setStage('song');
    return;
  }
  // tracker + identity cache 로 탈락자의 잔존 여부 판단. recognize 호출 없이 매 tick 즉시.
  const totalFacesDetected = latestTracks.length;
  const presentIds = new Set<number>();
  for (const t of latestTracks) {
    const cid = identityCache.getChildId(t.trackId);
    if (cid != null) presentIds.add(cid);
  }
  const matchedEliminatedVisible = Array.from(eliminationWaitIds).some(
    (id) => presentIds.has(id),
  );
  // 화면에 남아있어야 정상인 인원 — 등록됐고 탈락 안 한 아이들.
  const expectedRemaining = participants.value.filter(
    (p) => p.registered && !p.eliminated,
  ).length;
  const tooManyFaces = totalFacesDetected > expectedRemaining;
  const stillVisible = matchedEliminatedVisible || tooManyFaces;
  if (stillVisible) {
    elimAbsentStreak = 0;
  } else {
    elimAbsentStreak += 1;
    if (elimAbsentStreak >= ELIM_WAIT_REQUIRED_ABSENT_CHECKS) {
      // 모든 탈락자가 시야 밖 (식별 + face count 둘 다 만족) → 게임 계속
      setStage('song');
    }
  }
}

function startEliminationWait(): void {
  stopEliminationWait();
  eliminationWaitIds.clear();
  for (const p of participants.value) {
    if (p.registered && p.eliminated) eliminationWaitIds.add(p.id);
  }
  if (eliminationWaitIds.size === 0) {
    // 탈락 대기로 들어왔지만 사실 탈락자가 없는 케이스 — 곧장 노래 복귀
    setStage('song');
    return;
  }
  elimAbsentStreak = 0;
  pushToast('탈락한 친구는 자리에서 벗어나주세요');
  eliminationWaitTimer = window.setInterval(eliminationWaitTick, ELIM_WAIT_POLL_MS);
}

function stopEliminationWait(): void {
  if (eliminationWaitTimer !== null) {
    window.clearInterval(eliminationWaitTimer);
    eliminationWaitTimer = null;
  }
  eliminationWaitIds.clear();
  elimAbsentStreak = 0;
}

watch(stage, (s, prev) => {
  if (s === 'eliminationWait') startEliminationWait();
  else if (prev === 'eliminationWait') stopEliminationWait();
});

// 단계별 viewer 입력:
//   entry / ready / end / eliminationWait — rest snapshot (자연 하강 자세). follower WS
//     가 잔존 pose 를 들고 있어도 명시적으로 zero pose 로 덮어쓴다.
//   song — 음악 진행률에 lock 된 모션 보간 (songTick 에서 갱신)
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
  void setupCamera();
  navigator.mediaDevices.addEventListener('devicechange', scheduleListCamerasOnDeviceChange);
  // 첫 mount 시 단계가 'entry' 면 watch 가 한 번 안 돌므로 직접 확대 트리거.
  if (STAGES_WITH_AUTO_CAMERA.includes(stage.value)) cameraExpanded.value = true;
  // 마찬가지로 첫 mount 가 entry 면 detector loop 도 시작.
  if (stage.value === 'entry') startDetectorLoop();
});

onUnmounted(() => {
  stopSongStage();
  if (songAudio) {
    try { songAudio.pause(); } catch { /* noop */ }
    songAudio.src = '';
    songAudio = null;
  }
  stopDetectorLoop();
  stopMotionDetection();
  stopObservationCountdown();
  stopEliminationWait();
  stopReadyCountdown();
  if (audioContext) {
    try { void audioContext.close(); } catch { /* noop */ }
    audioContext = null;
  }
  navigator.mediaDevices.removeEventListener('devicechange', scheduleListCamerasOnDeviceChange);
  if (deviceChangeDebounce !== null) {
    window.clearTimeout(deviceChangeDebounce);
    deviceChangeDebounce = null;
  }
  teardownCamera();
});
</script>

<template>
  <Transition name="fade">
    <div class="popup-overlay">
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

            <div class="camera-pip-wrap">
              <div class="camera-picker" @click.stop>
                <select
                  v-model="selectedDeviceId"
                  :disabled="!hasCameras"
                  class="camera-picker__select"
                  aria-label="카메라 선택"
                  @change="onCameraChange"
                >
                  <option v-if="!hasCameras" disabled value="">— 카메라 없음 —</option>
                  <option v-for="c in cameras" :key="c.deviceId" :value="c.deviceId">
                    {{ c.label || `카메라 ${c.deviceId.slice(0, 8)}…` }}
                  </option>
                </select>
                <button
                  type="button"
                  class="camera-picker__rescan"
                  aria-label="카메라 다시 스캔"
                  title="카메라 다시 스캔"
                  @click="rescanCameras"
                >↻</button>
              </div>
              <div
                class="camera-pip"
                :class="{ ready: cameraReady, error: !!cameraError, motion: motionDetected, captured: emotionCapture.captured.value }"
                :title="motionDetected ? '⚠ 움직임 감지!' : (cameraError || (cameraReady ? '카메라 작동 중 (클릭으로 확대)' : '카메라 준비 중…'))"
                @click="toggleCamera"
              >
                <video ref="videoRef" muted playsinline />
                <div v-if="!cameraReady && !cameraError" class="cam-overlay">준비 중…</div>
                <div v-if="cameraError" class="cam-overlay err">⚠ {{ cameraError }}</div>
                <!-- 셔터 플래시 — 캡처 직후 1회. -->
                <div
                  v-if="emotionCapture.flashTick.value > 0"
                  :key="emotionCapture.flashTick.value"
                  class="cam-shutter"
                />
                <!-- 마지막 캡처 감정 라벨 — 짧게 표시. -->
                <div
                  v-if="emotionCapture.lastEmotion.value !== null"
                  class="cam-emotion-tag"
                  :class="`is-${emotionCapture.lastEmotion.value}`"
                >
                  📸 {{ emotionCapture.lastEmotion.value === 'happy' ? '활짝!' : '시무룩' }}
                </div>
                <!-- 라이브 HUD — armed 상태에서 얼굴 검출/감정 % 표시 (디버깅 + 사용자 피드백). -->
                <div
                  v-if="captureArmed && cameraReady && emotionCapture.ready.value && !emotionCapture.inCaptureCooldown.value"
                  class="cam-live-hud"
                  :class="{ 'has-face': emotionCapture.faceDetected.value }"
                >
                  <template v-if="!emotionCapture.faceDetected.value">얼굴 찾는 중…</template>
                  <template v-else>
                    웃음 {{ (emotionCapture.liveHappy.value * 100).toFixed(0) }}%
                    · 슬픔 {{ (emotionCapture.liveSad.value * 100).toFixed(0) }}%
                  </template>
                </div>
                <!-- 누적 캡처 수 — 사용자가 한 게임에서 몇 번 잡혔는지. -->
                <div v-if="naturalShotCount > 0" class="cam-shot-count">
                  📸 {{ naturalShotCount }}
                </div>
                <button
                  v-if="cameraReady"
                  type="button"
                  class="cam-toggle"
                  aria-label="카메라 확대"
                  @click.stop="toggleCamera"
                >⤢</button>
              </div>
            </div>

            <button type="button" class="btn-icon close-btn" aria-label="닫기" @click="close">×</button>
          </header>

          <!-- 메인: arm viewer + 노래 HUD 오버레이 -->
          <main class="main-area">
            <div class="arm-wrap">
              <OpenarmViewer
                source="follower"
                :external-snapshot="armSnapshot"
                :extra-yaw-deg="-45"
              />
              <div v-if="stage === 'song'" class="arm-overlay">
                <div class="tempo-badge" :class="`tempo-${tempoPattern}`">
                  <span class="tempo-name">{{ TEMPO_LABEL[tempoPattern] }}</span>
                  <span class="tempo-rate">{{ currentRate.toFixed(2) }}×</span>
                </div>
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

          <!-- 카메라 확대 오버레이 -->
          <Transition name="cam-fade">
            <div
              v-if="cameraExpanded && cameraReady"
              class="cam-expanded-backdrop"
              @click.self="cameraExpanded = false"
            >
              <div class="cam-expanded-card">
                <header class="cam-expanded-head">
                  <div class="cam-expanded-title">
                    <span class="rec-dot" /> 카메라 미리보기
                  </div>
                  <div class="cam-expanded-picker">
                    <select
                      v-model="selectedDeviceId"
                      :disabled="!hasCameras"
                      class="cam-expanded-select"
                      aria-label="카메라 선택"
                      @change="onCameraChange"
                    >
                      <option v-if="!hasCameras" disabled value="">— 카메라 없음 —</option>
                      <option v-for="c in cameras" :key="c.deviceId" :value="c.deviceId">
                        {{ c.label || `카메라 ${c.deviceId.slice(0, 8)}…` }}
                      </option>
                    </select>
                    <button
                      type="button"
                      class="cam-expanded-rescan"
                      aria-label="카메라 다시 스캔"
                      title="카메라 다시 스캔"
                      @click="rescanCameras"
                    >↻</button>
                  </div>
                  <button
                    type="button"
                    class="btn-icon close-btn small"
                    aria-label="카메라 축소"
                    @click="cameraExpanded = false"
                  >×</button>
                </header>
                <div class="cam-expanded-body">
                  <video ref="expandedVideoRef" muted playsinline />
                </div>
                <footer v-if="stage === 'entry'" class="cam-expanded-foot entry">
                  <div class="entry-info">
                    <div class="entry-line">
                      참가자 확인 중
                      <span v-if="recognitionActive" class="reco-dot" title="얼굴 인식 중" />
                    </div>
                    <div class="entry-sub">
                      카메라에 보이는 친구는 자동으로 등록돼요.
                      <strong>{{ registeredCount }}</strong> / {{ participants.length }} 명 등록됨
                    </div>
                  </div>
                  <button
                    type="button"
                    class="btn-start"
                    @click="setStage('ready')"
                  >시작</button>
                </footer>
                <footer v-else-if="stage === 'ready'" class="cam-expanded-foot ready">
                  <div class="entry-info">
                    <div class="entry-line">준비 — 출발선 뒤로 멀리 가서 자리잡으세요</div>
                    <div class="entry-sub">
                      <strong class="ready-num">{{ readyCountdownSec }}</strong> 초 후 자동 시작
                    </div>
                  </div>
                  <button
                    type="button"
                    class="btn-start"
                    @click="setStage('song')"
                  >건너뛰기</button>
                </footer>
                <p v-else class="cam-expanded-hint">
                  관찰 단계 중에는 이 화면으로 누가 움직이는지 확인할 수 있어요.
                </p>
              </div>
            </div>
          </Transition>

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
  grid-template-columns: auto 1fr auto auto;
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

.camera-pip-wrap {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 4px;
  flex-shrink: 0;
  width: 160px;
}
.camera-picker {
  display: flex;
  align-items: center;
  gap: 4px;
}
.camera-picker__select {
  flex: 1;
  min-width: 0;
  padding: 3px 6px;
  border-radius: 6px;
  border: 1px solid #cbd5e1;
  font-size: 11px;
  font-family: inherit;
  background: white;
  color: #1f3a4d;
  cursor: pointer;
}
.camera-picker__select:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.camera-picker__rescan {
  flex-shrink: 0;
  background: white;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  padding: 2px 6px;
  cursor: pointer;
  font-size: 12px;
  font-family: inherit;
  color: #5b7a8c;
}
.camera-picker__rescan:hover { background: #f1f5f9; }

.camera-pip {
  position: relative;
  width: 160px;
  height: 90px;
  border-radius: 12px;
  overflow: hidden;
  background: #0f172a;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.18);
  border: 2px solid #cbd5e1;
  flex-shrink: 0;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
  cursor: pointer;
}
.camera-pip.ready:hover {
  box-shadow: 0 4px 14px rgba(22, 163, 74, 0.35);
}
.cam-toggle {
  position: absolute;
  bottom: 4px;
  right: 4px;
  width: 22px;
  height: 22px;
  border-radius: 6px;
  border: none;
  background: rgba(0, 0, 0, 0.65);
  color: white;
  font-size: 13px;
  font-weight: 700;
  line-height: 1;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-family: inherit;
}
.cam-toggle:hover { background: rgba(0, 0, 0, 0.85); }
.camera-pip.ready { border-color: #16a34a; }
.camera-pip.error { border-color: #b91c1c; }
.camera-pip.motion {
  border-color: #dc2626;
  animation: motion-flash 0.55s ease-in-out infinite;
}
.camera-pip.captured { box-shadow: 0 0 0 3px #f0c042 inset; }

.cam-shutter {
  position: absolute;
  inset: 0;
  background: white;
  opacity: 0;
  pointer-events: none;
  animation: cam-shutter-flash 0.6s ease-out;
  animation-iteration-count: 1;
}
@keyframes cam-shutter-flash {
  0%   { opacity: 0; }
  10%  { opacity: 0.95; }
  100% { opacity: 0; }
}
.cam-emotion-tag {
  position: absolute;
  bottom: 4px;
  left: 4px;
  font-size: 10px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 999px;
  color: white;
  pointer-events: none;
}
.cam-emotion-tag.is-happy { background: rgba(45, 139, 87, 0.92); }
.cam-emotion-tag.is-sad   { background: rgba(193, 69, 69, 0.92); }
.cam-live-hud {
  position: absolute;
  left: 4px;
  right: 4px;
  bottom: 22px;
  z-index: 2;
  font-size: 9px;
  font-weight: 600;
  padding: 2px 4px;
  border-radius: 4px;
  color: rgba(255, 255, 255, 0.95);
  background: rgba(30, 45, 58, 0.7);
  pointer-events: none;
  line-height: 1.2;
  text-align: center;
}
.cam-live-hud.has-face { background: rgba(45, 110, 75, 0.8); }
.cam-shot-count {
  position: absolute;
  top: 4px;
  left: 4px;
  font-size: 10px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 6px;
  color: white;
  background: rgba(0, 0, 0, 0.6);
  pointer-events: none;
}

@keyframes motion-flash {
  0%, 100% {
    box-shadow: 0 0 0 0 rgba(220, 38, 38, 0.65), 0 2px 8px rgba(15, 23, 42, 0.18);
  }
  50% {
    box-shadow: 0 0 0 12px rgba(220, 38, 38, 0), 0 4px 14px rgba(220, 38, 38, 0.5);
  }
}
.camera-pip video {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transform: scaleX(-1);
}
.cam-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #cbd5e1;
  font-size: 11px;
  font-weight: 600;
  text-align: center;
  padding: 8px;
}
.cam-overlay.err { color: #fecaca; background: rgba(127, 29, 29, 0.85); }
.cam-badge {
  position: absolute;
  top: 4px;
  left: 6px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 6px;
  background: rgba(0, 0, 0, 0.65);
  color: white;
  font-size: 10px;
  font-weight: 700;
  border-radius: 4px;
  letter-spacing: 0.05em;
}
.rec-dot {
  width: 6px;
  height: 6px;
  background: #ef4444;
  border-radius: 50%;
  animation: rec-blink 1s ease-in-out infinite;
}
@keyframes rec-blink { 50% { opacity: 0.25; } }

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

/* ---------------- camera expanded overlay ---------------- */
.cam-expanded-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.72);
  backdrop-filter: blur(4px);
  z-index: 80;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
.cam-expanded-card {
  background: #0f172a;
  border-radius: 20px;
  overflow: hidden;
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.5);
  display: flex;
  flex-direction: column;
  width: min(720px, 92vw);
  max-height: 92dvh;
}
.cam-expanded-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  background: rgba(0, 0, 0, 0.4);
}
.cam-expanded-title {
  color: white;
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 0.04em;
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.cam-expanded-picker {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  max-width: 320px;
  margin: 0 12px;
}
.cam-expanded-select {
  flex: 1;
  min-width: 0;
  padding: 6px 8px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.25);
  background: rgba(255, 255, 255, 0.92);
  color: #1f3a4d;
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
}
.cam-expanded-select:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.cam-expanded-rescan {
  flex-shrink: 0;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid rgba(255, 255, 255, 0.25);
  border-radius: 8px;
  padding: 4px 10px;
  cursor: pointer;
  font-size: 14px;
  font-family: inherit;
  color: #5b7a8c;
}
.cam-expanded-rescan:hover { background: white; }
.cam-expanded-body {
  flex: 1;
  background: #000;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 0;
}
.cam-expanded-body video {
  width: 100%;
  height: auto;
  max-height: 70dvh;
  object-fit: contain;
  transform: scaleX(-1);
  display: block;
}
.cam-expanded-hint {
  margin: 0;
  padding: 10px 16px 14px;
  font-size: 12px;
  color: #cbd5e1;
  text-align: center;
  background: rgba(0, 0, 0, 0.4);
}
.cam-expanded-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 18px;
  background: rgba(0, 0, 0, 0.55);
}
.entry-info {
  color: white;
  text-align: left;
  min-width: 0;
}
.entry-line {
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 0.02em;
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.reco-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #4ade80;
  box-shadow: 0 0 0 0 rgba(74, 222, 128, 0.7);
  animation: reco-pulse 1.4s ease-out infinite;
}
@keyframes reco-pulse {
  0%   { box-shadow: 0 0 0 0 rgba(74, 222, 128, 0.7); }
  70%  { box-shadow: 0 0 0 8px rgba(74, 222, 128, 0); }
  100% { box-shadow: 0 0 0 0 rgba(74, 222, 128, 0); }
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

.cam-fade-enter-active, .cam-fade-leave-active { transition: opacity 0.22s ease; }
.cam-fade-enter-from, .cam-fade-leave-to { opacity: 0; }

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
  .camera-pip-wrap { width: 120px; }
  .camera-pip { width: 120px; height: 68px; }
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
