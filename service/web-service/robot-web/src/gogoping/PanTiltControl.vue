<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, inject } from 'vue';
import { CAMERA_PAN_KEY } from './cameraPanKey';
import { vectorFromOffset, type JoystickConfig } from './composables/panTiltJoystick';

const cp = inject(CAMERA_PAN_KEY);
if (!cp) throw new Error('PanTiltControl: CAMERA_PAN_KEY not provided');

const PAD_RADIUS = 80;
const JOY_CFG: JoystickConfig = { radiusPx: PAD_RADIUS, maxDegPerSec: 60 };
const TICK_MS = 50;
const KEY_STEP_DEG = 5;

const pad = ref<HTMLDivElement | null>(null);
const knob = ref({ x: 0, y: 0 });
const dragging = ref(false);
let timer: ReturnType<typeof setInterval> | null = null;

// pointerdown 위치 — pointerup 시점에 이동량 작으면 tap = 원점복귀로 해석.
const TAP_THRESHOLD_PX = 5;
let downAt: { x: number; y: number } | null = null;

function startDrag(ev: PointerEvent) {
  dragging.value = true;
  downAt = { x: ev.clientX, y: ev.clientY };
  pad.value?.setPointerCapture(ev.pointerId);
  moveDrag(ev);
}
function moveDrag(ev: PointerEvent) {
  if (!dragging.value || !pad.value) return;
  const rect = pad.value.getBoundingClientRect();
  const cx = rect.left + rect.width / 2;
  const cy = rect.top + rect.height / 2;
  const dx = ev.clientX - cx;
  const dy = ev.clientY - cy;
  const r = Math.min(Math.hypot(dx, dy), PAD_RADIUS);
  const ang = Math.atan2(dy, dx);
  knob.value = { x: Math.cos(ang) * r, y: Math.sin(ang) * r };
}
function endDrag(ev: PointerEvent) {
  dragging.value = false;
  pad.value?.releasePointerCapture(ev.pointerId);
  // tap (이동량 < 임계치) = 원점 복귀
  if (downAt) {
    const moved = Math.hypot(ev.clientX - downAt.x, ev.clientY - downAt.y);
    if (moved < TAP_THRESHOLD_PX) cp!.center();
  }
  downAt = null;
  knob.value = { x: 0, y: 0 };
}

function tick() {
  if (knob.value.x === 0 && knob.value.y === 0) return;
  const v = vectorFromOffset(knob.value.x, knob.value.y, JOY_CFG);
  const dt = TICK_MS / 1000;
  cp!.updateSetpoint(v.pan * dt, v.tilt * dt);
}

function isInTextInput(): boolean {
  const el = document.activeElement as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || el.isContentEditable;
}

function onKeyDown(ev: KeyboardEvent) {
  if (ev.repeat && ['c', 'C', ' '].includes(ev.key)) return;
  if (isInTextInput()) return;
  let dp = 0, dt = 0;
  switch (ev.key) {
    case 'a': case 'A': case 'ArrowLeft':  dp = -KEY_STEP_DEG; break;
    case 'd': case 'D': case 'ArrowRight': dp = +KEY_STEP_DEG; break;
    case 'w': case 'W': case 'ArrowUp':    dt = +KEY_STEP_DEG; break;
    case 's': case 'S': case 'ArrowDown':  dt = -KEY_STEP_DEG; break;
    case 'c': case 'C': case ' ':          cp!.center(); ev.preventDefault(); return;
    default: return;
  }
  cp!.updateSetpoint(dp, dt);
  ev.preventDefault();
}

onMounted(() => {
  timer = setInterval(tick, TICK_MS);
  window.addEventListener('keydown', onKeyDown);
});
onBeforeUnmount(() => {
  if (timer) clearInterval(timer);
  window.removeEventListener('keydown', onKeyDown);
});
</script>

<template>
  <div class="pt-control">
    <div
      ref="pad"
      class="pad"
      :style="{ width: `${PAD_RADIUS*2}px`, height: `${PAD_RADIUS*2}px` }"
      @pointerdown="startDrag"
      @pointermove="moveDrag"
      @pointerup="endDrag"
      @pointercancel="endDrag"
    >
      <div
        class="knob"
        :style="{ transform: `translate(${knob.x}px, ${knob.y}px)` }"
      />
      <!-- 중앙 "원점" 라벨 — 시각 표시용 (pointer-events:none).
           실제 동작: pad 위에서 이동 없이 탭 → endDrag 가 center 호출. -->
      <div class="center-btn">원점</div>
    </div>
    <div v-if="cp?.lastError.value" class="toast">{{ cp.lastError.value }}</div>
  </div>
</template>

<style scoped>
.pt-control {
  position: absolute;
  right: 24px;
  bottom: 24px;
  /* ModeSelectorFab .mode-panel (z:20) 가 우측 200px 스트립을 덮어 pointer 가로채는 것 회피 */
  z-index: 25;
  user-select: none;
  touch-action: none;
}
.pad {
  position: relative;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.15);
  border: 2px solid rgba(255, 255, 255, 0.35);
  display: flex;
  align-items: center;
  justify-content: center;
}
.knob {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.85);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.35);
  pointer-events: none;
  transition: transform 60ms linear;
}
.center-btn {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 56px;
  height: 56px;
  border-radius: 50%;
  border: 1px solid rgba(255, 255, 255, 0.6);
  background: rgba(40, 40, 50, 0.55);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;   /* pad 의 pointer 이벤트 가로채지 않음 */
  z-index: 2;
}
.toast {
  position: absolute;
  right: 0;
  top: -36px;
  padding: 6px 10px;
  background: rgba(220, 38, 38, 0.9);
  color: white;
  font-size: 12px;
  border-radius: 4px;
  white-space: nowrap;
}
</style>
