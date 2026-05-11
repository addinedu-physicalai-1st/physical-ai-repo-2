<script setup lang="ts">
import { computed, inject, watch } from 'vue';
import { storeToRefs } from 'pinia';
import { useVoiceStore } from '@/stores/voice';
import { useModeStore } from '@/stores/mode';
import { VOICE_CONTROLLER_KEY } from '@/composables/voiceControllerKey';
import { useAudioLevel } from '@/composables/useAudioLevel';
import { faceAccent } from '@/config/colors';
import CommandBar from './CommandBar.vue';
import SiriBlob from './SiriBlob.vue';
import DispatchingLoader from './DispatchingLoader.vue';

const voice = useVoiceStore();
const { voiceMode, state } = storeToRefs(voice);

const { robot } = storeToRefs(useModeStore());
const primary = computed(() => faceAccent(robot.value.id));

const controller = inject(VOICE_CONTROLLER_KEY);
if (!controller) throw new Error('VOICE_CONTROLLER_KEY not provided');
const ctrl = controller;

const audio = useAudioLevel();

// voiceMode 토글 — STT on/off 전환 (초기 시작은 App.vue handleStart 가 처리)
watch(voiceMode, (next, prev) => {
  if (next === 'voice' && prev === 'text') ctrl.start();
  else if (next === 'text' && prev === 'voice') ctrl.stop();
});

// listening/wake_detected 동안 마이크 시각화용 AudioContext on
watch([voiceMode, state], async ([vm, st]) => {
  const wantAudio = vm === 'voice' && (st === 'listening' || st === 'wake_detected');
  if (wantAudio) {
    try {
      await audio.start();
    } catch (e) {
      console.warn('[Mic] Failed to start audio visualization:', e);
    }
  } else {
    audio.stop();
  }
});

const showLoader = computed(
  () => voiceMode.value === 'voice' && state.value === 'dispatching'
);

function switchToText(): void {
  voice.setVoiceMode('text');
}
</script>

<template>
  <div class="dock" :style="{ '--primary': primary }">
    <!-- Legacy caption hidden in favor of Premium Subtitles in EmotionDisplay -->
    <!-- <div class="caption-container">
      <VoiceCaption :text="captionText" />
    </div> -->
    <Transition name="dock-swap" mode="out-in">
      <CommandBar v-if="voiceMode === 'text'" key="text" />
      <div v-else key="voice" class="voice-area">
        <div class="anim-slot">
          <DispatchingLoader v-if="showLoader" />
          <SiriBlob v-else :level="audio.level.value" :state="state" />
          <button class="text-mode-btn" @click="switchToText" aria-label="타이핑 모드로 전환">
            <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <rect x="2" y="6" width="20" height="12" rx="2" />
              <path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10" />
            </svg>
          </button>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.dock {
  position: absolute;
  left: 50%;
  bottom: 60px;
  transform: translateX(-50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  gap: 16px;
  z-index: 15;
  width: min(560px, calc(100vw - 200px));
  min-height: 200px;
}
.caption-container {
  display: flex;
  justify-content: center;
  width: 100%;
}
.dock-swap-enter-active {
  transition: opacity 0.32s ease, transform 0.36s cubic-bezier(0.34, 1.5, 0.5, 1);
}
.dock-swap-leave-active {
  transition: opacity 0.18s ease, transform 0.22s ease;
}
.dock-swap-enter-from,
.dock-swap-leave-to {
  opacity: 0;
  transform: scale(0.7);
}
.voice-area {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}
.anim-slot {
  position: relative;
  width: 150px;
  height: 150px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.text-mode-btn {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 52px;
  height: 52px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.9);
  color: var(--primary);
  border: none;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background 0.12s, color 0.12s, transform 0.1s;
  box-shadow: 0 4px 14px color-mix(in srgb, var(--primary) 25%, transparent);
  z-index: 2;
  backdrop-filter: blur(4px);
}
.text-mode-btn:hover {
  background: var(--primary);
  color: white;
  transform: translate(-50%, -50%) scale(1.08);
}
</style>
