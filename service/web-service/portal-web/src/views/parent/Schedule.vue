<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '@/api/client'
import PageHeader from '@/components/common/PageHeader.vue'
import BaseCard from '@/components/common/BaseCard.vue'
import BaseEmptyState from '@/components/common/BaseEmptyState.vue'
import Icon from '@/components/common/Icon.vue'

const schedule = ref<Record<string, string>>({})
const loading = ref(true)

onMounted(async () => {
  try {
    schedule.value = await api.get<Record<string, string>>('/api/schedule')
  } catch {
    schedule.value = {}
  } finally {
    loading.value = false
  }
})

const entries = computed(() => Object.entries(schedule.value))

const currentTime = ref(currentHHMM())
function currentHHMM(): string {
  const d = new Date()
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}
// 일과표는 분 단위로 활성 줄이 바뀌므로 60s 주기로 NOW 갱신 — 다음 활동 강조용.
let tickHandle: number | null = null
onMounted(() => {
  tickHandle = window.setInterval(() => {
    currentTime.value = currentHHMM()
  }, 60_000)
})
onBeforeUnmount(() => {
  if (tickHandle !== null) window.clearInterval(tickHandle)
})

function isActive(timeRange: string): boolean {
  const [start, end] = timeRange.split('-')
  if (!start || !end) return false
  return start <= currentTime.value && currentTime.value < end
}
</script>

<template>
  <section>
    <PageHeader title="일과표" description="우리 원의 하루 일정을 시간순으로 확인합니다." />

    <BaseCard v-if="entries.length" :padded="true">
      <ol class="schedule">
        <li
          v-for="([range, activity], i) in entries"
          :key="range"
          class="schedule__row"
          :class="{ 'is-active': isActive(range) }"
        >
          <span class="schedule__index numeric">{{ i + 1 }}</span>
          <div class="schedule__main">
            <span class="schedule__time numeric">{{ range }}</span>
            <span class="schedule__activity">{{ activity }}</span>
          </div>
          <Icon
            v-if="isActive(range)"
            name="circle-dot"
            :size="18"
            class="schedule__now"
            aria-label="지금 진행 중"
          />
        </li>
      </ol>
    </BaseCard>

    <BaseEmptyState
      v-else-if="!loading"
      icon="calendar"
      title="일과표가 없습니다"
      description="관리자가 등록한 일과표가 아직 없어요."
    />
  </section>
</template>

<style scoped>
.schedule {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.schedule__row {
  display: grid;
  grid-template-columns: 32px 1fr auto;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  background: var(--color-surface-base);
  border: 1px solid var(--color-border-subtle);
  transition: border-color var(--motion-base) var(--motion-ease),
              background var(--motion-base) var(--motion-ease);
}
.schedule__row.is-active {
  background: var(--color-brand-primary-soft);
  border-color: var(--color-brand-primary);
}
.schedule__index {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--color-surface-sunken);
  color: var(--color-text-secondary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-semibold);
}
.schedule__row.is-active .schedule__index {
  background: var(--color-brand-primary);
  color: #fff;
}
.schedule__main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.schedule__time {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}
.schedule__activity {
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-primary);
}
.schedule__now {
  color: var(--color-brand-primary);
}
</style>
