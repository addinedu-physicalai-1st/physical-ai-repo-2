<script setup lang="ts">
/**
 * EduPing 뎁스카메라 뷰 — OpenarmViewer scene 위에 D435 라이브 포인트 클라우드 + frustum
 * + HUD (status / fps / nearest / hand toggle) 오버레이.
 *
 * 자체 three.js scene 은 더 이상 없음 — 클라우드 렌더링은 OpenarmViewer 의
 * showDepthCloud 가 처리 (useDepthCloudInScene 통해 d435_depth_optical_frame 자식으로
 * Points attach). 본 컴포넌트는 hand tracker + HUD 만 책임.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import OpenarmViewer from './OpenarmViewer.vue';
import {
  HIGHFIVE_PALM_MOVE_M,
  HIGHFIVE_PALM_STABLE_EPS_M,
  HIGHFIVE_PALM_STABLE_FRAMES,
  HIGHFIVE_POST_INTERVAL_MS,
  palmDistanceM,
  palmFromFrame,
  type Palm3D,
  postHighfiveHandTarget,
  postReturnHomeSim,
} from './highfiveHandTarget';
import { useDepthStream, type DecodedDepthFrame } from './useDepthStream';
import { useHandTracker } from './useHandTracker';
import type { HandBbox } from './useDepthCloudInScene';
import { useProximityOverride } from '@/composables/useProximityOverride';

const stream = useDepthStream('eduping');
useProximityOverride();  // 뎁스카메라 뷰(하이파이브) — 아이가 팔에 손 대는 모드라 근접 정지 우회
const depthStatusLabel = computed(() => {
  switch (stream.status.value) {
    case 'streaming':
      return '뎁스 연결됨';
    case 'open':
      return waitingProducer.value ? '카메라 스트림 대기' : 'WS 연결 (프레임 대기)';
    case 'connecting':
      return '뎁스 연결 중…';
    default:
      return '뎁스 끊김';
  }
});
const waitingProducer = computed(() => {
  if (stream.status.value !== 'open') return false;
  const last = stream.lastFrameAtMs.value;
  return last === 0 || Date.now() - last > 3000;
});

const depthHint = computed(() => {
  if (stream.status.value === 'streaming') return '';
  if (stream.status.value === 'open') {
    if (waitingProducer.value) {
      return 'WS OK — D435 producer 없음: ros2 launch eduarm d435_depth.launch.py (또는 d435-streamer.service)';
    }
    return 'D435 streamer·USB 확인 (journalctl -u d435-streamer)';
  }
  return 'run_server.sh (streaming :8100) 확인 후 재시도';
});
const fps = ref<number>(0);
const nearestMeters = ref<number | null>(null);
const handMeters = ref<number | null>(null);
const handEnabled = ref<boolean>(false);
const handLoading = ref<boolean>(false);
const handBbox = ref<HandBbox | null>(null);
/** high-five arm command status (sim / real via control-service → highfive_node). */
const armStatus = ref<string>('');

let lastPostAt = 0;
let motionBusyUntil = 0;
let stableFrames = 0;
let lastSamplePalm: Palm3D | null = null;
let lastPostedPalm: Palm3D | null = null;

/** Toggle ON 시 빠른 추적용 — 15fps 입력에서 매 frame 검출 (~15Hz). OFF 시는 미사용. */
const DETECT_EVERY_N = 2;
/** bbox 패딩 (image 픽셀 비율) — 손 윤곽 + 손목 약간 더 포함. */
const HAND_BBOX_PAD = 0.08;
let detectCounter = 0;
let firstResultReceived = false;
let tracker: ReturnType<typeof useHandTracker> | null = null;

let frameCount = 0;
let fpsTimer: ReturnType<typeof setInterval> | null = null;
let lastFpsCheck = 0;

