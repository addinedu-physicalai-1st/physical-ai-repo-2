<script setup lang="ts">
import Icon from './Icon.vue'

withDefaults(defineProps<{
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  size?: 'sm' | 'md' | 'lg'
  type?: 'button' | 'submit' | 'reset'
  disabled?: boolean
  loading?: boolean
  iconStart?: string
  iconEnd?: string
  block?: boolean
}>(), {
  variant: 'primary',
  size: 'md',
  type: 'button',
  disabled: false,
  loading: false,
  block: false,
})
</script>

<template>
  <button
    :type="type"
    :disabled="disabled || loading"
    :class="['btn', `btn--${variant}`, `btn--${size}`, { 'btn--block': block, 'btn--loading': loading }]"
  >
    <Icon v-if="loading" name="loader-2" :size="size === 'sm' ? 14 : 16" class="btn__spin" />
    <Icon v-else-if="iconStart" :name="iconStart" :size="size === 'sm' ? 14 : 16" />
    <span class="btn__label"><slot /></span>
    <Icon v-if="iconEnd && !loading" :name="iconEnd" :size="size === 'sm' ? 14 : 16" />
  </button>
</template>

<style scoped>
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
  transition: background var(--motion-base) var(--motion-ease),
              color var(--motion-base) var(--motion-ease),
              border-color var(--motion-base) var(--motion-ease),
              transform var(--motion-fast) var(--motion-ease);
  white-space: nowrap;
}
.btn--block { width: 100%; }

.btn--sm { padding: 6px 12px; font-size: var(--font-size-xs); }
.btn--md { padding: 9px 16px; font-size: var(--font-size-sm); }
.btn--lg { padding: 12px 22px; font-size: var(--font-size-base); }

.btn--primary {
  background: var(--color-brand-primary);
  color: #fff;
}
.btn--primary:hover:not(:disabled) {
  background: var(--color-brand-primary-hover);
  transform: translateY(-1px);
}
.btn--primary:active:not(:disabled) { transform: translateY(0); }

.btn--secondary {
  background: var(--color-surface-raised);
  color: var(--color-text-primary);
  border-color: var(--color-border-strong);
}
.btn--secondary:hover:not(:disabled) {
  background: var(--color-surface-sunken);
}

.btn--ghost {
  background: transparent;
  color: var(--color-text-secondary);
}
.btn--ghost:hover:not(:disabled) {
  background: var(--color-surface-sunken);
  color: var(--color-text-primary);
}

.btn--danger {
  background: var(--color-status-danger);
  color: #fff;
}
.btn--danger:hover:not(:disabled) { filter: brightness(0.95); }

.btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }

.btn__label:empty { display: none; }

.btn__spin {
  animation: btn-spin 800ms linear infinite;
}
@keyframes btn-spin {
  to { transform: rotate(360deg); }
}
</style>
