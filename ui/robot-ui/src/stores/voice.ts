import { defineStore } from 'pinia';
import { ref } from 'vue';

export type VoiceState = 'idle' | 'wake_detected' | 'listening' | 'dispatching' | 'cooldown';
export type VoiceMode = 'voice' | 'text';

export const useVoiceStore = defineStore('voice', () => {
  const state = ref<VoiceState>('idle');
  const sttText = ref<string>('');
  const lastSpokenText = ref<string>('');
  const isSpeaking = ref<boolean>(false);
  const lastError = ref<string | null>(null);
  // 사용자가 입력창을 직접 편집 중인 동안에는 STT 결과로 덮어쓰지 않는다
  const inputLocked = ref<boolean>(false);
  const voiceMode = ref<VoiceMode>('voice');

  function setState(next: VoiceState): void {
    state.value = next;
  }

  function setSttText(text: string): void {
    sttText.value = text;
  }

  function setLastSpokenText(text: string): void {
    lastSpokenText.value = text;
  }

  function setSpeaking(value: boolean): void {
    isSpeaking.value = value;
  }

  function setError(message: string | null): void {
    lastError.value = message;
  }

  function setInputLocked(value: boolean): void {
    inputLocked.value = value;
  }

  function setVoiceMode(mode: VoiceMode): void {
    voiceMode.value = mode;
  }

  return {
    state,
    sttText,
    lastSpokenText,
    isSpeaking,
    lastError,
    inputLocked,
    voiceMode,
    setState,
    setSttText,
    setLastSpokenText,
    setSpeaking,
    setError,
    setInputLocked,
    setVoiceMode,
  };
});
