import type { InjectionKey, Ref } from 'vue';

export type VideoStreamStatus = 'idle' | 'connecting' | 'connected' | 'closed';

export interface VideoStreamProvider {
  stream: Ref<MediaStream | null>;
  status: Ref<VideoStreamStatus>;
}

export const VIDEO_STREAM_KEY: InjectionKey<VideoStreamProvider> = Symbol('gogoping-video-stream');
