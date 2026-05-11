<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { api } from '@/api/client'
import { localDateKey } from '@/lib/date'
import type { Child, Report } from '@/types'
import ReportEditor from '@/components/teacher/ReportEditor.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import BaseCard from '@/components/common/BaseCard.vue'
import BaseSelect from '@/components/common/BaseSelect.vue'
import BaseInput from '@/components/common/BaseInput.vue'
import BaseEmptyState from '@/components/common/BaseEmptyState.vue'
import BaseAvatar from '@/components/common/BaseAvatar.vue'
import BaseBadge from '@/components/common/BaseBadge.vue'

const today = localDateKey()
const children = ref<Child[]>([])
const className = ref<string>('')
const date = ref(today)
const reports = ref<Map<number, Report | null>>(new Map())
const loading = ref(false)
const error = ref<string | null>(null)

const classNames = computed(() => {
  const set = new Set(children.value.map((c) => c.class_name))
  return [...set].sort()
})

const filtered = computed(() =>
  children.value
    .filter((c) => !className.value || c.class_name === className.value)
    .sort((a, b) => a.name.localeCompare(b.name))
)

onMounted(async () => {
  children.value = await api.get<Child[]>('/api/children')
  if (classNames.value.length) className.value = classNames.value[0]
})

watch([filtered, date], async () => {
  if (!filtered.value.length) {
    reports.value = new Map()
    return
  }
  loading.value = true
  error.value = null
  try {
    const next = new Map<number, Report | null>()
    await Promise.all(
      filtered.value.map(async (c) => {
        const list = await api.get<Report[]>(
          `/api/reports?child_id=${c.id}&date=${date.value}`,
        )
        next.set(c.id, list[0] ?? null)
      }),
    )
    reports.value = next
  } catch {
    error.value = '보고서를 불러올 수 없습니다.'
  } finally {
    loading.value = false
  }
}, { immediate: true })

function onSaved(updated: Report) {
  reports.value.set(updated.child_id, updated)
}
</script>

<template>
  <section>
    <PageHeader title="일과 보고서" description="반과 날짜를 선택하면 어린이별 보고서가 표시됩니다." />

    <div class="filters">
      <BaseSelect
        v-model="className"
        label="반"
        :options="classNames.map(cn => ({ value: cn, label: cn }))"
      />
      <BaseInput v-model="date" type="date" label="날짜" />
    </div>

    <p v-if="error" class="info">{{ error }}</p>
    <p v-else-if="loading" class="info">불러오는 중...</p>
    <BaseEmptyState
      v-else-if="!filtered.length"
      icon="users-round"
      title="해당 반에 어린이가 없습니다"
      description="다른 반을 선택하거나 어린이를 등록하세요."
    />

    <div v-else class="grid">
      <BaseCard v-for="c in filtered" :key="c.id" class="card grid-card--reports" :padded="true">
        <template #header>
          <div class="card-head">
            <BaseAvatar :name="c.name" :size="32" />
            <div class="card-head__text">
              <strong>{{ c.name }}</strong>
              <span>{{ c.class_name }} · {{ c.birth_date }}</span>
            </div>
            <BaseBadge :variant="reports.get(c.id) ? 'success' : 'neutral'" size="sm">
              {{ reports.get(c.id) ? '작성됨' : '대기' }}
            </BaseBadge>
          </div>
        </template>
        <ReportEditor
          v-if="reports.get(c.id)"
          :report="reports.get(c.id)!"
          @saved="onSaved"
        />
        <p v-else class="info small">보고서가 아직 없습니다 (하원 후 자동 생성).</p>
      </BaseCard>
    </div>
  </section>
</template>

<style scoped>
.filters {
  display: grid;
  grid-template-columns: 200px 200px;
  gap: var(--space-3);
  margin-bottom: var(--space-5);
}
.info { color: var(--color-text-muted); padding: var(--space-5) 0; }
.info.small { padding: var(--space-2) 0; font-size: var(--font-size-sm); }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(380px, 1fr)); gap: var(--space-4); }
.card-head { display: flex; align-items: center; gap: var(--space-3); width: 100%; }
.card-head__text { display: flex; flex-direction: column; gap: 2px; flex: 1; min-width: 0; }
.card-head__text strong { font-size: var(--font-size-sm); }
.card-head__text span { font-size: var(--font-size-xs); color: var(--color-text-muted); }
.grid-card--reports {
  position: relative;
  overflow: hidden;
}
.grid-card--reports::after {
  content: '📝';
  position: absolute;
  bottom: -20px;
  right: -20px;
  font-size: 140px;
  opacity: 0.12;
  transform: rotate(-15deg);
  pointer-events: none;
}
</style>
