import { defineStore } from 'pinia';
import { ref } from 'vue';

export type VoiceState =
  | 'idle'
  | 'wake_detected'
  | 'listening'
  | 'dispatching'
  | 'speaking'
  | 'cooldown';
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
  const robotReply = ref<string>('');
  const currentChar = ref<string>('');
  /** 0~1 Web Audio RMS — 말할 때 입 벌림에 섞어 대화감(오·아 리듬) 보강 */
  const speechEnvelope = ref(0);

  function setState(next: VoiceState): void {
    state.value = next;
  }

  function setSttText(text: string): void {
    sttText.value = text;
    if (text && state.value !== 'dispatching') {
      robotReply.value = '';
    }
  }

  function setLastSpokenText(text: string): void {
    lastSpokenText.value = text;
  }

  function setRobotReply(text: string): void {
    robotReply.value = text;
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
  
  function setCurrentChar(char: string): void {
    currentChar.value = char;
  }

  function setSpeechEnvelope(value: number): void {
    speechEnvelope.value = Math.min(1, Math.max(0, value));
  }

  return {
    state,
    sttText,
    lastSpokenText,
    robotReply,
    isSpeaking,
    lastError,
    inputLocked,
    voiceMode,
    currentChar,
    speechEnvelope,
    setState,
    setSttText,
    setLastSpokenText,
    setRobotReply,
    setCurrentChar,
    setSpeechEnvelope,
    setSpeaking,
    setError,
    setInputLocked,
    setVoiceMode,
  };
});
