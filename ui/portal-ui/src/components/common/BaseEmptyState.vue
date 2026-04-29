<script setup lang="ts">
import Icon from './Icon.vue'

withDefaults(defineProps<{
  icon?: string
  title: string
  description?: string
}>(), { icon: 'inbox' })
</script>

<template>
  <div class="empty">
    <span class="empty__icon">
      <Icon :name="icon" :size="28" :stroke-width="1.5" />
    </span>
    <h3 class="empty__title">{{ title }}</h3>
    <p v-if="description" class="empty__desc">{{ description }}</p>
    <div v-if="$slots.action" class="empty__action">
      <slot name="action" />
    </div>
  </div>
</template>

<style scoped>
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: var(--space-9) var(--space-6);
  color: var(--color-text-secondary);
}
.empty__icon {
  width: 56px;
  height: 56px;
  border-radius: var(--radius-full);
  background: var(--color-surface-sunken);
  color: var(--color-text-muted);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-bottom: var(--space-4);
}
.empty__title {
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin-bottom: var(--space-1);
}
.empty__desc {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
  max-width: 320px;
}
.empty__action { margin-top: var(--space-4); }
</style>
