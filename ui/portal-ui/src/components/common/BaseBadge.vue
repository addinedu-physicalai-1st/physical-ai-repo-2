<script setup lang="ts">
withDefaults(defineProps<{
  variant?: 'neutral' | 'success' | 'warning' | 'danger' | 'info' | 'brand'
  size?: 'sm' | 'md'
}>(), {
  variant: 'neutral',
  size: 'sm',
})
</script>

<template>
  <span :class="['badge', `badge--${variant}`, `badge--${size}`]">
    <slot />
  </span>
</template>

<style scoped>
.badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border-radius: var(--radius-full);
  font-weight: var(--font-weight-medium);
  letter-spacing: 0.01em;
  white-space: nowrap;
}
.badge--sm { font-size: var(--font-size-xs); padding: 2px 8px; }
.badge--md { font-size: var(--font-size-sm); padding: 4px 12px; }

.badge--neutral { background: var(--color-surface-sunken); color: var(--color-text-secondary); }
.badge--success { background: var(--color-status-success-soft); color: var(--color-status-success); }
.badge--warning { background: var(--color-status-warning-soft); color: var(--color-status-warning); }
.badge--danger  { background: var(--color-status-danger-soft);  color: var(--color-status-danger); }
.badge--info    { background: var(--color-status-info-soft);    color: var(--color-status-info); }
.badge--brand   { background: var(--color-brand-primary-soft);  color: var(--color-brand-primary); }
</style>
