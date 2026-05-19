<script setup lang="ts">
import { computed, inject, onUnmounted, ref, watch } from 'vue';
import { storeToRefs } from 'pinia';
import { useModeStore } from '@/stores/mode';
import oxQuizData from '../../../../../shared/ox_quiz.json';
import UrdfViewer from '@/noriarm/UrdfViewer.vue';
import OXVisionPreview from '@/noriarm/OXVisionPreview.vue';
import IntegratedCameraPreview from '@/noriarm/IntegratedCameraPreview.vue';
import { VOICE_CONTROLLER_KEY } from '@/composables/voiceControllerKey';

const voiceController = inject(VOICE_CONTROLLER_KEY);
const tts = {
  speak: (text: string) => { voiceController?.speak(text); return Promise.resolve(); },
  cancel: () => { voiceController?.cancelSpeak(); },
};

interface OXQuestion {
  id: string;
  question: string;
  answer: 'O' | 'X';
  explanation: string;
}

const QUESTIONS_PER_ROUND = 3;
// trajectory duration 응답이 누락된 비정상 케이스의 fallback. 정상 흐름에서는 서버가 돌려준 duration_s 사용.
const FALLBACK_TRAJECTORY_MS = 18000;
// 정답 공개 후 다음 문제 전 잠깐 머무는 시간 — 사용자가 답·해설 읽도록.
const REVEAL_VIEW_MS = 3500;

type Phase = 'intro' | 'question' | 'thinking' | 'reveal' | 'done';

const mode = useModeStore();
const { currentMode } = storeToRefs(mode);
const isActive = computed(() => currentMode.value === 'OX 퀴즈');

function exitToIdle(): void {
  mode.setMode('대기');
}

const phase = ref<Phase>('intro');
const questions = ref<OXQuestion[]>([]);
const currentIndex = ref(0);

// 점수 / 직전 클릭 — reveal 단계에서 정/오답 표시 + done 화면 결과 요약.
const score = ref(0);
const userClicked = ref<'O' | 'X' | null>(null);

// 실물 노리암 연결 여부 (Control Server `/api/noriarm/health` 결과).
//   true  — 실물 연결, URDF 시뮬 뷰어 숨기고 실물 배지만 표시
//   false — 실물 미연결, URDF 뷰어로 시뮬레이션 시각화
//   null  — 아직 확인 전 (보수적으로 시뮬 표시)
const realArmPresent = ref<boolean | null>(null);
const showSimViewer = computed(() => realArmPresent.value !== true);

// 외장 카메라(보드·YOLO) 감지 — OXVisionPreview emit. 없으면 보드 패널 숨김.
//   null  — 감지 전
//   true  — 외장 후보 있음 → 좌하단 패널
//   false — 없음
const usbCameraAvailable = ref<boolean | null>(null);

// 내장 카메라 감지 (자연 촬영용, 우상단). USB 보드 카메라와 동시에 있어도 마운트되어 probe.
const integratedCameraAvailable = ref<boolean | null>(null);
// 자연 촬영 — 세션 동안 표정이 잡힐 때마다 쿨다운 후 추가 저장. done 화면에서 장 수 집계.
const naturalShotCount = ref(0);
// IntegratedCameraPreview 에 넘기는 resetKey — startQuiz 마다 +1 해서 락 해제 trigger.
const captureResetKey = ref(0);
// 자연 촬영 활성 phase — 게임 진행 중 (intro/done 제외).
const captureArmed = computed(
  () => phase.value === 'question' || phase.value === 'thinking' || phase.value === 'reveal',
);

/** 내장 카메라 probe 가 끝나고 없을 때만(false) OX 패널 안에서 표정 PIP·두 번째 스트림 사용.
 * null(probe 전) 이면 끄기 — 내장이 있으면 곧 우상단으로 가므로 노트북 화면이 USB 위에 겹치는 것 방지. */
const oxPanelEmotionEnabled = computed(() => integratedCameraAvailable.value === false);

function handleNaturalShot(): void {
  naturalShotCount.value += 1;
}

// reveal/playback 단계 동안 중복 클릭 방지.
const submitting = ref(false);

