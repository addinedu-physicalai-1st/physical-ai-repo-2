<script setup lang="ts">
/**
 * 율동 재생 팝업 — EduPing 의 '율동' 모드 진입 시 표시.
 *
 * 라이브러리 (GET /api/eduping/dance) 를 띄우고, 곡 선택 시 단일 양방향
 * WS (/api/eduping/dance/stream) 로 컨트롤 + audio/motion frame 을 주고받음 (useDanceStream).
 * 정지·자연 종료 시 같은 채널로 home ramp motion frame 이 흘러와 시각화 단절 없음.
 * 실물 팔/sim_twin JointTrajectory 발사도 백엔드가 WS 컨트롤에 묶어서 처리 — 별도 REST 콜 불필요.
 *
 * 녹화 기능은 본 팝업에 없음 — 녹화는 '율동 등록' 모드의 DanceManager 가 담당.
 */
import { computed, inject, onMounted, onUnmounted, ref, watch } from 'vue';
import { useModeStore } from '@/stores/mode';
import { useVoiceStore } from '@/stores/voice';
import { STOP_TOKENS } from '@/config/robots';
import { useModeIntents } from '@/composables/useModeIntents';
import { VOICE_CONTROLLER_KEY } from '@/composables/voiceControllerKey';
import { useEdupingStateWs } from '@/composables/useEdupingStateWs';
import Icon from '@/common/Icon.vue';
import OpenarmViewer from './OpenarmViewer.vue';
import IntegratedCameraPreview from '@/noriarm/IntegratedCameraPreview.vue';
import { useDanceStream } from './useDanceStream';

interface DanceItem {
  slug: string;
  display_name: string;
  duration_s?: number;
  recorded_at?: string;
  has_song?: boolean;
  has_motion?: boolean;
}

const mode = useModeStore();
const voice = useVoiceStore();
const voiceController = inject(VOICE_CONTROLLER_KEY);
const stream = useDanceStream();
const stateWs = useEdupingStateWs();
stateWs.start();

// 패널 최소화 상태 — 헤더만 남기고 본문 접음.
const cameraMinimized = ref(false);
const musicMinimized = ref(false);
// 시뮬 panel 은 기본 최소화 — URDF 로드가 무거워 율동 진입 직후엔 카메라/음악
// panel 만 펼쳐두고, 시뮬이 필요한 교사가 헤더 클릭해서 열도록.
const simMinimized = ref(true);
// 시뮬 패널이 한 번이라도 열리기 전엔 URDF 로드 자체를 하지 않음.
// realActive=true 면 패널이 unmount 되므로 어차피 로드 없음.
const simEverOpened = ref(false);
watch(simMinimized, (m) => { if (!m) simEverOpened.value = true; });

const items = ref<DanceItem[]>([]);
const loading = ref(false);
const error = ref('');

const playingSlug = ref<string>('');
const playingItem = computed(() => items.value.find((i) => i.slug === playingSlug.value) ?? null);

// 자연 촬영 — 율동 재생 중에만 캡처. 곡 시작마다 resetKey 증가시켜 직전 세션 락 해제.
// OXQuiz 와 동일한 패턴: /api/photos/natural 로 happy/sad 프레임 업로드 → 같은 child_id+date
// 의 photo_events 가 보고서 합성에 자동 포함.
const captureArmed = computed(() => playingSlug.value !== '');
const captureResetKey = ref(0);

const playDurationS = computed(() => stream.durationMs.value / 1000);
const playElapsedS = computed(() => stream.elapsedMs.value / 1000);
const progressPct = computed(() => {
  if (playDurationS.value <= 0) return 0;
  return Math.min(100, (playElapsedS.value / playDurationS.value) * 100);
});

stream.onEnd(() => {
  playingSlug.value = '';
});

watch(stream.error, (e) => {
  if (e) error.value = e;
});

