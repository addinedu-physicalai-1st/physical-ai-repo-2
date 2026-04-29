<script setup lang="ts">
import { RouterLink } from 'vue-router'
import Icon from './Icon.vue'

withDefaults(defineProps<{
  to: string
  icon?: string
  label: string
  badge?: string | number | null
  variant?: 'sidebar' | 'topbar'
}>(), { variant: 'sidebar' })
</script>

<template>
  <RouterLink :to="to" :class="['nav-item', `nav-item--${variant}`]" active-class="is-active">
    <Icon v-if="icon" :name="icon" :size="18" class="nav-item__icon" />
    <span class="nav-item__label">{{ label }}</span>
    <span v-if="badge !== null && badge !== undefined && badge !== ''" class="nav-item__badge">{{ badge }}</span>
  </RouterLink>
</template>

<style scoped>
.nav-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  text-decoration: none;
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  transition: background var(--motion-base) var(--motion-ease),
              color var(--motion-base) var(--motion-ease);
  position: relative;
}

.nav-item--sidebar {
  padding: 10px 16px 10px 14px;
  color: var(--color-text-on-inverse-muted);
  border-left: 3px solid transparent;
}
.nav-item--sidebar:hover {
  color: var(--color-text-on-inverse);
  background: rgba(255, 255, 255, 0.04);
}
.nav-item--sidebar.is-active {
  color: var(--color-text-on-inverse);
  background: var(--color-brand-primary-soft-inverse);
  border-left-color: var(--color-brand-primary);
}

.nav-item--topbar {
  padding: 8px 4px;
  color: var(--color-text-secondary);
}
.nav-item--topbar:hover { color: var(--color-text-primary); }
.nav-item--topbar.is-active {
  color: var(--color-brand-primary);
}
.nav-item--topbar.is-active::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: -15px;
  height: 2px;
  background: var(--color-brand-primary);
  border-radius: 2px;
}

.nav-item__icon { flex-shrink: 0; }
.nav-item__label { flex: 1; }
.nav-item__badge {
  background: var(--color-brand-primary);
  color: #fff;
  font-size: var(--font-size-xs);
  padding: 1px 6px;
  border-radius: var(--radius-full);
  font-weight: var(--font-weight-semibold);
}
</style>
