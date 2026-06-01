<script setup lang="ts">
/**
 * 등원/하원/율동 배경 화면 — 로봇 팔 3D + D435 depth cloud (VIEW-ONLY).
 *
 * DepthViewer (뎁스카메라 뷰) 와 달리 hand-tracking·high-five 트리거를 하지 않는다 —
 * 순수 시각화. 로봇이 등원 하이파이브 / 하원 인사 / 율동 하는 모습을 화면으로 보여줄 뿐.
 * 등원 하이파이브 트리거는 HighfiveDetector 가 별도 overlay 로 처리한다.
 *
 * OpenarmViewer 는 /api/eduping/state WS 로 받은 follower joint 값을 실시간 렌더하고,
 * depthStream 을 받아 D435 point cloud 를 합성한다 (DepthViewer 와 동일한 cloud props).
 */
import { onBeforeUnmount } from 'vue';
import OpenarmViewer from './OpenarmViewer.vue';
import { useDepthStream } from './useDepthStream';
import { HIGHFIVE_MAX_Z_M, HIGHFIVE_MIN_Z_M } from './highfiveHandTarget';

// 자체 depth WS 한 개 (생성 시 auto-connect, consumer). unmount 시 정리.
const stream = useDepthStream('eduping');

// ⚠ 핵심: consumer WS 만 열면 프레임이 안 온다 — DepthViewer 처럼 depth SESSION 을
// start 해야 control-service 가 d435_camera + d435_depth_streamer (producer) 를
// 띄우거나(또는 tmux 외부 launch 에 attach) 프레임이 흐른다. 등원/하원/율동 에선
// 이 호출이 없어서 depth 가 안 붙었음 (사용자 보고). start 는 idempotent, stop 은
// 자체 spawn 만 종료 (외부 tmux launch 는 안 건드림) — 안전.
async function startDepthSession(): Promise<void> {
  try {
    const res = await fetch('/api/eduping/depth/session/start', { method: 'POST' });
    if (!res.ok) console.warn('[arm-depth] session/start non-OK:', res.status);
  } catch (e) {
    console.warn('[arm-depth] session/start failed:', e);
  }
}
function stopDepthSession(): void {
  try {
    const blob = new Blob(['{}'], { type: 'application/json' });
    const sent = navigator.sendBeacon?.('/api/eduping/depth/session/stop', blob);
    if (!sent) void fetch('/api/eduping/depth/session/stop', { method: 'POST' });
  } catch (e) {
    console.warn('[arm-depth] session/stop failed:', e);
  }
}

// 세션을 setup 단계에서 즉시 시작 — useDepthStream 은 생성 즉시 connect() 하므로
// onMounted 까지 기다리면 producer(d435_camera+streamer)가 아직 안 떠 첫 subscribe 가
// 빈다. 즉시 POST 로 producer 기동 → WS 재연결 backoff 안에 프레임이 흐른다.
void startDepthSession();
onBeforeUnmount(() => {
  stopDepthSession();
  stream.stop();
});
</script>

<template>
  <div class="arm-depth-screen">
    <OpenarmViewer
      source="follower"
      :show-depth-cloud="true"
      :show-depth-voxels="false"
      :depth-stream="stream"
      :depth-point-size="9.0"
      :depth-stride="2"
      :depth-max-m="2.0"
      :depth-frustum-near-m="HIGHFIVE_MIN_Z_M"
      :depth-frustum-far-m="HIGHFIVE_MAX_Z_M"
      depth-color-mode="silhouette"
      :depth-band-min-m="HIGHFIVE_MIN_Z_M"
      :depth-band-max-m="HIGHFIVE_MAX_Z_M"
      :depth-world-bound-xz="2.0"
      render-lite
    />
  </div>
</template>

<style scoped>
/* 얼굴(EmotionDisplay, 내부 z≤3) 위, overlay(AttendanceCamera z5 · HighfiveDetector
   z30 · DancePlayPopup z60) 아래의 배경 레이어. */
.arm-depth-screen {
  position: absolute;
  inset: 0;
  z-index: 4;
}
</style>
