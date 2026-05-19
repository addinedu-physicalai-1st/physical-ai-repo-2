<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue';
import { storeToRefs } from 'pinia';
import { useVoiceStore } from '@/stores/voice';
import { useModeStore } from '@/stores/mode';
import { VOICE_CONTROLLER_KEY, VOICE_UI_SESSION_KEY } from '@/composables/voiceControllerKey';
import { useAudioLevel } from '@/composables/useAudioLevel';
import { usePhoneViewport } from '@/common/usePhoneViewport';
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

const voiceUiSession = inject(VOICE_UI_SESSION_KEY, ref(false));

const audio = useAudioLevel();
const isPhone = usePhoneViewport();

/** SiriBlob 에 줄 audio level — phone 은 useServerSTT 의 stream RMS, 데스크톱은 useAudioLevel. */
const micLevel = computed(() => (isPhone.value ? ctrl.micLevel.value : audio.level.value));

// voiceMode 토글 — STT on/off 전환 (초기 시작은 App.vue handleStart 가 처리)
watch(voiceMode, (next, prev) => {
  if (next === 'voice' && prev === 'text') ctrl.start();
  else if (next === 'text' && prev === 'voice') ctrl.stop();
});

// 시각화용 mic 스트림 — listening 상태에서만 켠다. idle / speaking / dispatching
// 동안은 SiriBlob 자체가 안 보이므로 RAF + Web Audio 비용 절감.
// phone 은 useServerSTT 의 stream RMS 를 재사용하므로 audio-level 의 두 번째
// getUserMedia 가 필요 없음 (실제로 STT 마이크 입력을 굶기는 부작용도 있음).
watch(
  [voiceMode, voiceUiSession, state],
  async ([vm, session, st]) => {
    const shouldRun = !isPhone.value && vm === 'voice' && session && st === 'listening';
    if (shouldRun) {
      try {
        await audio.start();
      } catch (e) {
        console.warn('[Mic] Failed to start audio visualization:', e);
      }
    } else {
      audio.stop();
    }
  },
  { immediate: true },
);

const showLoader = computed(
  () => voiceMode.value === 'voice' && state.value === 'dispatching'
);
const showBlob = computed(
  () => voiceMode.value === 'voice' && state.value === 'listening'
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
          <SiriBlob v-else-if="showBlob" :level="micLevel" :state="state" />
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

/* 휴대전화 공통: SiriBlob 자체 크기 축소 (interactive 한 발화 반응은 SiriBlob 의 scale 로 충분히 잘 보임) */
@media (max-width: 768px), (pointer: coarse) {
  .dock {
    bottom: calc(env(safe-area-inset-bottom, 0px) + 16px);
    width: min(96vw, 460px);
    min-height: 0;
    gap: 8px;
  }
  .anim-slot {
    width: 76px;
    height: 76px;
  }
  .text-mode-btn {
    width: 38px;
    height: 38px;
  }
}

/* 가로 휴대전화: 화면이 짧음 — dock 위치는 화면 가운데 그대로 (hamburger drawer 로 modes 가 사라졌으므로) */
@media (pointer: coarse) and (orientation: landscape),
       (max-height: 500px) and (orientation: landscape) {
  .dock {
    bottom: calc(env(safe-area-inset-bottom, 0px) + 2px);
    width: min(50vw, 260px);
    gap: 2px;
  }
  .anim-slot {
    width: 56px;
    height: 56px;
  }
  .text-mode-btn {
    width: 32px;
    height: 32px;
  }
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
