<script setup lang="ts">
/**
 * DepthOnlyApp — 뎁스 카메라 뷰 standalone 페이지 (URL: /depth.html).
 *
 * 의도:
 *   robot-web 메인 (App.vue + ModeSelector + VoiceController + WakeWord + intent
 *   dispatch + WS broadcaster) 가 같이 돌면 main thread CPU 가 80%+ 잡혀 MediaPipe
 *   Hands 의 onResults latency 가 200-400ms 까지 늘어남. 본 standalone 은 DepthViewer
 *   하나만 마운트 → CPU 여유 ↑ → 하이파이브 트리거 반응성 ↑.
 *
 * 접근:
 *   `npm run dev` 로 띄운 vite 의 https://localhost:5173/depth.html
 *   (메인은 그대로 https://localhost:5173/index.html)
 *
 * 의존성:
 *   - DepthViewer 가 사용하는 모든 composable (useDepthStream, useHandTracker,
 *     OpenarmViewer 의 three.js, useDepthCloudInScene) 그대로 import.
 *   - control-service · streaming server 는 같은 proxy 로 reach.
 */
import DepthViewer from '@/eduping/DepthViewer.vue';
</script>

<template>
  <div class="depth-only-root">
    <DepthViewer />
  </div>
</template>

<style>
html, body, #app {
  margin: 0;
  padding: 0;
  height: 100%;
  background: #f0f4f8;
  font-family: 'Pretendard', -apple-system, 'Helvetica Neue', sans-serif;
}
.depth-only-root {
  position: relative;
  width: 100vw;
  height: 100vh;
  overflow: hidden;
}
</style>
