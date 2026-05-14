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
      // shared/ 디렉터리(repo root) 를 dev server 가 import 할 수 있도록 허용
      fs: {
        allow: [path.resolve(__dirname, '../../')],
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
            // goto_vertex intent 받으면 robot-ui 가 /waypoints/navigate 호출.
            '/waypoints': {
              target: controlTarget,
              changeOrigin: true,
            },
          },
    },
    // Pure 유틸 (wakeMatcher 등) 만 테스트하므로 jsdom 불필요. globals 도 import 로 명시.
    test: {
      environment: 'node',
      include: ['tests/**/*.test.ts'],
    },
  };
});
