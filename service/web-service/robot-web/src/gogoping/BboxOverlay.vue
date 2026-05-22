<script setup lang="ts">
import { computed } from 'vue';
import type { TrackingState } from './composables/useTrackingStateWs';

const props = defineProps<{
  state: TrackingState;
  /** perception 카메라의 native 해상도. 영상이 다른 크기로 렌더되면 viewBox 스케일이 자동. */
  imageWidth?: number;
  imageHeight?: number;
}>();

const viewW = computed(() => props.imageWidth ?? 640);
const viewH = computed(() => props.imageHeight ?? 480);

const visible = computed(() =>
  props.state.matched &&
  props.state.bbox_x1 !== null &&
  props.state.bbox_y1 !== null &&
  props.state.bbox_x2 !== null &&
  props.state.bbox_y2 !== null
);

const bbox = computed(() => ({
  x: props.state.bbox_x1 ?? 0,
  y: props.state.bbox_y1 ?? 0,
  w: (props.state.bbox_x2 ?? 0) - (props.state.bbox_x1 ?? 0),
  h: (props.state.bbox_y2 ?? 0) - (props.state.bbox_y1 ?? 0),
}));

const label = computed(() => {
  const id = props.state.track_id !== null ? `#${props.state.track_id}` : '';
  const sim = props.state.reid_sim !== null ? `${Math.round(props.state.reid_sim * 100)}%` : '';
  return [id, sim].filter(Boolean).join(' ');
});
</script>

<template>
  <svg
    v-if="visible"
    class="bbox-overlay"
    :viewBox="`0 0 ${viewW} ${viewH}`"
    preserveAspectRatio="xMidYMid slice"
    pointer-events="none"
  >
    <rect
      :x="bbox.x" :y="bbox.y" :width="bbox.w" :height="bbox.h"
      fill="none" stroke="#22c55e" stroke-width="3"
    />
    <g v-if="label">
      <rect
        :x="bbox.x" :y="bbox.y - 22" :width="label.length * 11 + 12" height="22"
        fill="#22c55e" opacity="0.9"
      />
      <text
        :x="bbox.x + 6" :y="bbox.y - 6"
        font-family="ui-monospace, monospace" font-size="14" font-weight="700" fill="white"
      >{{ label }}</text>
    </g>
  </svg>
</template>

<style scoped>
.bbox-overlay {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}
</style>
