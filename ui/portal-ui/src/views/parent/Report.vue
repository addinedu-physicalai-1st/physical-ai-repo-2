<script setup lang="ts">
import { ref, watchEffect } from 'vue'
import { api } from '@/api/client'
import { localDateKey } from '@/lib/date'
import { useChildStore } from '@/stores/child'
import type { Report } from '@/types'
import PageHeader from '@/components/common/PageHeader.vue'
import BaseCard from '@/components/common/BaseCard.vue'
import BaseInput from '@/components/common/BaseInput.vue'
import BaseEmptyState from '@/components/common/BaseEmptyState.vue'

const child = useChildStore()
const today = localDateKey()
const date = ref(today)
const report = ref<Report | null>(null)

watchEffect(async () => {
  if (child.selectedChildId === null) return
  const list = await api.get<Report[]>(
    `/api/reports?child_id=${child.selectedChildId}&date=${date.value}`
  )
  report.value = list[0] ?? null
})
</script>

<template>
  <section>
    <PageHeader title="일과 보고서" description="선생님이 작성한 일과 기록입니다.">
      <template #actions>
        <BaseInput v-model="date" type="date" />
      </template>
    </PageHeader>

    <BaseCard v-if="report" :padded="true">
      <article class="content">
        <p v-for="(line, i) in report.content.split('\n')" :key="i">{{ line }}</p>
      </article>
    </BaseCard>

    <BaseEmptyState
      v-else
      icon="file-text"
      title="선택한 날짜에 보고서가 없습니다"
      description="다른 날짜를 선택하거나 하원 후 다시 확인하세요."
    />
  </section>
</template>

<style scoped>
.content p { line-height: var(--line-height-relaxed); margin: 0 0 var(--space-2); color: var(--color-text-primary); font-size: var(--font-size-base); }
.content p:last-child { margin: 0; }
</style>
