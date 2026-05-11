/// <reference types="vitest" />
import { defineConfig, loadEnv } from 'vite';
import vue from '@vitejs/plugin-vue';
import path from 'node:path';
import { intentMockPlugin } from './mock/intentMockPlugin';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  // /api/* 는 Control Service 로. Control 이 AI Hub / DB / ROS2 분기.
  const controlTarget = env.CONTROL_URL ?? 'http://localhost:8000';
  // VITE_USE_MOCK=true 면 Vite middleware 가 mock 으로 응답 (Control 안 띄울 때)
  const useMock = env.VITE_USE_MOCK === 'true';

  return {
    plugins: [vue(), ...(useMock ? [intentMockPlugin()] : [])],
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