function handleFrame(frame: DecodedDepthFrame): void {
  frameCount++;
  nearestMeters.value = frame.depthMinMm > 0 ? frame.depthMinMm / 1000 : null;

  // 손 검출 — N frame 마다 1번 (toggle ON 일 때만).
  if (handEnabled.value && tracker) {
    detectCounter = (detectCounter + 1) % DETECT_EVERY_N;
    if (detectCounter === 0) {
      const t = tracker;
      void createImageBitmap(frame.colorBlob).then((bm) => {
        const ok = t.detect(bm);
        if (!ok) bm.close();
      }).catch((e) => console.warn('hand decode:', e));
    }
    // MediaPipe 가 첫 onResults 를 한 번 부르면 트래커 자체는 살아있는 것 — 손이
    // 실제로 잡혔는지 (hand.value !== null) 와 무관하게 로딩 표시를 끈다.
    // 이전 로직은 손이 안 보이면 'loading…' 이 영원히 안 풀려 사용자가 혼란.
    if (!firstResultReceived && tracker.ready.value) {
      firstResultReceived = true;
      handLoading.value = false;
    }
    // 손 3D 거리 + bbox (cloud 필터링용)
    const h = tracker.hand.value;
    if (h !== null) {
      const u = Math.round(Math.min(Math.max(h.u, 0), frame.depthW - 1));
      const v = Math.round(Math.min(Math.max(h.v, 0), frame.depthH - 1));
      const raw = frame.depth[v * frame.depthW + u];
      handMeters.value = raw > 0 ? raw * frame.depthScale : null;
      // 21 landmark 중 min/max 픽셀 + 패딩으로 bbox.
      let uMin = Infinity, uMax = -Infinity, vMin = Infinity, vMax = -Infinity;
      for (const lm of h.landmarks) {
        if (lm.u < uMin) uMin = lm.u;
        if (lm.u > uMax) uMax = lm.u;
        if (lm.v < vMin) vMin = lm.v;
        if (lm.v > vMax) vMax = lm.v;
      }
      const padU = (uMax - uMin) * HAND_BBOX_PAD + 6;
      const padV = (vMax - vMin) * HAND_BBOX_PAD + 6;
      handBbox.value = {
        uMin: Math.max(0, uMin - padU),
        uMax: Math.min(frame.depthW - 1, uMax + padU),
        vMin: Math.max(0, vMin - padV),
        vMax: Math.min(frame.depthH - 1, vMax + padV),
      };
    } else {
      handMeters.value = null;
      handBbox.value = null;
    }

    // 손 ON → palm 3D 를 highfive_node 로 전달 (sim / 실물 공통).
    tryPostHighfive(frame);
  } else if (!handEnabled.value) {
    handMeters.value = null;
    handBbox.value = null;
    armStatus.value = '';
  }
}

function tryPostHighfive(frame: DecodedDepthFrame): void {
  if (!tracker) return;
  const h = tracker.hand.value;
  if (h === null) {
    armStatus.value = '팔: 손 찾는 중…';
    return;
  }
  const palmResult = palmFromFrame(frame, h);
  if (!palmResult.ok) {
    stableFrames = 0;
    lastSamplePalm = null;
    if (palmResult.reason === 'no_depth') {
      armStatus.value = '팔: 손 depth 없음';
    } else {
      armStatus.value = `팔: ${handMeters.value?.toFixed(2) ?? '?'}m — 0.3~1.5m`;
    }
    return;
  }
  const palm = palmResult.palm;
  if (lastSamplePalm !== null
    && palmDistanceM(palm, lastSamplePalm) < HIGHFIVE_PALM_STABLE_EPS_M) {
    stableFrames += 1;
  } else {
    stableFrames = 1;
  }
  lastSamplePalm = palm;

  const now = Date.now();
  if (now < motionBusyUntil) {
    armStatus.value = '팔: 도달 중…';
    return;
  }
  if (stableFrames < HIGHFIVE_PALM_STABLE_FRAMES) {
    armStatus.value = `팔: 손 고정 중 (${stableFrames}/${HIGHFIVE_PALM_STABLE_FRAMES})`;
    return;
  }
  if (lastPostedPalm !== null && palmDistanceM(palm, lastPostedPalm) < HIGHFIVE_PALM_MOVE_M) {
    armStatus.value = `팔: 유지 ✋ ${palm.z.toFixed(2)}m`;
    return;
  }
  if (now - lastPostAt < HIGHFIVE_POST_INTERVAL_MS) return;
  lastPostAt = now;
  armStatus.value = '팔: 보내는 중…';
  void postHighfiveHandTarget(palm).then((ok) => {
    if (!ok) {
      armStatus.value = '팔: POST 실패 (서버/ROS?)';
      return;
    }
    lastPostedPalm = palm;
    motionBusyUntil = Date.now() + HIGHFIVE_POST_INTERVAL_MS;
    armStatus.value = `팔: 도달 중 ✋ ${palm.z.toFixed(2)}m`;
  }).catch(() => {
    armStatus.value = '팔: POST 오류';
  });
}