// 3개 패널 각각 독립 토글 — 사용자가 필요한 것만 켤 수 있도록 (햄버거 일괄 토글 X).
// 기본은 전부 숨김. 각 코너에 작은 pill 버튼이 항상 떠 있고, 클릭하면 그 자리에서
// 패널이 펼쳐진다. localStorage 로 세션 간 사용자 선호도 유지.
function makeToggle(key: string) {
  const r = ref(typeof window !== 'undefined' && window.localStorage.getItem(key) === '1');
  return {
    ref: r,
    toggle: () => {
      r.value = !r.value;
      if (typeof window !== 'undefined') {
        window.localStorage.setItem(key, r.value ? '1' : '0');
      }
    },
  };
}
const faceCam = makeToggle('oxquiz.panel.face');
const boardCam = makeToggle('oxquiz.panel.board');
const simView = makeToggle('oxquiz.panel.sim');

const isCorrect = computed(
  () => userClicked.value !== null && currentQuestion.value?.answer === userClicked.value,
);

let phaseTimer: number | null = null;

// 두구두구 효과음 — thinking phase ("노리암이 답을 가리키고 있어요…") 시작 시 재생.
// 모듈 로드 시점에 Audio 생성 + preload='auto' 로 mp3 를 미리 받아둠 — 클릭 직후
// 첫 재생에서 fetch latency 가 안 끼게.
const revealSfx = new Audio('/sounds/dugudugu.mp3');
revealSfx.preload = 'auto';
function playRevealSfx(): void {
  try {
    revealSfx.currentTime = 0;
    void revealSfx.play().catch(() => {
      /* 자동재생 정책 차단 등 — 조용히 무시 */
    });
  } catch {
    /* Audio 재생 실패 무시 */
  }
}
function stopRevealSfx(): void {
  revealSfx.pause();
  revealSfx.currentTime = 0;
}

function clearTimers(): void {
  if (phaseTimer != null) {
    window.clearTimeout(phaseTimer);
    phaseTimer = null;
  }
}

function shuffle<T>(arr: T[]): T[] {
  const out = arr.slice();
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

function pickQuestions(): OXQuestion[] {
  const pool = oxQuizData.questions as OXQuestion[];
  return shuffle(pool).slice(0, QUESTIONS_PER_ROUND);
}

async function checkRealArmHealth(): Promise<void> {
  try {
    const r = await fetch('/api/noriarm/health');
    if (!r.ok) {
      realArmPresent.value = null;
      return;
    }
    const data = (await r.json()) as { real_arm_present?: boolean };
    realArmPresent.value = Boolean(data.real_arm_present);
  } catch (err) {
    console.warn('[OXQuiz] /api/noriarm/health 호출 실패 — sim 으로 가정', err);
    realArmPresent.value = null;
  }
}

interface AnswerResponse {
  ok?: boolean;
  action?: string;
  duration_s?: number;
}

async function dispatchTrajectory(answer: 'O' | 'X'): Promise<AnswerResponse | null> {
  // Control Server 가 노리암 정책을 호출해 trajectory 재생을 background 로 시작.
  // 서버는 trajectory 길이 (duration_s) 를 응답에 포함 — UI 가 그 시간 후 다음 문제로.
  // joint state 들은 별도로 UrdfViewer 가 SSE 로 받아 three.js 에 반영.
  try {
    const r = await fetch('/api/noriarm/games/ox-quiz/answer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answer }),
    });
    if (!r.ok) return null;
    return (await r.json()) as AnswerResponse;
  } catch (err) {
    console.warn('[OXQuiz] answer dispatch failed', err);
    return null;
  }
}

function startQuiz(): void {
  clearTimers();
  questions.value = pickQuestions();
  currentIndex.value = 0;
  score.value = 0;
  userClicked.value = null;
  // 새 세션 — 직전 캡처 락 해제 + 카운트 리셋.
  naturalShotCount.value = 0;
  captureResetKey.value += 1;
  startQuestion();
}

function startQuestion(): void {
  clearTimers();
  submitting.value = false;
  userClicked.value = null;
  phase.value = 'question';
  // 문제 본문 TTS — 진입 직후 발화. 사용자가 답을 누르면 selectAnswer 에서 cancel.
  const q = questions.value[currentIndex.value];
  if (q) void tts.speak(q.question);
}

