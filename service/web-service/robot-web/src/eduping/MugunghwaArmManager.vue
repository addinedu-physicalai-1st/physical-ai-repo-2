<script setup lang="ts">
/**
 * 무궁화 율동 등록 — 무궁화꽃이 피었습니다 (SR-PLAY-004) 의 양팔 가리기 모션 단일 녹화.
 *
 * 게임 중에는 같은 모션을 정방향 (가리기) + 역재생 (떼기) 으로 두 번 사용한다 — 별도
 * 떼기 녹화 없음. 저장 경로 shared/openarm_mugunghwa/motion.yaml. REST 경로
 * /api/eduping/mugunghwa/motion/{record/start,record/stop,play}.
 *
 * 박자 가이드 — `public/sounds/yeonghui_mugunghwa.mp3` (자연 속도, ~4.6s). 런타임
 * `audio.playbackRate = REFERENCE_PLAYBACK_RATE` 로 일정한 느린 속도 재생.
 * 등록 단계는 단일 템포여야 한다 — 교사가 한 박자에 맞춰 팔 동작을 녹화하면, 게임의
 * tempo pattern (느렸다가 빠르게 등) 이 그 한 녹화를 동적으로 변속해서 쓴다.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { useModeStore } from '@/stores/mode';
import { useEdupingStateWs } from '@/composables/useEdupingStateWs';
import Icon from '@/common/Icon.vue';
import OpenarmViewer from './OpenarmViewer.vue';
import RecorderControls from './RecorderControls.vue';

const MOTION_NAME = 'motion';
const REFERENCE_TTS_TEXT = '무궁화 꼬치 피었습니다';
const REFERENCE_CUE_URL = '/sounds/yeonghui_mugunghwa.mp3';
const REFERENCE_PLAYBACK_RATE = 0.8;  // yeonghui mp3 가 자연 속도부터 이미 느려서 0.45 는 과도 — 0.8 로 상향

const referenceDurationS = ref(0);
const referenceEffectiveDurationS = computed(
  () => referenceDurationS.value / REFERENCE_PLAYBACK_RATE,
);
let referenceAudio: HTMLAudioElement | null = null;
// pause() 직후 play() 가 일으키는 AbortError 를 잡으려면 currently-pending play 토큰을
// 들고 있어야 함. 새 play 가 시작되면 이전 토큰은 stale 처리해 .catch 가 silently 무시.
let playToken = 0;

function ensureReferenceAudio(): HTMLAudioElement {
  if (referenceAudio) return referenceAudio;
  const audio = new Audio(REFERENCE_CUE_URL);
  audio.preload = 'auto';
  audio.playbackRate = REFERENCE_PLAYBACK_RATE;
  audio.addEventListener('loadedmetadata', () => {
    if (Number.isFinite(audio.duration)) referenceDurationS.value = audio.duration;
  });
  referenceAudio = audio;
  return audio;
}

function startReferenceTts(): void {
  const audio = ensureReferenceAudio();
  const myToken = ++playToken;
  try { audio.pause(); } catch { /* noop */ }
  try { audio.currentTime = 0; } catch { /* noop */ }
  audio.playbackRate = REFERENCE_PLAYBACK_RATE;
  const p = audio.play();
  if (p && typeof p.catch === 'function') {
    p.catch((err: unknown) => {
      if (playToken !== myToken) return;
      const name = (err as { name?: string } | null)?.name;
      if (name === 'AbortError' || name === 'NotAllowedError') return;
      console.warn('[yeonghui-cue] play failed', err);
    });
  }
}

function stopReferenceTts(): void {
  if (!referenceAudio) return;
  playToken++;
  try {
    referenceAudio.pause();
    referenceAudio.currentTime = 0;
  } catch { /* noop */ }
}

function disposeReferenceAudio(): void {
  if (!referenceAudio) return;
  try { referenceAudio.pause(); } catch { /* noop */ }
  referenceAudio.src = '';
  referenceAudio = null;
}

interface MotionMeta {
  duration_s?: number;
  keyframe_count?: number;
  recorded_at?: string;
  sample_hz?: number;
}

const mode = useModeStore();
const stateWs = useEdupingStateWs();
stateWs.start();

const meta = ref<MotionMeta | null>(null);
const loading = ref(false);
const error = ref('');

const isPlaying = ref(false);
let playbackTimer: number | null = null;
function onPlayed(payload: { ok: boolean; duration_s: number }): void {
  if (!payload.ok) return;
  if (playbackTimer !== null) window.clearTimeout(playbackTimer);
  isPlaying.value = true;
  const ms = Math.max(200, Math.round(payload.duration_s * 1000));
  mode.setEmotionTransient('sleep', ms);
  playbackTimer = window.setTimeout(() => {
    isPlaying.value = false;
    playbackTimer = null;
  }, ms);
}

