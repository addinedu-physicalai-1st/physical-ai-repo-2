<script setup lang="ts">
import { inject, nextTick, onMounted, ref, watch } from 'vue';
import { VIDEO_STREAM_KEY } from './videoStreamKey';
import { forceReconnectWebRTCStream, useWebRTCStream } from './composables/useWebRTCStream';
import { useTrackingStateWs } from './composables/useTrackingStateWs';
import BboxOverlay from './BboxOverlay.vue';
import FollowTelemetry from './FollowTelemetry.vue';

defineEmits<{ (e: 'stop'): void }>();

// 영상은 App.vue 가 provide 한 공유 인스턴스 — 인증 모달과 같은 stream.
const injected = inject(VIDEO_STREAM_KEY, null);
const ownHandle = injected ? null : useWebRTCStream('robot-web');
const stream = injected ?? { stream: ownHandle!.stream, status: ownHandle!.status };

const videoEl = ref<HTMLVideoElement | null>(null);
// watch source 에 videoEl 도 포함 — stream 이 mount 전에 set 되거나 videoEl 이
// stream set 후 mount 되는 race 모두 대응.
watch(
  [() => stream.stream.value, videoEl],
  ([s, el]) => {
    if (el) el.srcObject = s ?? null;
  },
  { immediate: true },
);

// 모드 재진입 시 track ended 검사 → 강제 reconnect, 살아있으면 디코더 재시동.
// stream 이 아직 null 이면 watch immediate 가 ontrack 시 처리하므로 여기선 return.
onMounted(async () => {
  const el = videoEl.value;
  const s = stream.stream.value;
  if (!el || !s) return;
  if (s.getVideoTracks().length === 0 || s.getVideoTracks().every(t => t.readyState === 'ended')) {
    forceReconnectWebRTCStream();
    return;
  }
  el.srcObject = null;
  await nextTick();
  el.srcObject = s;
  try { await el.play(); } catch { /* autoplay policy — 무시 */ }
});

const tracking = useTrackingStateWs();
</script>

<template>
  <div class="follow-mode">
    <div class="video-wrap">
      <video
        ref="videoEl"
        class="video"
        autoplay
        playsinline
        muted
      />
      <div v-if="!stream.stream.value" class="placeholder">영상 대기 중…</div>

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
  position: absolute;
  inset: 0;
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
