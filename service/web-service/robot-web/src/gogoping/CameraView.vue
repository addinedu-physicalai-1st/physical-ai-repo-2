<script setup lang="ts">
import { inject, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { forceReconnectWebRTCStream, useWebRTCStream } from './composables/useWebRTCStream';
import { CAMERA_PAN_KEY } from './cameraPanKey';
import { VIDEO_STREAM_KEY, type VideoStreamStatus } from './videoStreamKey';

// App.vue 가 provide 한 공유 인스턴스가 있으면 그걸 쓰고, 없으면 (예: 테스트 / 단독 사용)
// 자체 WebRTC 핸들을 만든다. 자체 생성한 경우만 unmount 때 stop.
const injected = inject(VIDEO_STREAM_KEY, null);
const ownHandle = injected ? null : useWebRTCStream('robot-web');
const stream = injected ?? { stream: ownHandle!.stream, status: ownHandle!.status };
const cameraPan = inject(CAMERA_PAN_KEY);

const videoEl = ref<HTMLVideoElement | null>(null);
defineExpose({ getVideoEl: (): HTMLVideoElement | null => videoEl.value });

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
// stream 이 null 이면 watch immediate 가 ontrack 시 처리하므로 여기선 return.
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

function statusClass(s: VideoStreamStatus): string {
  if (s === 'connected') return 'ok';
  if (s === 'connecting') return 'warn';
  return 'err';
}

// 영상 드래그 = 직접 팬틸트 조작. 1 px ≈ DRAG_GAIN_DEG 도 회전.
// 자연스러운 방향: 우드래그 → 카메라 우측 팬, 위드래그 → 위 틸트.
const DRAG_GAIN_DEG = 0.15;
const dragView = ref<HTMLDivElement | null>(null);
const dragLast = ref<{ x: number; y: number } | null>(null);

function viewPointerDown(ev: PointerEvent) {
  if (!cameraPan) return;
  dragLast.value = { x: ev.clientX, y: ev.clientY };
  dragView.value?.setPointerCapture(ev.pointerId);
}
function viewPointerMove(ev: PointerEvent) {
  if (!cameraPan || !dragLast.value) return;
  const dx = ev.clientX - dragLast.value.x;
  const dy = ev.clientY - dragLast.value.y;
  dragLast.value = { x: ev.clientX, y: ev.clientY };
  // dx>0 (우) → pan +,  dy<0 (위로 드래그) → tilt +
  cameraPan.updateSetpoint(dx * DRAG_GAIN_DEG, -dy * DRAG_GAIN_DEG);
}
function viewPointerUp(ev: PointerEvent) {
  dragLast.value = null;
  dragView.value?.releasePointerCapture(ev.pointerId);
}

onBeforeUnmount(() => { ownHandle?.stop(); });
</script>

<template>
  <div
    ref="dragView"
    class="camera-view"
    @pointerdown="viewPointerDown"
    @pointermove="viewPointerMove"
    @pointerup="viewPointerUp"
    @pointercancel="viewPointerUp"
  >
    <video
      ref="videoEl"
      class="frame"
      autoplay
      playsinline
      muted
    />
    <div v-if="!stream.stream.value" class="placeholder">영상 대기 중…</div>
    <div class="status" :class="statusClass(stream.status.value)">●</div>
    <div v-if="cameraPan" class="angles">
      pan {{ Math.round(cameraPan.setpoint.value.pan) }}° ·
      tilt {{ Math.round(cameraPan.setpoint.value.tilt) }}°
    </div>
  </div>
</template>

<style scoped>
.camera-view {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #000;
  z-index: 5;
  /* 드래그로 팬틸트 조작 — 브라우저 기본 스크롤/제스처 차단 */
  touch-action: none;
  cursor: grab;
  user-select: none;
}
.camera-view:active { cursor: grabbing; }
.frame {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  pointer-events: none;   /* 비디오가 드래그 이벤트 가로채는 것 방지 */
  -webkit-user-drag: none;
}
.placeholder {
  position: absolute;
  color: #aaa;
  font-size: 18px;
}
.status {
  position: absolute;
  top: 12px;
  left: 12px;
  font-size: 24px;
}
.status.ok   { color: #22c55e; }
.status.warn { color: #eab308; }
.status.err  { color: #ef4444; }
.angles {
  position: absolute;
  top: 12px;
  right: 16px;
  color: #fff;
  font-weight: 700;
  font-size: 14px;
  text-shadow: 0 1px 2px rgba(0,0,0,0.6);
}
</style>
