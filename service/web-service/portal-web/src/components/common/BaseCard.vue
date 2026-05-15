<script setup lang="ts">
withDefaults(defineProps<{
  padded?: boolean
  interactive?: boolean
  as?: string
}>(), {
  padded: true,
  interactive: false,
  as: 'div',
})
</script>

<template>
  <component :is="as" :class="['card', { 'card--padded': padded, 'card--interactive': interactive }]">
    <header v-if="$slots.header" class="card__header">
      <slot name="header" />
    </header>
    <div class="card__body">
      <slot />
    </div>
    <footer v-if="$slots.footer" class="card__footer">
      <slot name="footer" />
    </footer>
  </component>
</template>

<style scoped>
.card {
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-xs);
  display: flex;
  flex-direction: column;
}
.card--padded > .card__header,
.card--padded > .card__body,
.card--padded > .card__footer { padding: var(--space-5) var(--space-6); }

.card__header {
  border-bottom: 1px solid var(--color-border-subtle);
  font-weight: var(--font-weight-semibold);
}
.card__footer {
  border-top: 1px solid var(--color-border-subtle);
  background: var(--color-surface-sunken);
}

.card--interactive {
  cursor: pointer;
  transition: box-shadow var(--motion-base) var(--motion-ease),
              transform var(--motion-fast) var(--motion-ease),
              border-color var(--motion-base) var(--motion-ease);
}
.card--interactive:hover {
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
  border-color: var(--color-border-strong);
}
</style>
