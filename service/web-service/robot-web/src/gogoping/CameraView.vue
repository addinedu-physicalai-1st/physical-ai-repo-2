<script setup lang="ts">
import { inject, onBeforeUnmount, ref } from 'vue';
import { useVideoStream, type StreamStatus } from './composables/useVideoStream';
import { CAMERA_PAN_KEY } from './cameraPanKey';
import { VIDEO_STREAM_KEY } from './videoStreamKey';

const injected = inject(VIDEO_STREAM_KEY, null);
const stream = injected ?? useVideoStream('gogoping');
const cameraPan = inject(CAMERA_PAN_KEY);

function statusClass(s: StreamStatus): string {
  if (s === 'streaming') return 'ok';
  if (s === 'open') return 'warn';
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

onBeforeUnmount(() => { if (!injected) stream.stop(); });
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
    <img v-if="stream.frameUrl.value" :src="stream.frameUrl.value" class="frame" alt="camera" />
    <div v-else class="placeholder">영상 대기 중…</div>
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
  pointer-events: none;   /* 이미지가 드래그 이벤트 가로채는 것 방지 */
  -webkit-user-drag: none;
}
.placeholder {
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