async function selectAnswer(clicked: 'O' | 'X'): Promise<void> {
  // 흐름: thinking (로봇 동작) → reveal (정·오답 + 정답 공개) → 다음.
  if (phase.value !== 'question' || submitting.value) return;
  const q = questions.value[currentIndex.value];
  if (!q) return;
  submitting.value = true;
  userClicked.value = clicked;
  if (clicked === q.answer) {
    score.value += 1;
  }
  // 답 선택했으니 문제 낭독 중이면 끊는다.
  tts.cancel();

  phase.value = 'thinking';
  // 두구두구 — 사용자가 O/X 선택한 즉시 재생. 로봇이 답을 가리키는 동안 긴장감 유지.
  playRevealSfx();
  const result = await dispatchTrajectory(q.answer);
  // 로봇이 답을 가리킨 후 원위치로 돌아오는 마지막 ~5 초 동안에는 이미 답이 정해진 상태이므로
  // trajectory 종료 5 초 전에 reveal 로 전환한다 — 발표가 늦다는 체감 제거.
  const totalMs = result?.duration_s ? result.duration_s * 1000 : FALLBACK_TRAJECTORY_MS;
  const waitMs = Math.max(500, totalMs - 5000);

  // trajectory 가 끝난 뒤에야 정답 공개.
  phaseTimer = window.setTimeout(() => {
    phase.value = 'reveal';
    // 정답 카드를 잠깐 보여준 뒤 다음 문제로.
    phaseTimer = window.setTimeout(() => {
      phaseTimer = null;
      if (currentIndex.value + 1 < questions.value.length) {
        currentIndex.value += 1;
        startQuestion();
      } else {
        phase.value = 'done';
      }
    }, REVEAL_VIEW_MS);
  }, waitMs);
}

function reset(): void {
  clearTimers();
  stopRevealSfx();
  tts.cancel();
  submitting.value = false;
  phase.value = 'intro';
  currentIndex.value = 0;
  questions.value = [];
  score.value = 0;
  userClicked.value = null;
  naturalShotCount.value = 0;
  captureResetKey.value += 1;
  integratedCameraAvailable.value = null;
}

watch(isActive, (active, prev) => {
  if (!active && prev) reset();
  if (active && !prev) {
    phase.value = 'intro';
    integratedCameraAvailable.value = null;
    void checkRealArmHealth();
  }
});

onUnmounted(clearTimers);

const currentQuestion = computed<OXQuestion | null>(
  () => questions.value[currentIndex.value] ?? null
);
const progressLabel = computed(
  () => `${currentIndex.value + 1} / ${questions.value.length}`
);
</script>