function toggleHand(): void {
  handEnabled.value = !handEnabled.value;
  if (handEnabled.value) {
    if (tracker === null) tracker = useHandTracker();
    detectCounter = DETECT_EVERY_N - 1;   // 다음 frame 즉시 detect
    handLoading.value = !firstResultReceived;
    stableFrames = 0;
    lastSamplePalm = null;
    lastPostedPalm = null;
    motionBusyUntil = 0;
  } else {
    handMeters.value = null;
    handBbox.value = null;
    handLoading.value = false;
    armStatus.value = '';
    stableFrames = 0;
    lastSamplePalm = null;
    lastPostedPalm = null;
    motionBusyUntil = 0;
    void postReturnHomeSim();
  }
}

onMounted(() => {
  stream.onFrame(handleFrame);
  lastFpsCheck = performance.now();
  fpsTimer = setInterval(() => {
    const now = performance.now();
    const elapsed = (now - lastFpsCheck) / 1000;
    fps.value = Math.round(frameCount / elapsed);
    frameCount = 0;
    lastFpsCheck = now;
  }, 1000);
});

onBeforeUnmount(() => {
  if (fpsTimer) clearInterval(fpsTimer);
  stream.stop();
  if (handEnabled.value) void postReturnHomeSim();
  if (tracker) void tracker.close();
});
</script>

<template>
  <div class="depth-viewer">
    <OpenarmViewer
      source="follower"
      :show-depth-cloud="true"
      :depth-stream="stream"
      :depth-point-size="2.0"
      :depth-cloud-scale="0.5"
      :depth-max-m="1"
      depth-color-mode="depth"
      :hand-bbox="handBbox"
      render-lite
    />
    <div class="hud">
      <span class="status" :data-status="stream.status.value" :title="depthHint">
        {{ depthStatusLabel }}
      </span>
      <span v-if="fps > 0" class="fps">{{ fps }} fps</span>
      <span v-if="handMeters !== null" class="hand">
        손 {{ handMeters.toFixed(2) }} m
      </span>
      <span v-else-if="nearestMeters !== null" class="nearest">
        최근접 {{ nearestMeters.toFixed(2) }} m
      </span>
      <span v-if="armStatus" class="arm">{{ armStatus }}</span>
      <button class="toggle" :data-on="handEnabled" @click="toggleHand">
        ✋ {{ handEnabled ? (handLoading ? 'loading…' : '하이파이브') : 'OFF' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.depth-viewer {
  position: absolute;
  inset: 0;
}
.hud {
  position: absolute;
  top: calc(env(safe-area-inset-top, 0px) + 12px);
  right: 16px;
  display: flex;
  gap: 8px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.85);
  pointer-events: none;
  z-index: 50;
}
.status,
.fps,
.nearest,
.hand {
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.55);
}
.status[data-status='streaming'] { background: rgba(34, 197, 94, 0.75); }
.status[data-status='connecting'] { background: rgba(234, 179, 8, 0.75); }
.status[data-status='closed'] { background: rgba(220, 38, 38, 0.75); }
.nearest {
  background: rgba(59, 130, 246, 0.75);
  font-weight: 600;
}
.hand {
  background: rgba(34, 197, 94, 0.85);
  font-weight: 700;
}
.arm {
  background: rgba(168, 85, 247, 0.85);
  font-weight: 600;
  max-width: 42vw;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.toggle {
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.25);
  background: rgba(0, 0, 0, 0.55);
  color: rgba(255, 255, 255, 0.85);
  font-family: inherit;
  font-size: 12px;
  cursor: pointer;
  pointer-events: auto;
  font-weight: 600;
}
.toggle[data-on='true'] {
  background: rgba(34, 197, 94, 0.85);
  color: white;
  border-color: rgba(34, 197, 94, 0.95);
}
</style>
