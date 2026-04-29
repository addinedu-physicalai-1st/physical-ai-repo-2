<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { api } from '@/api/client'
import { localDateKey } from '@/lib/date'
import type { AttendanceRecord, MenuEntry, Report } from '@/types'
import AttendanceGrid from '@/components/teacher/AttendanceGrid.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import BaseCard from '@/components/common/BaseCard.vue'
import BaseSkeleton from '@/components/common/BaseSkeleton.vue'
import BaseEmptyState from '@/components/common/BaseEmptyState.vue'
import Icon from '@/components/common/Icon.vue'

const today = localDateKey()
const records = ref<AttendanceRecord[]>([])
const menu = ref<MenuEntry | null>(null)
const pendingReports = ref<Report[]>([])
const loading = ref(true)

const summary = computed(() => {
  const total = records.value.length
  const checkedIn = records.value.filter((r) => r.check_in).length
  const checkedOut = records.value.filter((r) => r.check_out).length
  return {
    total,
    checkedIn,
    checkedOut,
    missing: total - checkedIn,
  }
})

onMounted(async () => {
  try {
    const [att, m, reps] = await Promise.all([
      api.get<AttendanceRecord[]>(`/api/attendance?date=${today}`),
      api.get<MenuEntry>(`/api/menu?date=${today}`),
      api.get<Report[]>(`/api/reports?date=${today}&status=pending`),
    ])
    records.value = att
    menu.value = m
    pendingReports.value = reps
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <section>
    <PageHeader title="출결 현황" :description="`오늘 ${today} 기준`">
      <template #actions>
        <span class="date-pill numeric">
          <Icon name="calendar" :size="14" />
          {{ today }}
        </span>
      </template>
    </PageHeader>

    <div class="kpis">
      <BaseCard class="kpi" :padded="true">
        <div class="kpi__inner">
          <span class="kpi__label">전체</span>
          <div class="kpi__main">
            <span class="kpi__value numeric">{{ summary.total }}</span>
            <span class="kpi__hint">명</span>
          </div>
        </div>
      </BaseCard>
      <BaseCard class="kpi kpi--success" :padded="true">
        <div class="kpi__inner">
          <span class="kpi__label">등원</span>
          <div class="kpi__main">
            <span class="kpi__value numeric">{{ summary.checkedIn }}</span>
            <span class="kpi__hint">명</span>
          </div>
        </div>
      </BaseCard>
      <BaseCard class="kpi kpi--info" :padded="true">
        <div class="kpi__inner">
          <span class="kpi__label">하원</span>
          <div class="kpi__main">
            <span class="kpi__value numeric">{{ summary.checkedOut }}</span>
            <span class="kpi__hint">명</span>
          </div>
        </div>
      </BaseCard>
      <BaseCard class="kpi kpi--warning" :padded="true">
        <div class="kpi__inner">
          <span class="kpi__label">미등원</span>
          <div class="kpi__main">
            <span class="kpi__value numeric">{{ summary.missing }}</span>
            <span class="kpi__hint">명</span>
          </div>
        </div>
      </BaseCard>
    </div>

    <BaseCard class="grid-card" :padded="true">
      <template #header>
        <div class="grid-card__head">
          <Icon name="users-round" :size="16" />
          <span>반 명단</span>
        </div>
      </template>
      <div v-if="loading" class="loading">
        <BaseSkeleton v-for="n in 6" :key="n" height="120px" radius="var(--radius-lg)" />
      </div>
      <BaseEmptyState
        v-else-if="!records.length"
        icon="users-round"
        title="오늘 등록된 어린이가 없습니다"
        description="어린이를 등록하면 여기서 출결 현황을 확인할 수 있어요."
      />
      <AttendanceGrid v-else :records="records" />
    </BaseCard>

    <div class="bottom">
      <BaseCard :padded="true">
        <template #header>
          <div class="bottom__head"><Icon name="utensils" :size="16" /><span>오늘 점심</span></div>
        </template>
        <p class="bottom__value">
          {{ menu && menu.items.length ? menu.items.join(', ') : '미등록' }}
        </p>
      </BaseCard>
      <BaseCard :padded="true">
        <template #header>
          <div class="bottom__head"><Icon name="file-text" :size="16" /><span>미작성 보고서</span></div>
        </template>
        <p class="bottom__value" :class="{ 'bottom__value--alert': pendingReports.length > 0 }">
          <span class="numeric">{{ pendingReports.length }}</span><span class="bottom__unit">건</span>
        </p>
      </BaseCard>
    </div>
  </section>
</template>

<style scoped>
.date-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: var(--radius-full);
  background: var(--color-surface-sunken);
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.kpis {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-3);
  margin-bottom: var(--space-5);
}
.kpi__inner {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.kpi__label {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-secondary);
  letter-spacing: 0.02em;
}
.kpi__main {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
}
.kpi__value {
  font-size: var(--font-size-3xl);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  line-height: 1;
}
.kpi__hint {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
.kpi--success .kpi__value { color: var(--color-status-success); }
.kpi--info    .kpi__value { color: var(--color-status-info); }
.kpi--warning .kpi__value { color: var(--color-status-warning); }

.grid-card { margin-bottom: var(--space-4); }
.grid-card__head { display: flex; align-items: center; gap: var(--space-2); color: var(--color-text-secondary); font-size: var(--font-size-sm); }
.loading { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: var(--space-3); }

.bottom { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-3); }
.bottom__head { display: flex; align-items: center; gap: var(--space-2); color: var(--color-text-secondary); font-size: var(--font-size-sm); }
.bottom__value { font-size: var(--font-size-lg); font-weight: var(--font-weight-semibold); color: var(--color-text-primary); margin: 0; }
.bottom__value--alert { color: var(--color-status-danger); }
.bottom__unit { font-size: var(--font-size-sm); color: var(--color-text-muted); margin-left: 2px; }
</style>
