<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  name?: string
  src?: string | null
  size?: number
}>(), {
  size: 36,
})

const palette = [
  '#E07856', '#E0A03A', '#5BA978', '#5B8DEF', '#9B6BD4', '#D45B8B',
]

function hash(str: string): number {
  let h = 0
  for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) | 0
  return Math.abs(h)
}

const initial = computed(() => (props.name?.trim()[0] ?? '?').toUpperCase())
const bg = computed(() => palette[hash(props.name ?? '') % palette.length])
const fontSize = computed(() => Math.round(props.size * 0.42))
</script>

<template>
  <span
    class="avatar"
    :style="{ width: `${size}px`, height: `${size}px`, fontSize: `${fontSize}px`, background: bg }"
  >
    <img v-if="src" :src="src" :alt="name ?? ''" />
    <span v-else class="avatar__initial">{{ initial }}</span>
  </span>
</template>

<style scoped>
.avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-full);
  color: #fff;
  font-weight: var(--font-weight-semibold);
  overflow: hidden;
  flex-shrink: 0;
}
.avatar img { width: 100%; height: 100%; object-fit: cover; }
.avatar__initial { line-height: 1; }
</style>
