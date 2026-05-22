<script setup lang="ts">
/**
 * 등원 모드의 high-five 서브 상태 — D435 depth stream 연결 + MediaPipe Hands +
 * palm 의 3D 위치 산출 + POST /api/eduping/highfive/hand-target.
 *
 * AttendanceCamera 가 어린이의 등원이 확인되면 이 컴포넌트를 mount 하고,
 * 손이 감지·POST 되거나 timeout 시 emit('complete') 로 부모에게 알린다.
 *
 * 시각 출력은 가벼움 — 화면 하단 prompt 한 줄만. 3D 포인트클라우드는
 * DepthViewer (뎁스카메라 뷰 모드) 에서만 그림.
 */
import { onBeforeUnmount, onMounted, ref } from 'vue';
import {
  HIGHFIVE_POST_INTERVAL_MS,
  palmFromFrame,
  postHighfiveHandTarget,
  postReturnHomeSim,
} from './highfiveHandTarget';
import { useDepthStream } from './useDepthStream';
import { useHandTracker } from './useHandTracker';

const props = defineProps<{
  /** 손이 안 보일 때 최대 대기 시간 (ms). 기본 12s. */
  timeoutMs?: number;
  /** POST 후 모션 완료까지 대기 (ms). 기본 4s — highfive_node 의 2.5s 트래젝토리 + 마진. */
  motionMs?: number;
}>();

const emit = defineEmits<{
  /** 손이 감지·POST 되고 모션 시간 만료. */
  complete: [];
  /** 손이 안 나타나서 timeout. */
  timeout: [];
}>();

const stream = useDepthStream('eduping');
const tracker = useHandTracker();

const status = ref<string>('손을 들어주세요 ✋');

/** Detect 매 N frame (15fps → 3fps detection). */
const DETECT_EVERY_N = 5;
let detectCounter = 0;
let lastPostAt = 0;
let posted = false;

let timeoutHandle: ReturnType<typeof setTimeout> | null = null;
let motionHandle: ReturnType<typeof setTimeout> | null = null;

function handleFrame(frame: import('./useDepthStream').DecodedDepthFrame): void {
  // 검출 throttle
  detectCounter = (detectCounter + 1) % DETECT_EVERY_N;
  if (detectCounter === 0) {
    void createImageBitmap(frame.colorBlob).then((bm) => {
      const ok = tracker.detect(bm);
      if (!ok) bm.close();
    }).catch(() => {});
  }

  const hand = tracker.hand.value;
  if (hand === null) {
    if (!posted) status.value = '손을 들어주세요 ✋';
    return;
  }

  const palmResult = palmFromFrame(frame, hand);
  if (!palmResult.ok) {
    if (!posted) {
      status.value = palmResult.reason === 'no_depth'
        ? '손이 안 보여요 — 카메라 앞으로!'
        : `손 ${handMetersFromFrame(frame, hand)?.toFixed(2) ?? '?'}m — 0.3~1.5m 사이로`;
    }
    return;
  }
  const { palm } = palmResult;
  status.value = `손 잡았다 ✋ ${palm.z.toFixed(2)}m`;

  const now = Date.now();
  if (now - lastPostAt < HIGHFIVE_POST_INTERVAL_MS) return;
  lastPostAt = now;

  void postHighfiveHandTarget(palm).then((ok) => {
    if (!ok) {
      console.warn('hand-target POST failed');
      return;
    }
    if (posted) return;
    posted = true;
    if (timeoutHandle) { clearTimeout(timeoutHandle); timeoutHandle = null; }
    motionHandle = setTimeout(() => emit('complete'), props.motionMs ?? 4000);
  }).catch((e) => console.warn('hand-target POST error:', e));
}

function handMetersFromFrame(
  frame: import('./useDepthStream').DecodedDepthFrame,
  hand: import('./useHandTracker').HandPoint,
): number | null {
  const u = Math.round(Math.min(Math.max(hand.u, 0), frame.depthW - 1));
  const v = Math.round(Math.min(Math.max(hand.v, 0), frame.depthH - 1));
  const raw = frame.depth[v * frame.depthW + u];
  return raw > 0 ? raw * frame.depthScale : null;
}

onMounted(() => {
  stream.onFrame(handleFrame);
  timeoutHandle = setTimeout(() => {
    if (!posted) emit('timeout');
  }, props.timeoutMs ?? 12000);
});

onBeforeUnmount(() => {
  if (timeoutHandle) clearTimeout(timeoutHandle);
  if (motionHandle) clearTimeout(motionHandle);
  // 컴포넌트 unmount = 인터랙션 종료 → return-home 트리거 (어떤 종료 경로든 일관성).
  void postReturnHomeSim().catch((e) => console.warn('return-home POST:', e));
  stream.stop();
  void tracker.close();
});
</script>

<template>
  <div class="highfive-overlay">
    <div class="prompt">{{ status }}</div>
  </div>
</template>

<style scoped>
.highfive-overlay {
  position: absolute;
  inset: auto 0 25% 0;
  display: flex;
  justify-content: center;
  pointer-events: none;
  z-index: 30;
}
.prompt {
  padding: 16px 28px;
  border-radius: 999px;
  background: rgba(34, 197, 94, 0.92);
  color: white;
  font-size: 22px;
  font-weight: 800;
  font-family: 'Pretendard', -apple-system, 'Apple SD Gothic Neo', sans-serif;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
  letter-spacing: -0.5px;
  pointer-events: none;
}
</style>
