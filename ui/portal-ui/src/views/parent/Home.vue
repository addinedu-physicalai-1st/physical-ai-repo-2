<script setup lang="ts">
import { ref, watchEffect, computed } from 'vue'
import { api } from '@/api/client'
import { localDateKey } from '@/lib/date'
import { useChildStore } from '@/stores/child'
import { useAuthStore } from '@/stores/auth'
import type { AttendanceRecord, MenuEntry, Photo, Report } from '@/types'
import HomeCard from '@/components/parent/HomeCard.vue'

const auth = useAuthStore()
const child = useChildStore()
const today = localDateKey()

const att = ref<AttendanceRecord | null>(null)
const menu = ref<MenuEntry | null>(null)
const photos = ref<Photo[]>([])
const report = ref<Report | null>(null)
const schedule = ref<Record<string, string>>({})

watchEffect(async () => {
  if (child.selectedChildId === null) return
  const id = child.selectedChildId
  const [a, m, p, r, s] = await Promise.all([
    api.get<AttendanceRecord[]>(`/api/children/${id}/attendance?date=${today}`).then((arr) => arr[0] ?? null),
    api.get<MenuEntry>(`/api/menu?date=${today}`).catch(() => null),
    api.get<Photo[]>(`/api/children/${id}/photos?date=${today}`).catch(() => []),
    api.get<Report[]>(`/api/reports?child_id=${id}&date=${today}`).then((arr) => arr[0] ?? null),
    api.get<Record<string, string>>('/api/schedule').catch(() => ({})),
  ])
  att.value = a
  menu.value = m
  photos.value = p
  report.value = r
  schedule.value = s
})

const checkInLabel = computed(() => {
  if (!att.value?.check_in) return '미등원'
  const d = new Date(att.value.check_in)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')} 등원 완료`
})

const checkOutHint = computed(() =>
  att.value?.check_out
    ? `하원: ${new Date(att.value.check_out).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })}`
    : '하원: 아직 전'
)

const dateLabel = today.replace(/-/g, '.')

const nextActivity = computed(() => {
  const now = new Date()
  const timeStr = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`
  
  const entries = Object.entries(schedule.value)
  for (const [timeRange, activity] of entries) {
    const [start] = timeRange.split('-')
    if (start > timeStr) return `${start} ${activity}`
  }
  return '오늘 일과 종료'
})
</script>

<template>
  <section>
    <header class="hello">
      <div>
        <p class="hello__greet">안녕하세요,</p>
        <h1 class="hello__name">{{ auth.user?.name }} 님</h1>
      </div>
      <span class="hello__date numeric">{{ dateLabel }}</span>
    </header>

    <div class="grid">
      <HomeCard
        to="/parent/attendance" icon="bus" title="오늘 등원"
        :primary="checkInLabel" :secondary="checkOutHint" variant="info"
      />
      <HomeCard
        to="/parent/menu" icon="utensils" title="오늘 점심"
        :primary="menu?.items[0] ?? '미등록'"
        :secondary="menu && menu.items.length > 1 ? menu.items.slice(1).join(', ') : ''"
        variant="brand"
      />
      <HomeCard
        to="/parent/photos" icon="images" title="사진첩"
        :primary="photos.length ? `오늘 ${photos.length}장 새로 추가` : '오늘 사진 없음'"
        secondary="전체 보기"
        variant="success"
      />
      <HomeCard
        to="/parent/report" icon="file-text" title="일과 보고서"
        :primary="report ? '오늘 보고서 보기' : '하원 후 생성됩니다'"
        secondary="이전 보고서"
        variant="warm"
      />
      <HomeCard
        to="/parent/schedule" icon="calendar" title="일과표"
        primary="정규 일과표 보기"
        :secondary="nextActivity"
        variant="info"
      />
    </div>
  </section>
</template>

<style scoped>
.hello {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  margin-bottom: var(--space-6);
}
.hello__greet { color: var(--color-text-muted); font-size: var(--font-size-sm); margin-bottom: var(--space-1); }
.hello__name { font-size: var(--font-size-2xl); }
.hello__date { color: var(--color-text-muted); font-size: var(--font-size-sm); }

.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-3);
}
</style>
