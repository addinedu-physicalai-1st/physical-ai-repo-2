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

export interface ConfirmRequest {
  /** TTS 로 사용자에게 질문할 문장. */
  prompt: string;
  /** 디버그/로그용 context tag — 예: 'rhythm_play', 'game_exit'. */
  context: string;
  /** 사용자가 동의 발화 시 호출. */
  onConfirm: () => void | Promise<void>;
  /** 사용자가 거절 발화 시 호출. 기본 noop. */
  onCancel: () => void | Promise<void>;
}

export const useVoiceStore = defineStore('voice', () => {
  const state = ref<VoiceState>('idle');
  const sttText = ref<string>('');
  const lastSpokenText = ref<string>('');
  const isSpeaking = ref<boolean>(false);
  const lastError = ref<string | null>(null);
  const inputLocked = ref<boolean>(false);
  const voiceMode = ref<VoiceMode>('voice');
  const robotReply = ref<string>('');
  const currentChar = ref<string>('');
  const speechEnvelope = ref(0);
  const lastWakeAt = ref<number>(0);
  /** Active confirm 사이클 — voiceController.startConfirm 호출 후 useVoiceController
   *  가 setConfirm 으로 set. server 의 confirm_yes/no intent 도착 시 callback
   *  실행 후 clearConfirm. UI 컴포넌트는 이 ref 를 watch 해서 popup 표시. */
  const confirm = ref<ConfirmRequest | null>(null);

  function setState(next: VoiceState): void { state.value = next; }
  function setSttText(text: string): void {
    sttText.value = text;
    if (text && state.value !== 'dispatching') robotReply.value = '';
  }
  function setLastSpokenText(text: string): void { lastSpokenText.value = text; }
  function setRobotReply(text: string): void { robotReply.value = text; }
  function setSpeaking(value: boolean): void { isSpeaking.value = value; }
  function setError(message: string | null): void { lastError.value = message; }
  function setInputLocked(value: boolean): void { inputLocked.value = value; }
  function setVoiceMode(mode: VoiceMode): void { voiceMode.value = mode; }
  function setCurrentChar(char: string): void { currentChar.value = char; }
  function setSpeechEnvelope(value: number): void {
    speechEnvelope.value = Math.min(1, Math.max(0, value));
  }
  function bumpWake(): void { lastWakeAt.value = Date.now(); }
  function setConfirm(req: ConfirmRequest | null): void { confirm.value = req; }
  function clearConfirm(): void { confirm.value = null; }

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
    lastWakeAt,
    confirm,
    bumpWake,
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
    setConfirm,
    clearConfirm,
  };
});