async function refresh(): Promise<void> {
  loading.value = true;
  error.value = '';
  try {
    const res = await fetch('/api/eduping/dance');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    items.value = (json.items ?? []).filter((i: DanceItem) => i.has_motion !== false);
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}

function requestPlay(item: DanceItem): void {
  // 이미 재생 중인 곡 카드 클릭 = 즉시 정지 (item-icon 이 이미 stop 으로 바뀌어 있는 상태).
  if (item.slug === playingSlug.value) {
    stop();
    return;
  }
  // 다른 곡 — 클릭 즉시 재생 X. 안전을 위해 confirm 팝업 띄움.
  voiceController?.startConfirm({
    context: 'rhythm_play',
    prompt: `${item.display_name} 재생할게요. 로봇 팔이 움직일 수 있으니 가까이 가지 마세요. 재생할까요?`,
    onConfirm: () => {
      playingSlug.value = item.slug;
      captureResetKey.value += 1;
      error.value = '';
      stream.play(item.slug);
    },
    onCancel: () => {
      voiceController?.speak('알겠어요. 다른 곡을 말해주세요.');
    },
  });
}

function onConfirmClick(): void {
  const c = voice.confirm;
  voice.clearConfirm();
  if (c) void c.onConfirm();
}

function onCancelClick(): void {
  const c = voice.confirm;
  voice.clearConfirm();
  if (c) void c.onCancel();
}

function stop(): void {
  stream.stop();
  playingSlug.value = '';
}

function close(): void {
  stream.stop();  // home ramp 시작
  mode.setMode('대기');  // 팝업 unmount → onUnmounted 가 stream.close()
}

onMounted(() => {
  void refresh();
  stream.connect();
});
onUnmounted(() => {
  stream.close();
  stateWs.stop();
  voice.setSttHints([]);  // 다른 mode 진입 시 영향 안 주게 hint 비움.
});

// STT prompt hint — 등록된 곡명 + 율동 모드 내 자주 발화하는 명령들.
watch(
  () => items.value.map((i) => i.display_name).join('|'),
  () => {
    const songs = items.value.map((i) => i.display_name);
    voice.setSttHints([
      ...songs,
      '정지', '멈춰', '그만', '노래 멈춰', '음악 정지',
      '대기', '쉬자',
    ]);
  },
  { immediate: true },
);

// 음성 명령으로 들어온 곡 재생/정지. 라이브러리 (items) 에서 displayName 의 정규화
// substring 매치 — '아기상어' 발화로 '아기상어 율동' 같은 등록명도 잡히게.
// STT 가 문장 끝에 '.' 등 punctuation 을 종종 붙이므로 같이 제거.
function _normalize(s: string): string {
  return s.replace(/[\s.,!?。｡]/g, '').toLowerCase();
}

function _bigrams(s: string): Set<string> {
  const out = new Set<string>();
  for (let i = 0; i < s.length - 1; i++) out.add(s.slice(i, i + 2));
  return out;
}

function _jaccard(a: Set<string>, b: Set<string>): number {
  if (a.size === 0 || b.size === 0) return 0;
  let inter = 0;
  for (const x of a) if (b.has(x)) inter += 1;
  return inter / (a.size + b.size - inter);
}

const _BIGRAM_SIM_THRESHOLD = 0.4;

/** STT 가 "정지" 를 "장기/공지/방지" 등으로 떨군 경우를 mode-aware 로 잡기.
 *  발화 정규화 결과가 stopTokens 중 어느 하나와 글자 단위 거리 (1 이하) 또는
 *  bigram 유사도 임계 이상이면 stop 의 변형으로 본다. 짧은 한글 stop 토큰
 *  ('정지' 2글자) 의 1글자 차이는 음운 변형일 확률이 높음.
 *
 *  단순 char-level Levenshtein 의 짧은-string 변형: 두 문자열 길이가 같고 다른
 *  글자 수가 1 이하면 distance ≤ 1.
 */
function _isStopVariant(displayName: string): boolean {
  const q = _normalize(displayName);
  if (!q) return false;
  for (const token of STOP_TOKENS) {
    const t = _normalize(token);
    if (!t) continue;
    if (q === t) return true;
    // 같은 길이 + 1글자 차이 → 정지 ↔ 장기/공지/방지/잡지/정시 같은 패턴.
    if (q.length === t.length && q.length >= 2) {
      let diff = 0;
      for (let i = 0; i < q.length; i++) {
        if (q[i] !== t[i]) diff += 1;
        if (diff > 1) break;
      }
      if (diff <= 1) return true;
    }
  }
  return false;
}

function _findByDisplayName(displayName: string): DanceItem | null {
  const q = _normalize(displayName);
  if (!q) return null;
  // 1) 전체 substring (정확 match) — 가장 강한 확신.
  for (const item of items.value) {
    if (_normalize(item.display_name).includes(q)) return item;
  }
  // 2) 단어 단위 partial — STT 가 첫 음절 누락해도 다른 토큰이 등록명에 들어 있으면.
  const tokens = displayName
    .split(/\s+/)
    .map(_normalize)
    .filter((t) => t.length >= 2);
  for (const item of items.value) {
    const name = _normalize(item.display_name);
    if (tokens.some((t) => name.includes(t))) return item;
  }
  // 3) char-bigram Jaccard 유사도 — '쨍이 토마토' vs '멋쟁이 토마토' 처럼 일부
  //    음절만 다른 STT 오인식까지 흡수. threshold 0.4 = 약 절반 이상 음절쌍 공유.
  const qBigrams = _bigrams(q);
  let best: { item: DanceItem; score: number } | null = null;
  for (const item of items.value) {
    const score = _jaccard(qBigrams, _bigrams(_normalize(item.display_name)));
    if (score > (best?.score ?? 0)) best = { item, score };
  }
  if (best && best.score >= _BIGRAM_SIM_THRESHOLD) return best.item;
  return null;
}

// 음성 명령으로 들어온 곡 재생/정지/모드 종료 — useModeIntents 로 등록.
// confirm 사이클은 voiceController.startConfirm 으로 일임 (TTS prompt + wake gate
// + 서버 awaiting_confirm sync 일괄).
useModeIntents('율동', {
  onRhythmPlay: ({ displayName }) => {
    const playing = playingSlug.value !== '';
    const stopLike = _isStopVariant(displayName);

    // 1) 재생 중 + stop 변형 — STT 가 '정지' 를 '장기/공지/방지' 등으로
    //    떨군 경우. 재생 중인 상태에선 stop 의도일 확률이 압도적이라 즉시
    //    음악 정지 + 대기 복귀.
    if (playing && stopLike) {
      stop();
      mode.setMode('대기');
      return;
    }

    // 2) 재생 중 + 그 외 — 마이크가 곡 가사를 STT 로 잡아 들어오는 false
    //    rhythm_play 가 흔함. 무시.
    if (playing) return;

    // 3) 재생 안 중 — 사용자가 곡 선택/재생 의도일 확률이 압도적. 라이브러리
    //    fuzzy match 우선. stop 변형이라도 곡 찾기를 먼저 시도.
    if (items.value.length === 0) {
      voiceController?.speak('아직 등록된 율동이 없어요. 율동 등록 모드에서 먼저 곡을 추가해 주세요.');
      return;
    }
    const match = _findByDisplayName(displayName);
    if (match) {
      voiceController?.startConfirm({
        context: 'rhythm_play',
        prompt: `${match.display_name} 재생할게요. 로봇 팔이 움직일 수 있으니 가까이 가지 마세요. 재생할까요?`,
        onConfirm: () => {
          playingSlug.value = match.slug;
          captureResetKey.value += 1;
          error.value = '';
          stream.play(match.slug);
        },
        onCancel: () => {
          voiceController?.speak('알겠어요. 다른 곡을 말해주세요.');
        },
      });
      return;
    }

    // 4) 매치 실패 — 못 찾았다 안내. 사용자가 정말 빠져나가려면 정식 '정지'/'대기'
    //    발화로 다시 시도 (server StopHandler / ModeChangeHandler 가 분류).
    voiceController?.speak(
      `${displayName} 비슷한 곡을 찾지 못했어요. 등록된 곡 이름으로 다시 말해줄래요?`,
    );
  },
  onRhythmStop: () => {
    stop();
  },
  onModeExit: () => {
    mode.setMode('대기');
  },
});
</script>

<template>
  <Transition name="fade">
    <div class="popup-overlay" @click.self="close">
      <button type="button" class="close-fab" aria-label="닫기" @click="close">×</button>

      <!-- 카메라: 좌상단 -->
      <section
        class="panel panel-top-left"
        :class="{ minimized: cameraMinimized }"
        role="dialog"
        aria-label="카메라"
      >
        <header class="panel-head" @click="cameraMinimized = !cameraMinimized">
          <Icon name="camera" :size="16" />
          <span class="panel-title">카메라</span>
          <button
            type="button"
            class="btn-min"
            :aria-label="cameraMinimized ? '펼치기' : '최소화'"
            @click.stop="cameraMinimized = !cameraMinimized"
          >{{ cameraMinimized ? '+' : '–' }}</button>
        </header>
        <div v-show="!cameraMinimized" class="panel-body panel-body-camera">
          <IntegratedCameraPreview
            :armed="captureArmed"
            :reset-key="captureResetKey"
            robot="eduping"
            mode="dance"
            :infer-interval-ms="600"
          />
        </div>
      </section>

      <!-- 음악 플레이어: 우상단 -->
      <section
        class="panel panel-top-right panel-music"
        :class="{ minimized: musicMinimized }"
        role="dialog"
        aria-label="음악"
      >
        <header class="panel-head" @click="musicMinimized = !musicMinimized">
          <Icon name="music" :size="16" />
          <span class="panel-title">음악</span>
          <button
            type="button"
            class="btn-min"
            :aria-label="musicMinimized ? '펼치기' : '최소화'"
            @click.stop="musicMinimized = !musicMinimized"
          >{{ musicMinimized ? '+' : '–' }}</button>
        </header>
        <div v-show="!musicMinimized" class="panel-body">
          <!-- Now playing card (앨범 아트 느낌) -->
          <div class="np-card" :class="{ idle: !playingItem }">
            <div class="np-art">
              <Icon name="music" :size="playingItem ? 42 : 36" />
            </div>
            <div class="np-meta">
              <div class="np-title">
                {{ playingItem?.display_name ?? '재생 중인 곡 없음' }}
              </div>
              <div v-if="playingItem" class="np-bar">
                <div class="np-fill" :style="{ width: `${progressPct}%` }" />
              </div>
              <div v-if="playingItem" class="np-time">
                {{ playElapsedS.toFixed(1) }} / {{ playDurationS.toFixed(1) }}s
              </div>
              <div v-else class="np-hint">아래 목록에서 한 곡을 골라주세요.</div>
            </div>
            <button
              v-if="playingItem"
              type="button"
              class="np-ctrl"
              aria-label="정지"
              @click="stop"
            >
              <Icon name="stop" :size="22" />
            </button>
          </div>

          <!-- Track list -->
          <div class="track-list-wrap">
            <div v-if="loading" class="hint">불러오는 중…</div>
            <div v-else-if="error" class="err">{{ error }}</div>
            <ul v-else-if="items.length > 0" class="track-list">
              <li
                v-for="(item, idx) in items"
                :key="item.slug"
                class="track"
                :class="{ playing: item.slug === playingSlug }"
                @click="requestPlay(item)"
              >
                <div class="track-num">
                  <Icon
                    v-if="item.slug === playingSlug"
                    name="stop"
                    :size="14"
                  />
                  <span v-else>{{ String(idx + 1).padStart(2, '0') }}</span>
                </div>
                <div class="track-meta">
                  <div class="track-name">{{ item.display_name }}</div>
                  <div class="track-sub">
                    <span v-if="item.duration_s">{{ item.duration_s.toFixed(1) }}초</span>
                    <span v-if="item.has_song === false" class="warn">곡 없음</span>
                  </div>
                </div>
                <div class="track-play-icon">
                  <Icon :name="item.slug === playingSlug ? 'stop' : 'play'" :size="16" />
                </div>
              </li>
            </ul>
            <div v-else class="hint">
              저장된 율동이 없어요.<br />
              <small>'율동 등록' 모드에서 새 곡을 추가하세요.</small>
            </div>
          </div>
        </div>
      </section>

      <!-- 시뮬레이션: 좌하단. 실물 팔로워 연결 시 숨김. -->
      <section
        v-if="!stateWs.realActive.value"
        class="panel panel-bottom-left"
        :class="{ minimized: simMinimized }"
        role="dialog"
        aria-label="시뮬레이션"
      >
        <header class="panel-head" @click="simMinimized = !simMinimized">
          <Icon name="robot" :size="16" />
          <span class="panel-title">시뮬레이션</span>
          <button
            type="button"
            class="btn-min"
            :aria-label="simMinimized ? '펼치기' : '최소화'"
            @click.stop="simMinimized = !simMinimized"
          >{{ simMinimized ? '+' : '–' }}</button>
        </header>
        <div v-show="!simMinimized" class="panel-body panel-body-sim">
          <OpenarmViewer v-if="simEverOpened" source="follower" :external-snapshot="stream.currentSnapshot.value" />
        </div>
      </section>

      <Transition name="fade">
        <div v-if="voice.confirm" class="confirm-overlay" @click.self="onCancelClick">
          <div class="confirm-card" role="alertdialog" aria-modal="true">
            <div class="confirm-icon">
              <Icon name="alert" :size="32" />
            </div>
            <h3>{{ voice.confirm.prompt }}</h3>
            <div class="confirm-actions">
              <button type="button" class="btn-cancel" @click="onCancelClick">아니오</button>
              <button type="button" class="btn-confirm" @click="onConfirmClick">
                <Icon name="play" :size="14" /> 예
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </div>
  </Transition>
</template>

<style scoped>
.popup-overlay {
  position: fixed;
  inset: 0;
  /* 로봇 얼굴이 또렷이 보이도록 dim/blur 제거. 클릭은 여전히 차단 (투명 + auto). */
  background: transparent;
  z-index: 60;
}

.close-fab {
  position: absolute;
  top: 18px;
  left: 50%;
  transform: translateX(-50%);
  width: 44px;
  height: 44px;
  border-radius: 50%;
  border: none;
  background: rgba(255, 255, 255, 0.9);
  color: #475569;
  font-size: 28px;
  line-height: 1;
  cursor: pointer;
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.18);
}
.close-fab:hover { background: white; color: #1e293b; }

/* --- 플로팅 패널 공통 --- */
.panel {
  position: absolute;
  background: rgba(255, 255, 255, 0.97);
  border-radius: 16px;
  box-shadow: 0 20px 50px -12px rgba(15, 23, 42, 0.45);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  backdrop-filter: blur(6px);
}
.panel-top-left    { top: 18px;  left: 18px;  width: 360px; }
.panel-top-right   { top: 18px;  right: 18px; width: 380px; max-height: calc(100dvh - 36px); }
.panel-bottom-left { bottom: 18px; left: 18px; width: 360px; }

.panel-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  background: linear-gradient(135deg, #fce7f3, #fbcfe8);
  color: #9d174d;
  cursor: pointer;
  user-select: none;
}
.panel-title {
  font-weight: 700;
  font-size: 14px;
  flex: 1;
}
.btn-min {
  border: none;
  background: rgba(255, 255, 255, 0.6);
  color: #9d174d;
  width: 24px;
  height: 24px;
  border-radius: 6px;
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}
.btn-min:hover { background: white; }
.panel.minimized .panel-body { display: none; }

.panel-body {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.panel-body-camera { padding: 0; }
.panel-body-camera :deep(.cam-panel) {
  width: 100%;
  border-radius: 0;
}
.panel-body-camera :deep(.cam-panel video) {
  height: 220px;
}
.panel-body-sim { height: 280px; }
.panel-body-sim :deep(.openarm-viewer-wrap) { border-radius: 0; }

/* --- 음악 플레이어 --- */
.panel-music .panel-body { padding: 14px 14px 10px; gap: 12px; }

.np-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  border-radius: 14px;
  background: linear-gradient(135deg, #ec4899 0%, #f59e0b 100%);
  color: white;
  box-shadow: 0 12px 24px -10px rgba(236, 72, 153, 0.45);
}
.np-card.idle {
  background: linear-gradient(135deg, #f1f5f9 0%, #e2e8f0 100%);
  color: #64748b;
  box-shadow: none;
}
.np-art {
  width: 64px;
  height: 64px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.25);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.np-card.idle .np-art { background: rgba(100, 116, 139, 0.1); }

.np-meta { flex: 1; min-width: 0; }
.np-title {
  font-weight: 800;
  font-size: 15px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 6px;
}
.np-bar {
  height: 5px;
  background: rgba(255, 255, 255, 0.3);
  border-radius: 999px;
  overflow: hidden;
}
.np-fill {
  height: 100%;
  background: white;
  border-radius: 999px;
  transition: width 0.1s linear;
}
.np-time {
  font-size: 11px;
  opacity: 0.9;
  margin-top: 4px;
  font-variant-numeric: tabular-nums;
}
.np-hint { font-size: 12px; opacity: 0.8; }
.np-ctrl {
  flex-shrink: 0;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  border: none;
  background: rgba(255, 255, 255, 0.2);
  color: white;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.12s, transform 0.08s;
}
.np-ctrl:hover { background: rgba(255, 255, 255, 0.35); }
.np-ctrl:active { transform: scale(0.95); }

.track-list-wrap {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  max-height: 48vh;
}
.track-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
}
.track {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 8px;
  border-radius: 10px;
  cursor: pointer;
  transition: background 0.1s;
}
.track:hover { background: #fdf2f8; }
.track.playing { background: #fce7f3; }
.track-num {
  width: 26px;
  text-align: center;
  font-size: 13px;
  color: #94a3b8;
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}
.track.playing .track-num { color: #ec4899; }
.track-meta { flex: 1; min-width: 0; }
.track-name {
  font-weight: 600;
  font-size: 14px;
  color: #1e293b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.track.playing .track-name { color: #be185d; }
.track-sub {
  margin-top: 2px;
  font-size: 11px;
  color: #94a3b8;
  display: flex;
  gap: 6px;
}
.track-sub .warn { color: #b45309; }
.track-play-icon {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: rgba(236, 72, 153, 0.08);
  color: #be185d;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  opacity: 0;
  transition: opacity 0.1s;
}
.track:hover .track-play-icon,
.track.playing .track-play-icon { opacity: 1; }
.track.playing .track-play-icon { background: #ec4899; color: white; }

.hint {
  text-align: center;
  color: #94a3b8;
  font-size: 13px;
  padding: 24px 12px;
  line-height: 1.6;
}
.hint small { color: #cbd5e1; font-size: 11px; }
.err {
  color: #b91c1c;
  background: #fef2f2;
  padding: 10px 12px;
  border-radius: 10px;
  font-size: 13px;
}

/* --- 태블릿: 패널 플로팅 유지하되 크기 축소 --- */
@media (min-width: 801px) and (max-width: 1280px) {
  .panel-top-left  { width: 210px; }
  .panel-top-right { width: 220px; }
  .panel-body-camera :deep(.cam-panel video) { height: 120px; }
  .np-art { width: 44px; height: 44px; }
  .np-title { font-size: 12px; }
  .np-hint { font-size: 11px; }
  .track-name { font-size: 12px; }
  .track-sub { font-size: 10px; }
  .panel-title { font-size: 12px; }
  .track-list-wrap { max-height: 40vh; }
}

/* --- 좁은 화면: 패널을 위/중/아래로 쌓고 폭 조정 --- */
@media (max-width: 800px), (pointer: coarse) {
  .panel-top-left,
  .panel-top-right,
  .panel-bottom-left {
    position: static;
    width: calc(100vw - 24px);
    margin: 0 auto;
  }
  .popup-overlay {
    padding: 60px 12px 12px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    overflow-y: auto;
  }
  .panel-body-camera { height: 220px; }
  .panel-body-sim { height: 240px; }
  .track-list-wrap { max-height: 36vh; }
}

.fade-enter-active, .fade-leave-active { transition: opacity 0.18s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

.confirm-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.55);
  z-index: 70;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}
.confirm-card {
  background: white;
  border-radius: 18px;
  padding: 28px 32px 24px;
  max-width: 420px;
  width: 100%;
  box-shadow: 0 20px 60px rgba(15, 23, 42, 0.3);
  text-align: center;
}
.confirm-icon {
  width: 56px;
  height: 56px;
  margin: 0 auto 14px;
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #fef3c7;
  color: #d97706;
}
.confirm-card h3 {
  margin: 0 0 10px;
  font-size: 18px;
  color: #1e293b;
  letter-spacing: -0.01em;
}
.confirm-body {
  margin: 0 0 22px;
  font-size: 14px;
  color: #64748b;
  line-height: 1.5;
}
.confirm-actions {
  display: flex;
  gap: 10px;
  justify-content: center;
}
.btn-cancel, .btn-confirm {
  border: none;
  border-radius: 12px;
  padding: 10px 22px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.btn-cancel {
  background: #f1f5f9;
  color: #475569;
}
.btn-cancel:hover { background: #e2e8f0; }
.btn-confirm {
  background: #ec4899;
  color: white;
}
.btn-confirm:hover { background: #db2777; }
</style>
