<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { api } from '@/api/client'
import { useChildStore } from '@/stores/child'
import type { Child } from '@/types'
import BaseAvatar from '@/components/common/BaseAvatar.vue'

const child = useChildStore()
const children = ref<Child[]>([])

onMounted(async () => {
  children.value = await api.get<Child[]>('/api/parent/children')
  if (children.value.length && child.selectedChildId === null) {
    child.select(children.value[0].id)
  }
})

watch(() => children.value, () => {
  if (child.selectedChildId && !children.value.find((c) => c.id === child.selectedChildId)) {
    child.select(children.value[0]?.id ?? 0)
  }
})
</script>

<template>
  <div v-if="children.length > 0" class="picker">
    <span class="picker__label">자녀</span>
    <div class="picker__list">
      <button
        v-for="c in children"
        :key="c.id"
        class="chip"
        :class="{ 'chip--active': c.id === child.selectedChildId }"
        @click="child.select(c.id)"
      >
        <BaseAvatar :name="c.name" :src="c.photo_url ?? null" :size="22" />
        <span>{{ c.name }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.picker { display: flex; align-items: center; gap: var(--space-3); width: 100%; }
.picker__label {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.picker__list { display: flex; gap: var(--space-2); flex-wrap: wrap; }
.chip {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-full);
  padding: 4px 12px 4px 4px;
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: background var(--motion-base) var(--motion-ease),
              border-color var(--motion-base) var(--motion-ease),
              color var(--motion-base) var(--motion-ease);
}
.chip:hover { border-color: var(--color-border-strong); color: var(--color-text-primary); }
.chip--active {
  background: var(--color-brand-primary-soft);
  border-color: var(--color-brand-primary);
  color: var(--color-brand-primary);
  font-weight: var(--font-weight-semibold);
}
</style>
