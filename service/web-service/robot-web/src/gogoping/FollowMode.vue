<script setup lang="ts">
import { inject } from 'vue';
import { VIDEO_STREAM_KEY } from './videoStreamKey';
import { useVideoStream } from './composables/useVideoStream';
import { useTrackingStateWs } from './composables/useTrackingStateWs';
import BboxOverlay from './BboxOverlay.vue';
import FollowTelemetry from './FollowTelemetry.vue';

defineEmits<{ (e: 'stop'): void }>();

// 영상은 App.vue 가 provide 한 공유 인스턴스 — 인증 모달과 같은 stream.
const injected = inject(VIDEO_STREAM_KEY, null);
const stream = injected ?? useVideoStream('gogoping');

const tracking = useTrackingStateWs();
</script>

<template>
  <div class="follow-mode">
    <div class="video-wrap">
      <img
        v-if="stream.frameUrl.value"
        :src="stream.frameUrl.value"
        class="video"
        alt="follow camera"
      />
      <div v-else class="placeholder">영상 대기 중…</div>

      <BboxOverlay :state="tracking.state.value" />
    </div>

    <FollowTelemetry class="telemetry-panel" :state="tracking.state.value" />

    <button type="button" class="stop-btn" @click="$emit('stop')">정지</button>
  </div>
</template>

<style scoped>
.follow-mode {
  position: relative;
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
}
.video-wrap {
  position: relative;
  width: min(800px, 92vw);
  aspect-ratio: 4 / 3;
  background: #000;
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 12px 36px rgba(0, 0, 0, 0.35);
}
.video {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #888;
}
.telemetry-panel {
  width: min(800px, 92vw);
}
.stop-btn {
  margin-top: 4px;
  padding: 12px 32px;
  background: #ef4444;
  color: white;
  border: none;
  border-radius: 999px;
  font-size: 16px;
  font-weight: 800;
  cursor: pointer;
  font-family: inherit;
  letter-spacing: -0.3px;
  box-shadow: 0 8px 20px rgba(239, 68, 68, 0.35);
}
.stop-btn:hover { background: #dc2626; }
.stop-btn:active { transform: translateY(1px); }

@media (max-width: 768px) {
  .video-wrap { width: 96vw; }
  .telemetry-panel { width: 96vw; }
  .stop-btn { padding: 10px 24px; font-size: 14px; }
}
</style>
