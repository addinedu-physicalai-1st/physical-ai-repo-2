import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'node:path'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const controlTarget = env.CONTROL_URL ?? 'http://localhost:8000'
  const streamingTarget = env.STREAMING_URL ?? 'http://localhost:8100'
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
        // D435 depth stream — streaming uvicorn (port 8100), depth_ws_router.
        // 더 구체적인 규칙이 generic /ws 보다 먼저 와야 매칭됨.
        '/ws/depth-stream': { target: streamingTarget, changeOrigin: true, ws: true },
        // Doctor teleop WS — control-service `/ws/doctor/teleop`.
        '/ws': { target: controlTarget, changeOrigin: true, ws: true },
      },
    },
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./vitest.setup.ts'],
    },
  }
})
