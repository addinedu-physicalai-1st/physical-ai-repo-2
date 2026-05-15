<script setup lang="ts">
withDefaults(defineProps<{
  width?: string | number
  height?: string | number
  radius?: string
}>(), {
  width: '100%',
  height: '16px',
  radius: 'var(--radius-sm)',
})

function toCss(v: string | number): string {
  return typeof v === 'number' ? `${v}px` : v
}
</script>

<template>
  <span
    class="skeleton"
    :style="{ width: toCss(width), height: toCss(height), borderRadius: radius }"
  />
</template>

<style scoped>
.skeleton {
  display: block;
  background: linear-gradient(
    90deg,
    var(--color-surface-sunken) 0%,
    var(--color-border-subtle) 50%,
    var(--color-surface-sunken) 100%
  );
  background-size: 200% 100%;
  animation: skeleton-shimmer 1.4s ease-in-out infinite;
}
@keyframes skeleton-shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
</style>
