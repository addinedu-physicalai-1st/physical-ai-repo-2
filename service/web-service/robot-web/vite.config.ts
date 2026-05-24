/// <reference types="vitest" />
import { defineConfig, loadEnv } from 'vite';
import vue from '@vitejs/plugin-vue';
import mkcert from 'vite-plugin-mkcert';
import path from 'node:path';
import { intentMockPlugin } from './mock/intentMockPlugin';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  // /api/* 는 Control Service 로. Control 이 AI Hub / DB / ROS2 분기.
  const controlTarget = env.CONTROL_URL ?? 'http://localhost:8000';
  const streamingTarget = env.STREAMING_URL ?? 'http://localhost:8100';
  // VITE_USE_MOCK=true 면 Vite middleware 가 mock 으로 응답 (Control 안 띄울 때)
  const useMock = env.VITE_USE_MOCK === 'true';
  // 기본은 HTTPS (vite-plugin-mkcert) — kiosk·데스크톱.
  // 휴대전화에서 mkcert root 설치가 번거로워 plain HTTP 로 띄우고 싶을 때 VITE_HTTPS=false.
  // 단, mobile 브라우저는 비-localhost HTTP origin 에서 mic 거부 — chrome://flags 의
  // "unsafely-treat-insecure-origin-as-secure" 에 LAN URL 을 등록해야 한다.
  // process.env 우선 (shell env: `VITE_HTTPS=false npm run dev`), 없으면 .env 파일 (loadEnv).
  const useHttps = (process.env.VITE_HTTPS ?? env.VITE_HTTPS) !== 'false';

  return {
    plugins: [vue(), ...(useHttps ? [mkcert()] : []), ...(useMock ? [intentMockPlugin()] : [])],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, 'src'),
      },
    },
    server: {
      host: true,
      port: 5173,
      // onnxruntime-web 의 WASM multi-thread (SharedArrayBuffer) 활성. wake word
      // embedding 추론이 main thread 의 80% 이상 — single-thread 로는 step 250-600ms.
      headers: {
        'Cross-Origin-Opener-Policy': 'same-origin',
        'Cross-Origin-Embedder-Policy': 'require-corp',
      },
      // shared/ 디렉터리(repo root) 를 dev server 가 import 할 수 있도록 허용
      fs: {
        allow: [path.resolve(__dirname, '../../../')],
      },
      proxy: useMock
        ? undefined
        : {
            '/api': {
              target: controlTarget,
              changeOrigin: true,
              // ws: true → /api/...  WebSocket upgrade 도 Control Server 로 forward
              // (vision 스트리밍 추론 등). HTTP / WS 같은 prefix 공유.
              ws: true,
            },
            // graph routing — Control 의 waypoints router (prefix /waypoints).
            // goto_vertex intent 받으면 robot-web 가 /waypoints/navigate 호출.
            '/waypoints': {
              target: controlTarget,
              changeOrigin: true,
            },
            // GogoPing 수동 모드 — pan/tilt REST + state WS (control_service.main, port 8000)
            '/camera_pan': {
              target: controlTarget,
              changeOrigin: true,
              ws: true,
            },
            // GogoPing BT snapshot WS — control-service 가 ROS /gogoping/state fan-out
            '/ws/robot-state': {
              target: controlTarget,
              changeOrigin: true,
              ws: true,
            },
            // GogoPing 영상 stream (control_service.streaming.app, port 8100, 별도 uvicorn)
            '/ws/video-stream': {
              target: streamingTarget,
              changeOrigin: true,
              ws: true,
            },
            // EduPing D435 depth stream — 동일 streaming uvicorn (port 8100) 의
            // depth WS router. 4b98dc6 (D435 뎁스카메라 스트리밍 + 하이파이브 뷰 탭
            // 추가) 가 클라/서버 코드는 추가했지만 이 proxy rule 과 streaming/app.py
            // 의 include_router 가 빠져있어 브라우저 → 5173 → 8100 hop 이 닿지 않았다.
            '/ws/depth-stream': {
              target: streamingTarget,
              changeOrigin: true,
              ws: true,
            },
          },
    },
    test: {
      // jsdom — WebSocket / Blob / URL.createObjectURL / DOM 이벤트가 필요한 composable 테스트.
      environment: 'jsdom',
      include: ['tests/**/*.test.ts'],
    },
  };
});
