<script setup lang="ts">
/**
 * GogoPing WebRTC fullscreen video — admin QWebEngineView 용 embed 페이지.
 *
 * PyQt5 admin (`app/admin-app/widgets/camera_widget.py`, `CameraStreamView`)
 * 는 현재 binary JPEG WS frame 을 QPainter 로 그리는데, gogoping 의 1080p
 * D435 영상은 WebRTC (control-service 의 /ws/webrtc/signaling, server-side
 * offer flow) 로 전송되도록 Task 11 에서 robot-web 측이 전환되었다.
 *
 * 이 컴포넌트는 robot-web 의 useWebRTCStream composable 을 admin 쪽
 * peer_id='admin-ui' 로 재사용해 영상을 받아 <video> 로 표시한다. PyQt
 * admin 의 camera_card 가 QWebEngineView 로 `?embed=gogoping-video` URL
 * 을 띄우면, CameraStreamView 를 대체하지 않고도 같은 WebRTC 스트림을
 * 운영자에게 보여줄 수 있다.
 *
 * 상태 표시 (우하단 pill) — 연결 상태(idle/connecting/connected/closed)
 * 를 작게 표시. 비디오 자체는 검정 배경 위에서 contain 으로 letterbox.
 */
import { onBeforeUnmount, ref, watch } from 'vue';
import { useWebRTCStream } from '@/gogoping/composables/useWebRTCStream';

const stream = useWebRTCStream('admin-ui');
const videoEl = ref<HTMLVideoElement | null>(null);

watch(
  [stream.stream, videoEl],
  ([s, el]) => {
    if (el && s) {
      el.srcObject = s;
    } else if (el && !s) {
      el.srcObject = null;
    }
  },
  { immediate: true },
);

onBeforeUnmount(() => {
  stream.stop();
});

const statusLabel = ref<Record<string, string>>({
  idle: '대기',
  connecting: '연결 중',
  connected: 'LIVE',
  closed: '끊김',
});

const statusColor = ref<Record<string, string>>({
  idle: '#9ca3af',
  connecting: '#f59e0b',
  connected: '#16a34a',
  closed: '#ef4444',
});
</script>

<template>
  <div class="admin-gogoping-video">
    <video
      ref="videoEl"
      autoplay
      playsinline
      muted
      class="video"
    />
    <div class="status-pill">
      <span
        class="status-pill__dot"
        :style="{ background: statusColor[stream.status.value] ?? '#9ca3af' }"
      />
      <span class="status-pill__label">WebRTC</span>
      <span class="status-pill__value">{{ statusLabel[stream.status.value] ?? stream.status.value }}</span>
    </div>
  </div>
</template>

<style scoped>
.admin-gogoping-video {
  position: fixed;
  inset: 0;
  background: #0b0d12;
  display: flex;
  align-items: center;
  justify-content: center;
}

.video {
  width: 100%;
  height: 100%;
  object-fit: contain;
  background: #000;
}

.status-pill {
  position: absolute;
  right: 16px;
  bottom: 16px;
  z-index: 10;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px 6px 12px;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid rgba(15, 23, 42, 0.15);
  border-radius: 999px;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.18);
  font-family: system-ui, -apple-system, sans-serif;
  font-size: 11px;
  color: #1f2937;
}
.status-pill__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  box-shadow: 0 0 0 3px rgba(15, 23, 42, 0.05);
}
.status-pill__label { color: #6b7280; }
.status-pill__value {
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
</style>
