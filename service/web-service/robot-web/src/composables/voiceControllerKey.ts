import type { InjectionKey, Ref } from 'vue';
import type { VoiceController } from './useVoiceController';

export const VOICE_CONTROLLER_KEY: InjectionKey<VoiceController> =
  Symbol('voiceController');

/** 사용자가 시작 오버레이를 탭한 뒤 — 마이크 시각화 스트림을 세션 동안 한 번만 연다 */
export const VOICE_UI_SESSION_KEY: InjectionKey<Ref<boolean>> = Symbol('voiceUiSession');
