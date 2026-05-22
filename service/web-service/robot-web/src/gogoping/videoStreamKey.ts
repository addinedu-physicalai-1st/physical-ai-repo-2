import type { InjectionKey } from 'vue';
import type { UseVideoStream } from './composables/useVideoStream';

export const VIDEO_STREAM_KEY: InjectionKey<UseVideoStream> = Symbol('gogoping-video-stream');
