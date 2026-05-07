<script setup lang="ts">
import { computed } from 'vue';
import { storeToRefs } from 'pinia';
import type { EmotionId, RobotId } from '@/config/robots';
import { useModeStore } from '@/stores/mode';
import { useVoiceStore } from '@/stores/voice';
import ShaderFace from '@/common/ShaderFace.vue';

defineProps<{ emotion: EmotionId }>();

const voice = useVoiceStore();
const { state, voiceMode } = storeToRefs(voice);

const mode = useModeStore();
const { robot } = storeToRefs(mode);

// 표정 색은 emotion 별이 아닌 로봇 브랜드 primary 로 통일
const PRIMARY_BY_ROBOT: Record<RobotId, string> = {
  eduping: '#db2777',
  gogoping: '#bef32c',
  noriarm: '#3a8fc2',
};

const accent = computed(() => PRIMARY_BY_ROBOT[robot.value.id]);
const isListening = computed(
  () => state.value === 'listening' || state.value === 'wake_detected'
);

const statusLabel: Partial<Record<typeof state.value, string>> = {
  wake_detected: '대답 중',
  listening: '듣는 중',
  dispatching: '해석 중',
};
const statusColor: Partial<Record<typeof state.value, string>> = {
  wake_detected: '#f59e0b',
  listening: '#22c55e',
  dispatching: '#60a5fa',
};
const showStatus = computed(() => state.value in statusLabel);
const activeLabel = computed(() => statusLabel[state.value] ?? '');
const activeColor = computed(() => statusColor[state.value] ?? '#fff');

// 웨이크워드 대기 중일 때 로봇이 사용자에게 말 거는 형태의 말풍선
const showWakePrompt = computed(
  () => voiceMode.value === 'voice' && state.value === 'idle'
);
const wakePromptText = computed(
  () => `"${robot.value.wakeWord}" 을 부르고 명령해주세요`
);
const isThinking = computed(() => state.value === 'dispatching');
</script>

<template>
  <div class="stage">
    <div class="actor-wrapper">
      <div
        class="face"
        :class="{ listening: isListening }"
        :style="{ '--accent': accent }"
      >
        <Transition name="bubble-pop">
          <div v-if="showWakePrompt" class="wake-bubble" role="status">
            {{ wakePromptText }}
          </div>
        </Transition>
        <span class="notch">
          <span class="notch-dot"></span>
        </span>
        <Transition name="forehead-fade">
          <div
            v-if="showStatus"
            class="forehead-status"
            :style="{ '--dot-color': activeColor }"
          >
            <span class="status-dot"></span>
            <span class="status-label">{{ activeLabel }}</span>
          </div>
        </Transition>
        <div class="screen">
          <ShaderFace 
            :emotion="emotion" 
            :accent="accent" 
            :thinking="isThinking"
            :speaking="state === 'speaking'"
          />
          
          <Transition name="sleep-fx">
            <div v-if="emotion === 'sleep'" class="sleep-fx" aria-hidden="true">
              <div class="zzz">
                <span>z</span>
                <span>z</span>
                <span>z</span>
              </div>
            </div>
          </Transition>
        </div>
      </div>

      <!-- Premium Subtitle Overlay (Moved Outside for Clarity) -->
      <div class="subtitle-container" v-if="state !== 'idle' && state !== 'cooldown'">
        <Transition name="fade" mode="out-in">
          <div :key="state" class="subtitle-text">
            <span v-if="state === 'listening'" class="listening-text">
              {{ voice.sttText || '듣고 있어요...' }}
            </span>
            <span v-else-if="state === 'dispatching'" class="thinking-text">
              {{ voice.lastSpokenText }}
            </span>
            <span v-else-if="state === 'speaking'" class="speaking-text">
              {{ voice.robotReply }}
            </span>
          </div>
        </Transition>
      </div>
    </div>
  </div>
</template>

<style scoped>
.stage {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  padding-bottom: 14vh;
}

.face {
  --accent: #94a3b8;
  position: relative;
  width: min(80vw, calc(60vh * 4 / 3));
  aspect-ratio: 4 / 3;
  padding: 16px;
  background: linear-gradient(180deg, #ffffff 0%, #fdf4f7 100%);
  border-radius: 36px;
  box-shadow:
    0 18px 44px rgba(196, 84, 111, 0.18),
    0 0 0 1.5px color-mix(in srgb, var(--accent) 40%, transparent),
    inset 0 1px 0 rgba(255, 255, 255, 0.95);
  animation: bob 4s ease-in-out infinite;
  transition: box-shadow 0.5s ease;
}

.face::after {
  content: '';
  position: absolute;
  inset: -2px;
  border-radius: 38px;
  pointer-events: none;
  opacity: 0;
  box-shadow: 0 0 0 0 var(--accent);
  transition: opacity 0.3s ease;
}
.face.listening::after {
  opacity: 1;
  animation: glow 2.4s ease-in-out infinite;
}

.wake-bubble {
  position: absolute;
  top: -28px;
  left: -16px;
  transform: translateY(-100%);
  max-width: 320px;
  padding: 14px 22px;
  background: #ffffff;
  color: #2a3441;
  font-size: 20px;
  font-weight: 700;
  line-height: 1.35;
  border-radius: 22px;
  border: 2px solid color-mix(in srgb, var(--accent) 55%, transparent);
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.12);
  white-space: nowrap;
  z-index: 3;
  animation: bubble-bob 3.2s ease-in-out infinite;
}
.wake-bubble::before,
.wake-bubble::after {
  content: '';
  position: absolute;
  bottom: -14px;
  left: 42px;
  width: 22px;
  height: 22px;
  background: #ffffff;
  border-right: 2px solid color-mix(in srgb, var(--accent) 55%, transparent);
  border-bottom: 2px solid color-mix(in srgb, var(--accent) 55%, transparent);
  transform: rotate(45deg);
  border-bottom-right-radius: 4px;
}
.wake-bubble::before {
  bottom: -8px;
  left: 26px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #ffffff;
  border: 2px solid color-mix(in srgb, var(--accent) 55%, transparent);
  transform: none;
}
.bubble-pop-enter-active {
  transition: opacity 0.32s ease, transform 0.36s cubic-bezier(0.34, 1.5, 0.5, 1);
}
.bubble-pop-leave-active {
  transition: opacity 0.18s ease, transform 0.22s ease;
}
.bubble-pop-enter-from,
.bubble-pop-leave-to {
  opacity: 0;
  transform: translateY(-90%) scale(0.8);
}
@keyframes bubble-bob {
  50% {
    transform: translateY(calc(-100% - 4px));
  }
}

