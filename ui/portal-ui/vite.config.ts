import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'node:path'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const controlTarget = env.CONTROL_URL ?? 'http://localhost:8000'
  const minioTarget = env.MINIO_URL ?? 'http://localhost:9000'

  return {
    plugins: [vue()],
    resolve: {
      alias: { '@': path.resolve(__dirname, 'src') },
    },
    optimizeDeps: {
      include: ['@mediapipe/face_mesh'],
    },
    server: {
      host: true,
      port: 5174,
      proxy: {
        '/api': { target: controlTarget, changeOrigin: true },
        '/photos': { target: minioTarget, changeOrigin: true },
      },
    },
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./vitest.setup.ts'],
    },
  }
})
