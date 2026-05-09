<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue';
import { storeToRefs } from 'pinia';
import { useModeStore } from '@/stores/mode';
import oxQuizData from '../../../../shared/ox_quiz.json';

interface OXQuestion {
  id: string;
  question: string;
  answer: 'O' | 'X';
  explanation: string;
}

const QUESTIONS_PER_ROUND = 3;
const COUNTDOWN_SECONDS = 5;
const TRAJECTORY_PLAY_MS = 6000;

type Phase = 'intro' | 'question' | 'reveal' | 'playback' | 'done';

const mode = useModeStore();
const { currentMode } = storeToRefs(mode);
const isActive = computed(() => currentMode.value === 'OX 퀴즈');

const phase = ref<Phase>('intro');
const questions = ref<OXQuestion[]>([]);
const currentIndex = ref(0);
const countdown = ref(COUNTDOWN_SECONDS);

let countdownTimer: number | null = null;
let phaseTimer: number | null = null;

function clearTimers(): void {
  if (countdownTimer != null) {
    window.clearInterval(countdownTimer);
    countdownTimer = null;
  }
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

async function dispatchTrajectory(answer: 'O' | 'X'): Promise<void> {
  try {
    await fetch('/api/noriarm/trajectory', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answer }),
    });
  } catch (err) {
    console.warn('[OXQuiz] trajectory dispatch failed', err);
  }
}

function startQuiz(): void {
  clearTimers();
  questions.value = pickQuestions();
  currentIndex.value = 0;
  startQuestion();
}

function startQuestion(): void {
  phase.value = 'question';
  countdown.value = COUNTDOWN_SECONDS;
  clearTimers();
  countdownTimer = window.setInterval(() => {
    countdown.value -= 1;
    if (countdown.value <= 0) {
      if (countdownTimer != null) {
        window.clearInterval(countdownTimer);
        countdownTimer = null;
      }
      void onCountdownEnd();
    }
  }, 1000);
}

async function onCountdownEnd(): Promise<void> {
  const q = questions.value[currentIndex.value];
  if (!q) return;
  phase.value = 'reveal';
  await dispatchTrajectory(q.answer);
  phase.value = 'playback';
  phaseTimer = window.setTimeout(() => {
    phaseTimer = null;
    if (currentIndex.value + 1 < questions.value.length) {
      currentIndex.value += 1;
      startQuestion();
    } else {
      phase.value = 'done';
    }
  }, TRAJECTORY_PLAY_MS);
}

function reset(): void {
  clearTimers();
  phase.value = 'intro';
  currentIndex.value = 0;
  questions.value = [];
}

watch(isActive, (active, prev) => {
  if (!active && prev) reset();
  if (active && !prev) phase.value = 'intro';
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
          <p class="subtitle">3문제를 낼게요. 마커를 O 또는 X 위에 올려놓으세요!</p>
          <button class="primary" @click="startQuiz">시작하기</button>
        </div>

        <!-- question -->
        <div v-else-if="phase === 'question' && currentQuestion" class="card question">
          <div class="progress">{{ progressLabel }}</div>
          <h2 class="q-text">{{ currentQuestion.question }}</h2>
          <div class="markers">
            <div class="marker o">O</div>
            <div class="marker x">X</div>
          </div>
          <div class="countdown" :class="{ urgent: countdown <= 2 }">
            {{ countdown }}
          </div>
          <p class="hint">5초 안에 답 위치를 정해주세요</p>
        </div>

        <!-- reveal + playback -->
        <div
          v-else-if="(phase === 'reveal' || phase === 'playback') && currentQuestion"
          class="card reveal"
        >
          <div class="progress">{{ progressLabel }}</div>
          <h2 class="q-text small">{{ currentQuestion.question }}</h2>
          <div class="answer-box" :class="currentQuestion.answer === 'O' ? 'is-o' : 'is-x'">
            <span class="big-answer">{{ currentQuestion.answer }}</span>
          </div>
          <p class="explanation">{{ currentQuestion.explanation }}</p>
          <p class="status">
            <span v-if="phase === 'reveal'">노리암이 답을 가리키러 갑니다…</span>
            <span v-else>로봇팔 재생 중…</span>
          </p>
        </div>

        <!-- done -->
        <div v-else-if="phase === 'done'" class="card done">
          <h1>퀴즈 끝!</h1>
          <p class="subtitle">잘했어요 👏</p>
          <button class="primary" @click="startQuiz">다시 하기</button>
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
.progress {
  font-size: 18px;
  color: #7a98ab;
  font-weight: 600;
  margin-bottom: 12px;
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
  width: 120px;
  height: 120px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 64px;
  font-weight: 800;
  border: 6px solid currentColor;
}
.marker.o {
  color: #2d8b57;
  background: rgba(45, 139, 87, 0.08);
}
.marker.x {
  color: #c14545;
  background: rgba(193, 69, 69, 0.08);
  border-radius: 18px;
}
.countdown {
  font-size: 96px;
  font-weight: 800;
  color: #3a8fc2;
  line-height: 1;
  margin: 8px 0;
  font-variant-numeric: tabular-nums;
  transition: color 0.2s, transform 0.2s;
}
.countdown.urgent {
  color: #d96363;
  animation: pulse 0.6s ease-in-out infinite alternate;
}
@keyframes pulse {
  from { transform: scale(1); }
  to   { transform: scale(1.12); }
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
.ox-fade-enter-active,
.ox-fade-leave-active {
  transition: opacity 0.3s ease;
}
.ox-fade-enter-from,
.ox-fade-leave-to {
  opacity: 0;
}
</style>