.notch {
  position: absolute;
  top: 6px;
  left: 50%;
  transform: translateX(-50%);
  width: 64px;
  height: 7px;
  background: #2a3441;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1;
}
.notch-dot {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 4px var(--accent);
  transition: background 0.4s ease, box-shadow 0.4s ease;
}

.forehead-status {
  position: absolute;
  top: 20px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 3;
  display: flex;
  align-items: center;
  gap: 7px;
  background: rgba(10, 13, 20, 0.62);
  backdrop-filter: blur(8px);
  border-radius: 999px;
  padding: 5px 14px 5px 10px;
  white-space: nowrap;
  pointer-events: none;
}
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--dot-color);
  box-shadow: 0 0 6px var(--dot-color);
  animation: status-pulse 1.4s ease-in-out infinite;
  flex-shrink: 0;
}
.status-label {
  color: rgba(255, 255, 255, 0.92);
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.03em;
}
.forehead-fade-enter-active,
.forehead-fade-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.forehead-fade-enter-from,
.forehead-fade-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(-4px);
}
@keyframes status-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.45; transform: scale(0.8); }
}

.screen {
  position: relative;
  width: 100%;
  height: 100%;
  border-radius: 22px;
  overflow: hidden;
  background: radial-gradient(
    ellipse at 50% 55%,
    color-mix(in srgb, var(--accent) 6%, #0a0d14) 0%,
    #0a0d14 70%
  );
  box-shadow: inset 0 4px 14px rgba(0, 0, 0, 0.35);
}

.sleep-fx {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 2;
}

/* 우상단에서 z 가 작게 등장해 커지면서 위로 떠오름 */
.zzz {
  position: absolute;
  top: 14%;
  right: 14%;
  width: 80px;
  height: 120px;
  pointer-events: none;
}
.zzz span {
  position: absolute;
  bottom: 0;
  left: 50%;
  font-family: -apple-system, 'Pretendard', sans-serif;
  font-style: italic;
  font-weight: 800;
  color: var(--accent);
  text-shadow: 0 0 12px var(--accent);
  opacity: 0;
  animation: zzz-float 2.4s ease-out infinite;
  transform-origin: 50% 100%;
}
.zzz span:nth-child(1) {
  animation-delay: 0s;
}
.zzz span:nth-child(2) {
  animation-delay: 0.8s;
}
.zzz span:nth-child(3) {
  animation-delay: 1.6s;
}
@keyframes zzz-float {
  0% {
    opacity: 0;
    font-size: 18px;
    transform: translate(-50%, 0);
  }
  15% {
    opacity: 1;
  }
  100% {
    opacity: 0;
    font-size: 56px;
    transform: translate(-160%, -110px);
  }
}

.sleep-fx-enter-active,
.sleep-fx-leave-active {
  transition: opacity 0.3s ease;
}
.sleep-fx-enter-from,
.sleep-fx-leave-to {
  opacity: 0;
}


.actor-wrapper {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 32px;
  width: 100%;
}

/* --- PREMIUM SUBTITLES --- */
.subtitle-container {
  width: min(75vw, 600px);
  z-index: 10;
  pointer-events: none;
}

.subtitle-text {
  background: rgba(10, 13, 20, 0.82);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 24px;
  padding: 16px 32px;
  color: white;
  text-align: center;
  font-size: 1.35rem;
  font-weight: 700;
  line-height: 1.45;
  box-shadow: 
    0 12px 40px rgba(0, 0, 0, 0.25),
    0 0 0 1px rgba(0, 0, 0, 0.1);
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.5);
}

.listening-text {
  color: #a3e635; /* Neon lime */
  opacity: 0.9;
}

.thinking-text {
  color: #60a5fa; /* Soft blue */
}

.speaking-text {
  color: white;
  font-size: 1.3rem;
}

/* Animations */
.fade-enter-active,
.fade-leave-active {
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}

.fade-enter-from {
  opacity: 0;
  transform: translateY(10px) scale(0.98);
}

.fade-leave-to {
  opacity: 0;
  transform: translateY(-10px) scale(0.98);
}

@keyframes bob {
  50% {
    transform: translateY(-6px);
  }
}
@keyframes glow {
  0%, 100% {
    box-shadow: 0 0 0 0 color-mix(in srgb, var(--accent) 60%, transparent);
  }
  50% {
    box-shadow: 0 0 0 8px color-mix(in srgb, var(--accent) 0%, transparent),
      0 0 24px color-mix(in srgb, var(--accent) 50%, transparent);
  }
}
</style>
