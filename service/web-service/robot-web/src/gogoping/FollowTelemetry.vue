<script setup lang="ts">
import { computed } from 'vue';
import type { TrackingState } from './composables/useTrackingStateWs';

const props = defineProps<{ state: TrackingState }>();

const statusLabel = computed(() => {
  if (!props.state.active) return '대기';
  if (props.state.matched) return '추종 중';
  return '인식 중…';
});

const statusClass = computed(() => {
  if (props.state.matched) return 'ok';
  if (props.state.active) return 'searching';
  return 'idle';
});

const distanceText = computed(() =>
  props.state.distance_m !== null
    ? `${props.state.distance_m.toFixed(2)} m`
    : '—'
);

const angleText = computed(() =>
  props.state.angle_deg !== null
    ? `${props.state.angle_deg.toFixed(1)}°`
    : '—'
);

const trackText = computed(() =>
  props.state.track_id !== null ? `#${props.state.track_id}` : '—'
);

const simText = computed(() =>
  props.state.reid_sim !== null
    ? `${Math.round(props.state.reid_sim * 100)}%`
    : '—'
);
</script>

<template>
  <div class="telemetry">
    <div class="status" :class="statusClass">
      <span class="dot" />
      <span class="label">{{ statusLabel }}</span>
    </div>
    <div class="grid">
      <div class="cell"><div class="k">거리</div><div class="v">{{ distanceText }}</div></div>
      <div class="cell"><div class="k">각도</div><div class="v">{{ angleText }}</div></div>
      <div class="cell"><div class="k">Track</div><div class="v">{{ trackText }}</div></div>
      <div class="cell"><div class="k">유사도</div><div class="v">{{ simText }}</div></div>
    </div>
  </div>
</template>

<style scoped>
.telemetry {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 10px 14px;
  background: rgba(15, 20, 18, 0.78);
  color: white;
  border-radius: 12px;
  backdrop-filter: blur(6px);
}
.status {
  display: flex;
  align-items: center;
  gap: 8px;
}
.status .dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #777;
}
.status.ok .dot { background: #22c55e; }
.status.searching .dot { background: #facc15; }
.status .label {
  font-weight: 700;
  font-size: 14px;
  letter-spacing: -0.2px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 6px 14px;
}
.cell .k {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.6);
  letter-spacing: 0.2px;
}
.cell .v {
  font-family: ui-monospace, monospace;
  font-size: 15px;
  font-weight: 700;
}
@media (max-width: 768px) {
  .grid { grid-template-columns: repeat(4, 1fr); gap: 4px 10px; }
  .cell .k { font-size: 10px; }
  .cell .v { font-size: 13px; }
}
</style>
