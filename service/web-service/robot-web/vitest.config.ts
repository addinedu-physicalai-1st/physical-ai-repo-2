import path from 'node:path';
import { defineConfig } from 'vitest/config';
import vue from '@vitejs/plugin-vue';

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  test: {
    environment: 'jsdom',
    include: [
      'src/**/__tests__/**/*.spec.ts',
      'src/**/*.spec.ts',
      'tests/**/*.test.ts',
      '__tests__/**/*.spec.ts',
    ],
    globals: true,
  },
});
