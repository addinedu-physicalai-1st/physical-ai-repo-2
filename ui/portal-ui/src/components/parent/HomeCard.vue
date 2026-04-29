<script setup lang="ts">
import { RouterLink } from 'vue-router'
import Icon from '@/components/common/Icon.vue'

withDefaults(defineProps<{
  to: string
  icon: string
  title: string
  primary: string
  secondary?: string
  variant?: 'brand' | 'info' | 'warm' | 'success'
}>(), { variant: 'brand' })
</script>

<template>
  <RouterLink :to="to" :class="['home-card', `home-card--${variant}`]">
    <span class="home-card__icon">
      <Icon :name="icon" :size="22" />
    </span>
    <div class="home-card__body">
      <span class="home-card__title">{{ title }}</span>
      <span class="home-card__primary">{{ primary }}</span>
      <span v-if="secondary" class="home-card__secondary">{{ secondary }}</span>
    </div>
    <span class="home-card__arrow">
      <Icon name="chevron-right" :size="18" />
    </span>
  </RouterLink>
</template>

<style scoped>
.home-card {
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-5) var(--space-5);
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-lg);
  text-decoration: none;
  color: inherit;
  box-shadow: var(--shadow-xs);
  transition: transform var(--motion-base) var(--motion-ease),
              box-shadow var(--motion-base) var(--motion-ease),
              border-color var(--motion-base) var(--motion-ease);
  min-height: 112px;
}
.home-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
  border-color: var(--color-border-strong);
}

.home-card__icon {
  width: 44px;
  height: 44px;
  border-radius: var(--radius-md);
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.home-card--brand   .home-card__icon { background: var(--color-brand-primary-soft);    color: var(--color-brand-primary); }
.home-card--info    .home-card__icon { background: var(--color-status-info-soft);      color: var(--color-status-info); }
.home-card--warm    .home-card__icon { background: var(--color-accent-warm-soft);      color: var(--color-status-warning); }
.home-card--success .home-card__icon { background: var(--color-status-success-soft);   color: var(--color-status-success); }

.home-card__body { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.home-card__title {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.home-card__primary {
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  line-height: var(--line-height-tight);
}
.home-card__secondary {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.home-card__arrow {
  color: var(--color-text-muted);
  transition: transform var(--motion-fast) var(--motion-ease), color var(--motion-base) var(--motion-ease);
}
.home-card:hover .home-card__arrow { color: var(--color-brand-primary); transform: translateX(2px); }
</style>
