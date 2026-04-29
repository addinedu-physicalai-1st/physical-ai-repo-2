<script setup lang="ts">
import type { AttendanceRecord } from '@/types'
import BaseAvatar from '@/components/common/BaseAvatar.vue'
import BaseBadge from '@/components/common/BaseBadge.vue'

defineProps<{ records: AttendanceRecord[] }>()

function timeLabel(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function status(r: AttendanceRecord): { variant: 'success' | 'info' | 'neutral'; label: string } {
  if (r.check_out) return { variant: 'info',    label: `${timeLabel(r.check_out)} 하원` }
  if (r.check_in)  return { variant: 'success', label: `${timeLabel(r.check_in)} 등원` }
  return { variant: 'neutral', label: '미등원' }
}
</script>

<template>
  <div class="grid">
    <div
      v-for="r in records"
      :key="r.child_id"
      class="cell"
      :class="{ 'cell--in': r.check_in, 'cell--out': r.check_out }"
    >
      <BaseAvatar :name="r.child_name" :size="44" />
      <div class="cell__name">{{ r.child_name }}</div>
      <BaseBadge :variant="status(r).variant" size="sm">{{ status(r).label }}</BaseBadge>
    </div>
  </div>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: var(--space-3);
}
.cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-4);
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-xs);
  transition: border-color var(--motion-base) var(--motion-ease);
}
.cell--in  { border-color: var(--color-status-success-soft); }
.cell--out { border-color: var(--color-status-info-soft); opacity: 0.85; }
.cell__name {
  font-weight: var(--font-weight-semibold);
  font-size: var(--font-size-sm);
  color: var(--color-text-primary);
}
</style>