<template>
  <Teleport to="body">
    <Transition name="ox-fade">
      <div v-if="isActive" class="ox-overlay" :data-phase="phase">
        <!-- intro -->
        <div v-if="phase === 'intro'" class="card intro">
          <h1>OX 퀴즈</h1>
          <p class="subtitle">3문제를 낼게요. O 또는 X 위에 손을 올려놓으세요!</p>
          <button class="primary" @click="startQuiz">시작하기</button>
        </div>

        <!-- question -->
        <div v-else-if="phase === 'question' && currentQuestion" class="card question">
          <div class="progress">{{ progressLabel }}</div>
          <h2 class="q-text">{{ currentQuestion.question }}</h2>
          <div class="markers">
            <button class="marker o clickable" type="button" @click="selectAnswer('O')">O</button>
            <button class="marker x clickable" type="button" @click="selectAnswer('X')">X</button>
          </div>
          <p class="hint">정답을 클릭해 주세요</p>
        </div>

        <!-- thinking — 로봇 동작 중. 정답은 아직 비공개. -->
        <div v-else-if="phase === 'thinking' && currentQuestion" class="card thinking">
          <div class="progress">{{ progressLabel }}</div>
          <h2 class="q-text small">{{ currentQuestion.question }}</h2>
          <div class="thinking-icon">🤔</div>
          <p class="status pulse">노리암이 답을 가리키고 있어요…</p>
          <p class="hint">로봇 팔이 멈출 때까지 기다려 주세요</p>
        </div>

        <!-- reveal — 로봇 동작 끝났을 때만. 정·오답 배지 + 정답 + 해설 공개. -->
        <div v-else-if="phase === 'reveal' && currentQuestion" class="card reveal">
          <div class="progress">{{ progressLabel }}</div>
          <div class="result-badge" :class="isCorrect ? 'is-correct' : 'is-wrong'">
            {{ isCorrect ? '정답!' : '오답!' }}
          </div>
          <h2 class="q-text small">{{ currentQuestion.question }}</h2>
          <div class="answer-box" :class="currentQuestion.answer === 'O' ? 'is-o' : 'is-x'">
            <span class="big-answer">{{ currentQuestion.answer }}</span>
          </div>
          <p class="explanation">{{ currentQuestion.explanation }}</p>
          <p class="running-score">점수 {{ score }} / {{ questions.length }}</p>
        </div>

        <!-- done -->
        <div v-else-if="phase === 'done'" class="card done">
          <h1>퀴즈 끝!</h1>
          <div class="final-score">
            <span class="score-num">{{ score }}</span>
            <span class="score-total"> / {{ questions.length }}</span>
          </div>
          <p class="subtitle">{{ score === questions.length ? '완벽해요! 🎉' : score > 0 ? '잘했어요 👏' : '다음에는 더 잘할 수 있어요!' }}</p>
          <p class="natural-shot-line">
            <template v-if="naturalShotCount > 0">
              오늘의 표정 {{ naturalShotCount }}장 찍었어요 📸
            </template>
            <template v-else>사진은 못 찍었어요</template>
          </p>
          <div class="done-actions">
            <button class="primary" @click="startQuiz">다시 하기</button>
            <button class="secondary" @click="exitToIdle">그만 하기</button>
          </div>
        </div>

        <!-- 우상단 — OX 퀴즈 모드 나가기. 항상 노출되어 done 화면이 아니어도 즉시 종료 가능. -->
        <div class="panel-zone panel-top-right">
          <button
            type="button"
            class="exit-btn"
            aria-label="OX 퀴즈 종료"
            title="OX 퀴즈 종료"
            @click="exitToIdle"
          >×</button>
        </div>

        <!-- 표정(자연 촬영) — 좌상단. pill 은 항상 노출 — 카메라 컴포넌트는 panel 이
             열린 동안에만 mount/probe 한다. 카메라가 없으면 panel 안에서 에러로 표시. -->
        <div class="panel-zone panel-top-left">
          <button
            v-if="!faceCam.ref.value"
            type="button"
            class="panel-pill"
            aria-label="표정 카메라 열기"
            @click="faceCam.toggle"
          >
            📷 <span class="pill-label">표정</span>
          </button>
          <div v-else class="panel-open">
            <button
              type="button"
              class="panel-close"
              aria-label="표정 카메라 닫기"
              @click="faceCam.toggle"
            >×</button>
            <div class="panel-box">
              <IntegratedCameraPreview
                :armed="captureArmed"
                :reset-key="captureResetKey"
                robot="noriarm"
                mode="ox-quiz"
                @integrated-available="(v: boolean) => (integratedCameraAvailable = v)"
                @captured="handleNaturalShot"
              />
              <p class="panel-caption">표정 촬영 (내장 카메라)</p>
            </div>
          </div>
        </div>

        <!-- 보드 카메라 — 좌하단. -->
        <div class="panel-zone panel-bottom-left">
          <button
            v-if="!boardCam.ref.value"
            type="button"
            class="panel-pill"
            aria-label="보드 카메라 열기"
            @click="boardCam.toggle"
          >
            🎯 <span class="pill-label">보드</span>
          </button>
          <div v-else class="panel-open">
            <button
              type="button"
              class="panel-close"
              aria-label="보드 카메라 닫기"
              @click="boardCam.toggle"
            >×</button>
            <div class="panel-box">
              <OXVisionPreview
                :armed="phase === 'question' && !submitting"
                :emotion-armed="captureArmed && oxPanelEmotionEnabled"
                :emotion-reset-key="captureResetKey"
                robot="noriarm"
                mode="ox-quiz"
                @select="(r: 'O' | 'X') => void selectAnswer(r)"
                @usb-available="(v: boolean) => (usbCameraAvailable = v)"
                @emotion-captured="handleNaturalShot"
              />
              <p class="panel-caption">
                <span class="status-dot status-vision" />
                <template v-if="integratedCameraAvailable === true">
                  보드·손 인식 (YOLO)
                </template>
                <template v-else>
                  보드 인식 · 첫 카메라는 표정 · 문제·생각·해설 단계에서만 인식
                </template>
              </p>
            </div>
          </div>
        </div>

        <!-- sim 또는 실물 배지 — 우하단. -->
        <div class="panel-zone panel-bottom-right">
          <template v-if="showSimViewer">
            <button
              v-if="!simView.ref.value"
              type="button"
              class="panel-pill"
              aria-label="시뮬레이션 열기"
              @click="simView.toggle"
            >
              🤖 <span class="pill-label">시뮬</span>
            </button>
            <div v-else class="panel-open">
              <button
                type="button"
                class="panel-close"
                aria-label="시뮬레이션 닫기"
                @click="simView.toggle"
              >×</button>
              <div class="panel-box">
                <div class="sim-canvas-wrap">
                  <UrdfViewer />
                </div>
                <p class="panel-caption">
                  <span class="status-dot status-sim" />
                  노리암 시뮬레이션
                </p>
              </div>
            </div>
          </template>
          <div v-else class="real-badge">
            <span class="status-dot status-real" />
            실물 노리암 연결됨
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.ox-overlay {
  position: fixed;
  inset: 0;
  /* ModeSelectorFab(20) 보다 아래 — 사용자가 다른 모드로 빠져나올 수 있도록. */
  z-index: 18;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, rgba(232, 245, 251, 0.92) 0%, rgba(197, 228, 243, 0.92) 100%);
  backdrop-filter: blur(6px);
  font-family: inherit;
}
.card {
  background: white;
  border-radius: 28px;
  padding: 56px 64px;
  box-shadow: 0 20px 60px rgba(40, 110, 160, 0.18);
  text-align: center;
  min-width: 480px;
  max-width: 720px;
}
/* ── 카메라·시뮬 패널 ───────────────────────────────────────────────────────
 * 3개 패널 (표정 카메라 / 보드 카메라 / sim 뷰어) 가 동일한 box 크기로 모서리에
 * 배치된다 — 좌상 (표정) / 좌하 (보드) / 우하 (sim). 우측 ModeSelectorFab 사이드바와
 * 안 겹치게 마진 확보. `:deep()` 으로 내부 컴포넌트의 자체 width/height 를 일괄 override
 * 해 세 패널이 시각적으로 동일 frame 으로 보이게 함.
 * 우상단은 닫기 (×) 버튼 자리라 비워둠. */
