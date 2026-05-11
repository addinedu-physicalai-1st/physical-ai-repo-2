<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue';
import { storeToRefs } from 'pinia';
import { useModeStore } from '@/stores/mode';
import oxQuizData from '../../../../shared/ox_quiz.json';
import UrdfViewer from '@/noriarm/UrdfViewer.vue';
import OXVisionPreview from '@/noriarm/OXVisionPreview.vue';

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

// reveal/playback 단계 동안 중복 클릭 방지.
const submitting = ref(false);

const isCorrect = computed(
  () => userClicked.value !== null && currentQuestion.value?.answer === userClicked.value,
);

let phaseTimer: number | null = null;

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
  startQuestion();
}

function startQuestion(): void {
  clearTimers();
  submitting.value = false;
  userClicked.value = null;
  phase.value = 'question';
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

  phase.value = 'thinking';
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
  submitting.value = false;
  phase.value = 'intro';
  currentIndex.value = 0;
  questions.value = [];
  score.value = 0;
  userClicked.value = null;
}

watch(isActive, (active, prev) => {
  if (!active && prev) reset();
  if (active && !prev) {
    phase.value = 'intro';
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
          <div class="done-actions">
            <button class="primary" @click="startQuiz">다시 하기</button>
            <button class="secondary" @click="exitToIdle">그만 하기</button>
          </div>
        </div>

        <!-- 좌하단 floating: 카메라 라이브 뷰 + 카메라 셀렉트 -->
        <div class="vision-float">
          <OXVisionPreview />
          <p class="vision-caption">
            <span class="status-dot status-vision" />
            보드 인식 카메라
          </p>
        </div>

        <!-- 우하단 floating: sim 일 때 URDF 뷰어, real 일 때 연결 배지 -->
        <div v-if="showSimViewer" class="viewer-float sim">
          <div class="viewer-float-canvas">
            <UrdfViewer />
          </div>
          <p class="viewer-float-caption">
            <span class="status-dot status-sim" />
            노리암 시뮬레이션
          </p>
        </div>
        <div v-else class="viewer-float real">
          <span class="status-dot status-real" />
          실물 노리암 연결됨
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
/* 우하단 floating 뷰어 패널. 카드 위로 살짝 올라와도 z-index 로 OX 오버레이 안에 정착. */
.viewer-float {
  position: absolute;
  right: 24px;
  bottom: 24px;
  background: white;
  border-radius: 18px;
  box-shadow: 0 10px 30px rgba(40, 110, 160, 0.25);
  padding: 8px 8px 6px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}
.viewer-float.sim {
  width: 320px;
}
.viewer-float-canvas {
  width: 100%;
  height: 240px;
  border-radius: 12px;
  overflow: hidden;
}
.viewer-float-caption {
  margin: 0;
  color: #5b7a8c;
  font-size: 13px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.viewer-float.real {
  padding: 10px 18px;
  color: #2d8b57;
  font-size: 14px;
  font-weight: 700;
  display: inline-flex;
  flex-direction: row;
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
.vision-float {
  position: absolute;
  left: 24px;
  bottom: 24px;
  background: white;
  border-radius: 18px;
  box-shadow: 0 10px 30px rgba(40, 110, 160, 0.25);
  padding: 10px 10px 8px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}
.vision-caption {
  margin: 0;
  color: #5b7a8c;
  font-size: 13px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 6px;
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
