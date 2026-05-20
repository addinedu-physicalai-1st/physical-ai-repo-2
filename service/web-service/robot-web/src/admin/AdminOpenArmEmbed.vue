<script setup lang="ts">
/**
 * Fullscreen OpenArm viewer for the PyQt admin app's QWebEngineView.
 *
 * Standalone path — joint state is pushed directly from the admin app (rclpy
 * subscriber on /joint_states, marshalled across the Qt/JS bridge) into this
 * page via `window.setEdupingJointState(snap)`. The viewer renders from that
 * `externalSnapshot`; the control-service `/api/eduping/state` WS is NOT used
 * here, so this works whenever the leader bringup
 * (`scripts/device-eduping-leader.sh`) is publishing on the same ROS_DOMAIN_ID.
 *
 * Highlight protocol — also pushed from PyQt on cursor hover:
 *   window.highlightJoint('openarm_left_joint1')
 *   window.clearJointHighlight()
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import OpenarmViewer from '@/eduping/OpenarmViewer.vue';
import type { JointSnapshot as StreamJointSnapshot } from '@/eduping/useDanceStream';

const highlightedJoint = ref<string | null>(null);
const externalSnap = ref<StreamJointSnapshot | null>(null);
const lastSnapMs = ref<number | null>(null);
const nowMs = ref(Date.now());
// Joint limits pushed from PyQt admin app (mirrors the slider state). When
// present, incoming leader positions are clipped to [min, max] before being
// rendered — so if the leader moves into a self-collision-unsafe range, the
// displayed arm freezes at the limit instead of crashing through itself.
let _jointLimits: Record<string, { min: number; max: number }> = {};

function highlightJoint(name: unknown): void {
  if (typeof name === 'string' && name.length > 0) {
    highlightedJoint.value = name;
  } else {
    highlightedJoint.value = null;
  }
}

function clearJointHighlight(): void {
  highlightedJoint.value = null;
}

interface IncomingJointState {
  joint_names?: unknown;
  positions?: unknown;
  velocities?: unknown;
}

function setEdupingJointState(snap: unknown): void {
  // PyQt sends JSON like { joint_names: string[], positions: number[],
  // velocities?: number[], stamp_sec?, stamp_nanosec? }. Convert to the
  // StreamJointSnapshot shape OpenarmViewer expects (jointNames, positions, tMs).
  if (!snap || typeof snap !== 'object') return;
  const s = snap as IncomingJointState;
  const names = Array.isArray(s.joint_names)
    ? (s.joint_names.filter((v): v is string => typeof v === 'string') as string[])
    : null;
  const positions = Array.isArray(s.positions)
    ? (s.positions.filter((v): v is number => typeof v === 'number') as number[])
    : null;
  if (!names || !positions || names.length !== positions.length || names.length === 0) {
    return;
  }
  // Clip each position to the configured joint limit (if any) — visual self-
  // collision prevention. If the leader moves past the configured safe range,
  // the displayed arm stops at the limit.
  const clipped = new Float32Array(positions.length);
  for (let i = 0; i < positions.length; i++) {
    const lim = _jointLimits[names[i]];
    const v = positions[i];
    if (lim) {
      clipped[i] = v < lim.min ? lim.min : v > lim.max ? lim.max : v;
    } else {
      clipped[i] = v;
    }
  }
  externalSnap.value = {
    jointNames: names,
    positions: clipped,
    tMs: Date.now(),
  };
  lastSnapMs.value = Date.now();
}

function setEdupingJointLimits(limits: unknown): void {
  if (!limits || typeof limits !== 'object') {
    _jointLimits = {};
    return;
  }
  const out: Record<string, { min: number; max: number }> = {};
  for (const [name, row] of Object.entries(limits as Record<string, unknown>)) {
    if (!row || typeof row !== 'object') continue;
    const r = row as { min?: unknown; max?: unknown };
    const mn = typeof r.min === 'number' ? r.min : null;
    const mx = typeof r.max === 'number' ? r.max : null;
    if (mn === null || mx === null) continue;
    out[name] = mn <= mx ? { min: mn, max: mx } : { min: mx, max: mn };
  }
  _jointLimits = out;
}

declare global {
  // eslint-disable-next-line no-var
  var highlightJoint: ((name: string | null) => void) | undefined;
  // eslint-disable-next-line no-var
  var clearJointHighlight: (() => void) | undefined;
  // eslint-disable-next-line no-var
  var setEdupingJointState: ((snap: unknown) => void) | undefined;
  // eslint-disable-next-line no-var
  var setEdupingJointLimits: ((limits: unknown) => void) | undefined;
}

const sourceText = computed(() => {
  if (lastSnapMs.value === null) return 'waiting for leader bringup';
  const ageS = (nowMs.value - lastSnapMs.value) / 1000;
  return `live (${ageS.toFixed(1)} s ago)`;
});
const sourceColor = computed(() => (lastSnapMs.value !== null ? '#16a34a' : '#9ca3af'));
const dismissed = ref(false);

let tickTimer: number | null = null;

onMounted(() => {
  window.highlightJoint = highlightJoint;
  window.clearJointHighlight = clearJointHighlight;
  window.setEdupingJointState = setEdupingJointState;
  window.setEdupingJointLimits = setEdupingJointLimits;
  tickTimer = window.setInterval(() => {
    nowMs.value = Date.now();
  }, 500);
});
onBeforeUnmount(() => {
  if (window.highlightJoint === highlightJoint) window.highlightJoint = undefined;
  if (window.clearJointHighlight === clearJointHighlight) {
    window.clearJointHighlight = undefined;
  }
  if (window.setEdupingJointState === setEdupingJointState) {
    window.setEdupingJointState = undefined;
  }
  if (window.setEdupingJointLimits === setEdupingJointLimits) {
    window.setEdupingJointLimits = undefined;
  }
  if (tickTimer !== null) {
    window.clearInterval(tickTimer);
    tickTimer = null;
  }
});
</script>

<template>
  <div class="admin-openarm-embed">
    <OpenarmViewer
      source="leader"
      :external-snapshot="externalSnap"
      :highlighted-joint="highlightedJoint"
    />

    <!-- Status pill — bottom-right, compact. Shows joint-state source. Click × to hide. -->
    <div v-if="!dismissed" class="status-pill">
      <span
        class="status-pill__dot"
        :style="{ background: sourceColor }"
      />
      <span class="status-pill__label">joint state</span>
      <span class="status-pill__value">{{ sourceText }}</span>
      <button
        type="button"
        class="status-pill__close"
        aria-label="hide"
        @click="dismissed = true"
      >×</button>
    </div>
  </div>
</template>

<style scoped>
.admin-openarm-embed {
  position: fixed;
  inset: 0;
  background: #eaf3fa;
}
.admin-openarm-embed :deep(.openarm-viewer-wrap) {
  width: 100%;
  height: 100%;
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
.status-pill__close {
  margin-left: 4px;
  border: none;
  background: transparent;
  font-size: 14px;
  font-weight: 700;
  color: #6b7280;
  cursor: pointer;
  padding: 0 2px;
  line-height: 1;
}
.status-pill__close:hover { color: #0f172a; }
</style>
