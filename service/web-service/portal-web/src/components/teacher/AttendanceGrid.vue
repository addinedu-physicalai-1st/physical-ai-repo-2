<script setup lang="ts">
import type { AttendanceRecord } from '@/types'
import BaseAvatar from '@/components/common/BaseAvatar.vue'
import BaseBadge from '@/components/common/BaseBadge.vue'

const props = defineProps<{
  records: AttendanceRecord[]
  /** 디버그: 등/하원 리셋 진행 중인 (child_id:type) — 버튼 disable 용. 예: "12:IN" */
  resettingKeys?: Set<string>
}>()

const emit = defineEmits<{
  /** 교사가 디버그용 리셋 버튼을 눌렀을 때 — Dashboard 가 DELETE 호출 + 로컬 state 갱신 담당. */
  (e: 'reset', payload: { childId: number; childName: string; type: 'IN' | 'OUT' }): void
}>()

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

function isResetting(r: AttendanceRecord, type: 'IN' | 'OUT'): boolean {
  return !!props.resettingKeys?.has(`${r.child_id}:${type}`)
}

function onReset(r: AttendanceRecord, type: 'IN' | 'OUT'): void {
  const label = type === 'IN' ? '등원' : '하원'
  const ok = window.confirm(
    `${r.child_name} 어린이의 오늘 ${label} 기록을 삭제할까요?\n` +
      `삭제하면 다음 카메라 인식 때 ${label} 인사 모션이 다시 재생돼요.`,
  )
  if (!ok) return
  emit('reset', { childId: r.child_id, childName: r.child_name, type })
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

      <div v-if="r.check_in || r.check_out" class="cell__reset">
        <button
          v-if="r.check_in"
          type="button"
          class="reset-btn"
          :disabled="isResetting(r, 'IN')"
          :title="`${r.child_name} 어린이 오늘 등원 기록 삭제 (인사 모션 재테스트용)`"
          @click="onReset(r, 'IN')"
        >
          {{ isResetting(r, 'IN') ? '삭제 중…' : '등원 리셋' }}
        </button>
        <button
          v-if="r.check_out"
          type="button"
          class="reset-btn"
          :disabled="isResetting(r, 'OUT')"
          :title="`${r.child_name} 어린이 오늘 하원 기록 삭제 (인사 모션 재테스트용)`"
          @click="onReset(r, 'OUT')"
        >
          {{ isResetting(r, 'OUT') ? '삭제 중…' : '하원 리셋' }}
        </button>
      </div>
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
.cell__reset {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: center;
}
.reset-btn {
  font: inherit;
  font-size: 11px;
  font-weight: var(--font-weight-medium);
  padding: 3px 10px;
  background: transparent;
  color: var(--color-text-muted);
  border: 1px solid var(--color-border-subtle);
  border-radius: 999px;
  cursor: pointer;
  transition: color var(--motion-base) var(--motion-ease),
    border-color var(--motion-base) var(--motion-ease),
    background var(--motion-base) var(--motion-ease);
}
.reset-btn:hover:not(:disabled) {
  color: var(--color-status-danger);
  border-color: var(--color-status-danger);
  background: color-mix(in srgb, var(--color-status-danger) 6%, transparent);
}
.reset-btn:disabled {
  opacity: 0.5;
  cursor: progress;
}
</style>
