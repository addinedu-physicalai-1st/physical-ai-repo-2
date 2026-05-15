<script setup lang="ts">
import { ref } from 'vue'
import type { Photo } from '@/types'
import Icon from '@/components/common/Icon.vue'

defineProps<{ photos: Photo[] }>()

const lightbox = ref<Photo | null>(null)

function fmtDateTime(iso: string): string {
  const d = new Date(iso)
  const date = `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, '0')}.${String(d.getDate()).padStart(2, '0')}`
  const time = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  return `${date} ${time}`
}
</script>

<template>
  <div class="grid">
    <button v-for="p in photos" :key="p.id" class="thumb" @click="lightbox = p">
      <img :src="p.url" alt="" loading="lazy" />
    </button>
  </div>

  <div v-if="lightbox" class="lightbox" @click.self="lightbox = null">
    <div class="lightbox__content">
      <img :src="lightbox.url" />
      <div class="lightbox__meta">
        <div><span class="meta-label">촬영시각</span> {{ fmtDateTime(lightbox.taken_at) }}</div>
        <div v-if="lightbox.mode"><span class="meta-label">모드</span> {{ lightbox.mode }}</div>
        <div v-if="lightbox.emotion"><span class="meta-label">감정</span> {{ lightbox.emotion }}</div>
      </div>
    </div>
    <button class="lightbox__close" aria-label="닫기" @click="lightbox = null">
      <Icon name="x" :size="20" />
    </button>
  </div>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: var(--space-3);
}
.thumb {
  padding: 0;
  border: 1px solid var(--color-border-subtle);
  background: var(--color-surface-sunken);
  cursor: pointer;
  aspect-ratio: 1;
  overflow: hidden;
  border-radius: var(--radius-lg);
  transition: transform var(--motion-base) var(--motion-ease),
              box-shadow var(--motion-base) var(--motion-ease),
              border-color var(--motion-base) var(--motion-ease);
}
.thumb:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
  border-color: var(--color-border-strong);
}
.thumb img { width: 100%; height: 100%; object-fit: cover; transition: transform var(--motion-slow) var(--motion-ease); }
.thumb:hover img { transform: scale(1.04); }

.lightbox {
  position: fixed; inset: 0; z-index: 1000;
  background: rgba(15, 18, 22, 0.86);
  backdrop-filter: blur(4px);
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  padding: var(--space-6);
}
.lightbox__content { display: flex; flex-direction: column; align-items: center; gap: var(--space-3); }
.lightbox__content img { max-width: 90vw; max-height: 70vh; border-radius: var(--radius-lg); box-shadow: var(--shadow-lg); }
.lightbox__meta {
  display: flex; gap: var(--space-5);
  background: rgba(255,255,255,0.92);
  border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-4);
  font-size: var(--font-size-sm);
  color: var(--color-text-primary);
}
.meta-label { color: var(--color-text-muted); margin-right: 4px; font-size: var(--font-size-xs); }

.lightbox__close {
  position: absolute; top: var(--space-5); right: var(--space-5);
  width: 40px; height: 40px;
  background: var(--color-surface-raised);
  border: none;
  border-radius: var(--radius-full);
  color: var(--color-text-primary);
  display: inline-flex; align-items: center; justify-content: center;
  cursor: pointer;
}
</style>