/* 코너 zone 컨테이너 — pill (닫힌 상태) 또는 panel-box (열린 상태) 가 들어감. */
.panel-zone {
  position: absolute;
  z-index: 19;
  pointer-events: auto;
}
.panel-top-left    { top: 24px; left: 24px; }
.panel-top-right   { top: 24px; right: 24px; }
.panel-bottom-left { bottom: 24px; left: 24px; }
.panel-bottom-right { bottom: 24px; right: 24px; }

/* 종료 (×) 버튼 — 다른 panel 들과 동일한 클릭 가능 영역 크기 (44px) 로 키워서 터치/마우스
 * 양쪽에서 안정. 빨강 톤으로 destructive action 강조. */
.exit-btn {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  border: 1px solid rgba(193, 69, 69, 0.35);
  background: white;
  color: #c14545;
  font-size: 24px;
  font-weight: 700;
  line-height: 1;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 14px rgba(40, 110, 160, 0.18);
  padding: 0;
  font-family: inherit;
}
.exit-btn:hover { background: #fbeaea; color: #a83b3b; }
.exit-btn:active { transform: scale(0.92); }
.exit-btn:focus-visible {
  outline: 3px solid rgba(193, 69, 69, 0.4);
  outline-offset: 3px;
}

.panel-box {
  position: relative;
  background: white;
  border-radius: 18px;
  box-shadow: 0 10px 30px rgba(40, 110, 160, 0.25);
  padding: 10px;
  width: 320px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}

/* 닫혀있을 때 코너에 떠 있는 작은 pill 토글. 클릭 시 panel 로 펼쳐짐. */
.panel-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border-radius: 999px;
  border: 1px solid rgba(58, 143, 194, 0.3);
  background: white;
  box-shadow: 0 4px 14px rgba(40, 110, 160, 0.18);
  cursor: pointer;
  font-size: 14px;
  font-weight: 700;
  color: #3a8fc2;
  font-family: inherit;
}
.panel-pill:hover { background: #f5fbff; }
.panel-pill:active { transform: scale(0.96); }
.pill-label { font-size: 13px; }

/* 열린 패널 wrapper — close 버튼을 panel-box 위 (above) 에 띄움. OXVisionPreview 의
 * 우상단 refresh ↻ 버튼과 충돌하지 않도록 box 안이 아니라 box 위 (별도 row) 로 배치. */
.panel-open {
  display: flex;
  flex-direction: column;
  align-items: flex-end;  /* close 버튼 오른쪽 정렬 — pill 위치와 시각적으로 일관 */
  gap: 6px;
}
.panel-close {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: 1px solid rgba(58, 143, 194, 0.3);
  background: white;
  color: #3a8fc2;
  font-size: 20px;
  font-weight: 700;
  line-height: 1;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 12px rgba(40, 110, 160, 0.18);
  font-family: inherit;
  padding: 0;
}
.panel-close:hover { background: #f5fbff; }
.panel-close:active { transform: scale(0.92); }

/* 내부 컴포넌트 사이즈 일괄 통일 — 세 패널이 동일한 box 로 보이게.
 * IntegratedCameraPreview, OXVisionPreview, UrdfViewer 가 각자 자체 CSS 로 다른
 * width/height 를 갖고 있어 :deep() 으로 override. */
.panel-box :deep(.cam-panel) { width: 100%; }
.panel-box :deep(.cam-panel video) { height: 200px; }
.panel-box :deep(.vision-panel) { width: 100%; }
.panel-box :deep(.vision-canvas) { height: 200px; }
.panel-box .sim-canvas-wrap {
  width: 100%;
  height: 200px;
  border-radius: 12px;
  overflow: hidden;
}

.panel-caption {
  margin: 0;
  color: #5b7a8c;
  font-size: 13px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  text-align: center;
  line-height: 1.3;
}

.real-badge {
  background: white;
  border-radius: 18px;
  box-shadow: 0 10px 30px rgba(40, 110, 160, 0.25);
  padding: 10px 18px;
  color: #2d8b57;
  font-size: 14px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.status-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.status-dot.status-sim {
  background: #d6a847;
  box-shadow: 0 0 0 3px rgba(214, 168, 71, 0.18);
}
.status-dot.status-real {
  background: #2d8b57;
  box-shadow: 0 0 0 3px rgba(45, 139, 87, 0.18);
}
.status-dot.status-vision {
  background: #3a8fc2;
  box-shadow: 0 0 0 3px rgba(58, 143, 194, 0.18);
}
.card h1 {
  margin: 0 0 16px;
  font-size: 56px;
  font-weight: 800;
  color: #286ea0;
  letter-spacing: -1.5px;
}
.subtitle {
  margin: 0 0 36px;
  color: #5b7a8c;
  font-size: 22px;
}
.primary {
  border: none;
  background: #3a8fc2;
  color: white;
  font-size: 22px;
  font-weight: 700;
  padding: 18px 52px;
  border-radius: 999px;
  cursor: pointer;
  box-shadow: 0 6px 18px rgba(58, 143, 194, 0.4);
  transition: transform 0.1s, background 0.15s;
  font-family: inherit;
}
.primary:hover {
  background: #2d7aa8;
  transform: translateY(-1px);
}
.secondary {
  border: 2px solid #b0c4d0;
  background: white;
  color: #5b7a8c;
  font-size: 22px;
  font-weight: 700;
  padding: 16px 50px;
  border-radius: 999px;
  cursor: pointer;
  transition: transform 0.1s, background 0.15s, border-color 0.15s;
  font-family: inherit;
}
.secondary:hover {
  border-color: #5b7a8c;
  background: #f6f9fb;
  transform: translateY(-1px);
}
.done-actions {
  display: flex;
  gap: 16px;
  justify-content: center;
}
.natural-shot-line {
  margin: -8px 0 24px;
  color: #5b7a8c;
  font-size: 16px;
  font-weight: 600;
}
.progress {
  font-size: 18px;
  color: #7a98ab;
  font-weight: 600;
  margin-bottom: 12px;
}
.result-badge {
  display: inline-block;
  padding: 8px 28px;
  border-radius: 999px;
  font-size: 26px;
  font-weight: 800;
  letter-spacing: 1px;
  margin-bottom: 16px;
  animation: result-pop 0.35s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.result-badge.is-correct {
  background: #e6f5ed;
  color: #2d8b57;
  border: 2px solid #2d8b57;
}
.result-badge.is-wrong {
  background: #fbeaea;
  color: #c14545;
  border: 2px solid #c14545;
}
@keyframes result-pop {
  from { transform: scale(0.6); opacity: 0; }
  to   { transform: scale(1);   opacity: 1; }
}
.running-score {
  margin: 16px 0 0;
  color: #5b7a8c;
  font-size: 18px;
  font-weight: 600;
}
.final-score {
  font-size: 0;
  margin: 8px 0 24px;
  line-height: 1;
}
.final-score .score-num {
  font-size: 120px;
  font-weight: 900;
  color: #286ea0;
  font-variant-numeric: tabular-nums;
}
.final-score .score-total {
  font-size: 56px;
  color: #7a98ab;
  font-weight: 700;
}
.q-text {
  margin: 0 0 32px;
  font-size: 38px;
  font-weight: 700;
  color: #1f3a4d;
  line-height: 1.35;
  word-break: keep-all;
}
.q-text.small {
  font-size: 28px;
  margin-bottom: 24px;
  color: #5b7a8c;
}
.markers {
  display: flex;
  gap: 36px;
  justify-content: center;
  margin: 12px 0 28px;
}
.marker {
  width: 140px;
  height: 140px;
  border-radius: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 72px;
  font-weight: 800;
  border: 6px solid currentColor;
  font-family: inherit;
}
.marker.o {
  color: #2d8b57;
  background: rgba(45, 139, 87, 0.08);
}
.marker.x {
  color: #c14545;
  background: rgba(193, 69, 69, 0.08);
}
.marker.clickable {
  cursor: pointer;
  padding: 0;
  transition: transform 0.12s ease, box-shadow 0.12s ease, background 0.12s ease;
}
.marker.clickable:hover {
  transform: translateY(-2px) scale(1.04);
  box-shadow: 0 10px 24px rgba(40, 110, 160, 0.18);
}
.marker.clickable:active {
  transform: translateY(0) scale(0.98);
}
.marker.clickable:focus-visible {
  outline: 4px solid rgba(58, 143, 194, 0.45);
  outline-offset: 4px;
}
.hint {
  margin: 0;
  color: #8aa6b8;
  font-size: 16px;
}
.answer-box {
  width: 220px;
  height: 220px;
  margin: 0 auto 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 10px solid currentColor;
}
.answer-box.is-o {
  color: #2d8b57;
  background: rgba(45, 139, 87, 0.1);
  border-radius: 50%;
}
.answer-box.is-x {
  color: #c14545;
  background: rgba(193, 69, 69, 0.1);
  border-radius: 24px;
}
.big-answer {
  font-size: 144px;
  font-weight: 900;
  line-height: 1;
}
.explanation {
  margin: 0 0 16px;
  font-size: 22px;
  color: #1f3a4d;
  font-weight: 600;
}
.status {
  margin: 0;
  color: #5b7a8c;
  font-size: 16px;
  font-style: italic;
}
.thinking-icon {
  font-size: 96px;
  margin: 8px 0 16px;
  animation: thinking-bounce 1.2s ease-in-out infinite alternate;
}
@keyframes thinking-bounce {
  from { transform: translateY(0) scale(1); }
  to   { transform: translateY(-6px) scale(1.05); }
}
.pulse {
  animation: pulse-tense 0.9s ease-in-out infinite alternate;
}
@keyframes pulse-tense {
  from { opacity: 0.55; }
  to   { opacity: 1; }
}
.ox-fade-enter-active,
.ox-fade-leave-active {
  transition: opacity 0.3s ease;
}
.ox-fade-enter-from,
.ox-fade-leave-to {
  opacity: 0;
}
</style>
