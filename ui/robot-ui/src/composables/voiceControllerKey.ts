import type { InjectionKey } from 'vue';
import type { VoiceController } from './useVoiceController';

export const VOICE_CONTROLLER_KEY: InjectionKey<VoiceController> =
  Symbol('voiceController');
