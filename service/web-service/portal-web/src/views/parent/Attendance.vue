<script setup lang="ts">
import { ref, watchEffect } from 'vue'
import { api } from '@/api/client'
import { useChildStore } from '@/stores/child'
import type { AttendanceRecord } from '@/types'
import PageHeader from '@/components/common/PageHeader.vue'
import BaseCard from '@/components/common/BaseCard.vue'
import BaseBadge from '@/components/common/BaseBadge.vue'
import BaseEmptyState from '@/components/common/BaseEmptyState.vue'
import Icon from '@/components/common/Icon.vue'

const child = useChildStore()
const records = ref<AttendanceRecord[]>([])

watchEffect(async () => {
  if (child.selectedChildId === null) return
  records.value = await api.get<AttendanceRecord[]>(
    `/api/children/${child.selectedChildId}/attendance`
  )
})

function fmtTime(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function dateOf(iso: string | null): string {
  if (!iso) return ''
  const [y, m, d] = iso.slice(0, 10).split('-')
  return `${y}.${m}.${d}`
}
</script>

<template>
  <section>
    <PageHeader title="등·하원 이력" description="자녀의 최근 등하원 기록을 확인합니다." />

    <BaseCard v-if="records.length" :padded="true">
      <ol class="timeline">
        <li v-for="(r, idx) in records" :key="idx" class="timeline__row">
          <span class="timeline__date numeric">{{ dateOf(r.check_in ?? r.check_out) }}</span>
          <span class="timeline__bullet" :class="{ 'is-out': r.check_out, 'is-in': r.check_in && !r.check_out }" />
          <div class="timeline__entry">
            <BaseBadge :variant="r.check_in ? 'success' : 'neutral'" size="sm">
              <Icon name="log-in" :size="12" /> 등원
            </BaseBadge>
            <span class="timeline__time numeric">{{ fmtTime(r.check_in) }}</span>
          </div>
          <div class="timeline__entry">
            <BaseBadge :variant="r.check_out ? 'info' : 'neutral'" size="sm">
              <Icon name="log-out" :size="12" /> 하원
            </BaseBadge>
            <span class="timeline__time numeric">{{ fmtTime(r.check_out) }}</span>
          </div>
        </li>
      </ol>
    </BaseCard>

    <BaseEmptyState
      v-else
      icon="bus"
      title="기록이 없습니다"
      description="등하원 기록이 누적되면 여기에 표시됩니다."
    />
  </section>
</template>

<style scoped>
.timeline { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--space-3); }
.timeline__row {
  display: grid;
  grid-template-columns: 100px 24px 1fr 1fr;
  gap: var(--space-3);
  align-items: center;
  padding: var(--space-3);
  border-bottom: 1px solid var(--color-border-subtle);
}
.timeline__row:last-child { border-bottom: none; }
.timeline__date { font-size: var(--font-size-sm); color: var(--color-text-secondary); }
.timeline__bullet {
  width: 10px;
  height: 10px;
  border-radius: var(--radius-full);
  background: var(--color-border-strong);
  justify-self: center;
}
.timeline__bullet.is-in  { background: var(--color-status-success); box-shadow: 0 0 0 4px var(--color-status-success-soft); }
.timeline__bullet.is-out { background: var(--color-status-info);    box-shadow: 0 0 0 4px var(--color-status-info-soft); }
.timeline__entry { display: flex; align-items: center; gap: var(--space-2); }
.timeline__time { font-size: var(--font-size-sm); color: var(--color-text-primary); }
</style>