async function refresh(): Promise<void> {
  loading.value = true;
  error.value = '';
  try {
    const res = await fetch('/api/eduping/mugunghwa');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    meta.value = (json.motion as MotionMeta | null) ?? null;
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}

function close(): void {
  mode.setMode('대기');
}

onMounted(() => {
  void refresh();
  // mount 시 미리 fetch 해 두면 녹화 시작 시점에 바로 재생 — 첫 로딩 지연 회피.
  void ensureReferenceAudio();
});
onBeforeUnmount(() => {
  stopReferenceTts();
  disposeReferenceAudio();
});
</script>

<template>
  <div class="mugung-mgr">
    <header class="bar">
      <h2>무궁화 율동 등록</h2>
      <button type="button" class="btn-close" @click="close">닫기</button>
    </header>

    <div v-if="!stateWs.leaderActive.value" class="leader-warning">
      <Icon name="alert" :size="18" />
      <strong>리더 디바이스가 연결되어 있지 않습니다.</strong>
      녹화·재생을 사용하려면 리더 디바이스를 먼저 켜주세요 —
      <code>scripts/device-eduping-leader.sh 3</code>
    </div>

    <div class="grid">
      <div class="viewer">
        <OpenarmViewer :source="isPlaying ? 'follower' : 'leader'" />
      </div>

      <aside class="side">
        <section class="slot-card">
          <h3>
            <Icon name="play" :size="18" />
            가리기 모션
          </h3>
          <p class="hint">
            노래 단계 시작과 함께 재생할 양팔 가리기 모션입니다. <br />
            게임 중에는 이 한 녹화로 <strong>가리기</strong> (정방향) →
            <strong>떼기</strong> (역재생) 를 모두 처리합니다.
          </p>
          <p class="tts-hint">
            <Icon name="music" :size="14" />
            <span class="tts-hint-text">
              녹화·재생 시 <strong>"{{ REFERENCE_TTS_TEXT }}"</strong> 박자 가이드<span
                v-if="referenceDurationS > 0"
              > (<strong>{{ Math.round(REFERENCE_PLAYBACK_RATE * 100) }}%</strong> 속도,
              <strong>{{ referenceEffectiveDurationS.toFixed(1) }}s</strong>)</span>
              가 재생됩니다. 이 박자에 맞춰 양팔로 눈을 가려주세요 —
              게임에서는 이 한 녹화를 빠르게/느리게 변속해 씁니다.
            </span>
          </p>

          <div v-if="loading" class="muted">로딩…</div>
          <div v-else-if="error" class="err">{{ error }}</div>
          <div v-else>
            <div v-if="meta" class="meta">
              <div><strong>녹화일</strong> {{ meta.recorded_at || '—' }}</div>
              <div><strong>길이</strong> {{ meta.duration_s?.toFixed(2) ?? '—' }} s</div>
              <div><strong>키프레임</strong> {{ meta.keyframe_count ?? '—' }}</div>
              <div><strong>샘플레이트</strong> {{ meta.sample_hz ?? '—' }} Hz</div>
            </div>
            <div v-else class="muted">
              아직 녹화 안 됨 — 아래 [녹화 시작] 으로 첫 녹화를 시작하세요.
            </div>
          </div>

          <RecorderControls
            kind="mugunghwa"
            :name="MOTION_NAME"
            @recorded="refresh"
            @played="onPlayed"
            @song-play="startReferenceTts"
            @song-stop="stopReferenceTts"
          />
        </section>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.mugung-mgr {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  background: rgba(253, 242, 248, 0.96);
  z-index: 50;
}
.bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 24px;
  background: rgba(236, 72, 153, 0.10);
}
.bar h2 { margin: 0; font-size: 22px; color: #be185d; }
.btn-close {
  padding: 6px 14px;
  background: white;
  border: 1px solid #f0d0e0;
  border-radius: 8px;
  cursor: pointer;
  font-weight: 600;
  color: #6b4258;
}

.leader-warning {
  margin: 12px 24px 0;
  padding: 10px 14px;
  background: #fef3c7;
  color: #78350f;
  border: 1px solid #f59e0b;
  border-radius: 8px;
  font-size: 14px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.leader-warning code {
  background: rgba(0, 0, 0, 0.06);
  padding: 1px 6px;
  border-radius: 4px;
  font-family: 'SF Mono', Menlo, monospace;
  font-size: 13px;
}

.grid {
  flex: 1;
  display: grid;
  grid-template-columns: 1fr 380px;
  gap: 14px;
  padding: 14px 24px 24px;
  min-height: 0;
}
.viewer { min-height: 0; }
.side { display: flex; flex-direction: column; gap: 12px; overflow-y: auto; }

.slot-card {
  background: rgba(255,255,255,0.9);
  padding: 16px;
  border-radius: 12px;
}
.slot-card h3 {
  margin: 0 0 8px 0;
  font-size: 18px;
  color: #334155;
  display: flex;
  align-items: center;
  gap: 8px;
}
.hint {
  margin: 0 0 14px;
  font-size: 13px;
  color: #6b4258;
  line-height: 1.6;
}
.hint strong { color: #be185d; font-weight: 700; }
.tts-hint {
  margin: 0 0 14px;
  padding: 10px 12px;
  background: rgba(236, 72, 153, 0.08);
  border: 1px solid rgba(236, 72, 153, 0.2);
  border-radius: 10px;
  font-size: 12px;
  color: #6b4258;
  line-height: 1.6;
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
.tts-hint :deep(.icon) {
  color: #be185d;
  margin-top: 2px;
  flex-shrink: 0;
}
.tts-hint-text {
  flex: 1;
  min-width: 0;       /* flex item 이 텍스트 줄바꿈 허용하도록 */
  word-break: keep-all; /* 한글 단어 단위 줄바꿈 — 음절 단위 자르기 방지 */
  overflow-wrap: anywhere;
}
.tts-hint strong { color: #be185d; font-weight: 700; }
.meta {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px 16px;
  font-size: 13px;
  color: #475569;
  margin-bottom: 12px;
}
.meta strong {
  color: #be185d;
  font-weight: 700;
  margin-right: 4px;
}
.muted { color: #94a3b8; font-size: 13px; margin-bottom: 12px; }
.err {
  color: #b91c1c;
  background: #fef2f2;
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 13px;
  margin-bottom: 12px;
}
</style>
