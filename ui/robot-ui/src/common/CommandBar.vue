<script setup lang="ts">
import { computed, inject, ref } from 'vue';
import { storeToRefs } from 'pinia';
import { useVoiceStore } from '@/stores/voice';
import { VOICE_CONTROLLER_KEY } from '@/composables/voiceControllerKey';

const voice = useVoiceStore();
const { sttText } = storeToRefs(voice);
const controller = inject(VOICE_CONTROLLER_KEY);
if (!controller) throw new Error('VOICE_CONTROLLER_KEY not provided');
const ctrl = controller;

const isSending = ref(false);
const inputEl = ref<HTMLInputElement | null>(null);

function switchToVoice(): void {
  voice.setVoiceMode('voice');
}

const value = computed({
  get: () => sttText.value,
  set: (v: string) => voice.setSttText(v),
});

function onFocus(): void {
  voice.setInputLocked(true);
}

function onBlur(): void {
  voice.setInputLocked(false);
}

async function submit(): Promise<void> {
  const trimmed = value.value.trim();
  if (!trimmed || isSending.value) return;

  isSending.value = true;
  try {
    await ctrl.processCommand(trimmed);
  } catch (err) {
    voice.setError((err as Error).message);
  } finally {
    isSending.value = false;
    voice.setSttText('');
    voice.setInputLocked(false);
    inputEl.value?.blur();
  }
}
</script>

<template>
  <div class="bar">
    <button class="mic" @click="switchToVoice" aria-label="음성 모드로 전환">
      <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z" />
        <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
        <line x1="12" y1="19" x2="12" y2="23" />
        <line x1="8" y1="23" x2="16" y2="23" />
      </svg>
    </button>
    <input
      ref="inputEl"
      v-model="value"
      class="input"
      placeholder="명령어를 입력하세요"
      :disabled="isSending"
      @focus="onFocus"
      @blur="onBlur"
      @keyup.enter="submit"
    />
    <button
      class="send"
      :disabled="!value.trim() || isSending"
      @click="submit"
      aria-label="전송"
    >
      <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
        <line x1="22" y1="2" x2="11" y2="13" />
        <polygon points="22 2 15 22 11 13 2 9 22 2" />
      </svg>
    </button>
  </div>
</template>

<style scoped>
.bar {
  flex: 1;
  background: white;
  border-radius: 18px;
  padding: 10px 12px;
  display: flex;
  align-items: center;
  gap: 10px;
  box-shadow: 0 8px 28px color-mix(in srgb, var(--primary) 18%, transparent);
}
.mic {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  background: transparent;
  color: var(--primary);
  border: none;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background 0.12s, transform 0.1s;
  flex-shrink: 0;
}
.mic:hover {
  background: color-mix(in srgb, var(--primary) 8%, transparent);
  transform: scale(1.05);
}
.input {
  flex: 1;
  border: none;
  outline: none;
  font-size: 20px;
  font-family: inherit;
  background: transparent;
  color: #333;
  padding: 8px 4px;
}
.input::placeholder {
  color: #b8b8b8;
  font-size: 17px;
}
.input:disabled {
  opacity: 0.5;
}
.send {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: var(--primary);
  color: white;
  border: none;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background 0.1s, transform 0.1s;
  flex-shrink: 0;
}
.send:hover:not(:disabled) {
  background: color-mix(in srgb, var(--primary) 80%, #000);
  transform: scale(1.05);
}
.send:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
</style>
