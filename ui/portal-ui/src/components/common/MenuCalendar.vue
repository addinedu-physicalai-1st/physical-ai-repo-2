<script setup lang="ts">
import { ref, watchEffect, computed } from 'vue'
import { api } from '@/api/client'
import { localDateKey } from '@/lib/date'
import type { MenuEntry } from '@/types'
import Icon from '@/components/common/Icon.vue'
import BaseCard from '@/components/common/BaseCard.vue'

const now = new Date()
const year = ref(now.getFullYear())
const month = ref(now.getMonth() + 1)
const entries = ref<MenuEntry[]>([])
const selectedDate = ref<string>(localDateKey(now))
const loading = ref(false)

const monthKey = computed(() => `${year.value}-${String(month.value).padStart(2, '0')}`)

watchEffect(async () => {
  loading.value = true
  try {
    entries.value = await api.get<MenuEntry[]>(`/api/menu?month=${monthKey.value}`)
  } finally {
    loading.value = false
  }
})

interface Cell {
  date: string
  day: number
  inMonth: boolean
  items: string[]
  isToday: boolean
  isSelected: boolean
}

const cells = computed<Cell[]>(() => {
  const first = new Date(year.value, month.value - 1, 1)
  const start = new Date(first)
  start.setDate(1 - first.getDay())
  const todayKey = localDateKey()

  const arr: Cell[] = []
  for (let i = 0; i < 42; i++) {
    const d = new Date(start)
    d.setDate(start.getDate() + i)
    const dateKey = localDateKey(d)
    const entry = entries.value.find((e) => e.date === dateKey)
    arr.push({
      date: dateKey,
      day: d.getDate(),
      inMonth: d.getMonth() === month.value - 1,
      items: entry?.items ?? [],
      isToday: dateKey === todayKey,
      isSelected: dateKey === selectedDate.value,
    })
  }
  return arr
})

const selectedItems = computed(() => {
  const e = entries.value.find((x) => x.date === selectedDate.value)
  return e?.items ?? []
})

function shift(delta: number) {
  let m = month.value + delta
  let y = year.value
  while (m < 1)  { m += 12; y -= 1 }
  while (m > 12) { m -= 12; y += 1 }
  month.value = m
  year.value = y
}

const weekdays = ['일', '월', '화', '수', '목', '금', '토']
</script>

<template>
  <div class="menu-grid">
    <BaseCard class="menu-grid__calendar" :padded="true">
      <template #header>
        <div class="cal-head">
          <button class="cal-nav" aria-label="이전 달" @click="shift(-1)">
            <Icon name="chevron-left" :size="18" />
          </button>
          <h2 class="cal-title numeric">{{ year }}.{{ String(month).padStart(2, '0') }}</h2>
          <button class="cal-nav" aria-label="다음 달" @click="shift(1)">
            <Icon name="chevron-right" :size="18" />
          </button>
        </div>
      </template>

      <div class="weekdays">
        <div
          v-for="(w, i) in weekdays"
          :key="w"
          :class="{ 'wk-sun': i === 0, 'wk-sat': i === 6 }"
        >{{ w }}</div>
      </div>
      <div class="grid">
        <button
          v-for="cell in cells"
          :key="cell.date"
          type="button"
          class="cell"
          :class="{
            'cell--outside': !cell.inMonth,
            'cell--today': cell.isToday,
            'cell--selected': cell.isSelected,
            'cell--has-menu': cell.items.length > 0,
          }"
          @click="selectedDate = cell.date"
        >
          <span class="cell__day numeric">{{ cell.day }}</span>
          <span v-if="cell.items.length" class="cell__first">{{ cell.items[0] }}</span>
          <span v-if="cell.items.length" class="cell__dot" />
        </button>
      </div>
    </BaseCard>

    <BaseCard class="menu-grid__detail" :padded="true">
      <template #header>
        <div class="detail-head">
          <Icon name="utensils" :size="16" />
          <span class="numeric">{{ selectedDate }}</span>
        </div>
      </template>
      <ul v-if="selectedItems.length" class="detail-list">
        <li v-for="item in selectedItems" :key="item">{{ item }}</li>
      </ul>
      <p v-else class="detail-empty">등록된 메뉴가 없습니다.</p>
    </BaseCard>
  </div>
</template>

<style scoped>
.menu-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 280px;
  gap: var(--space-5);
  align-items: start;
}

.cal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}
.cal-title { font-size: var(--font-size-lg); }
.cal-nav {
  width: 32px;
  height: 32px;
  background: transparent;
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-md);
  color: var(--color-text-secondary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background var(--motion-base) var(--motion-ease);
}
.cal-nav:hover { background: var(--color-surface-sunken); color: var(--color-text-primary); }

.weekdays {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  text-align: center;
  padding: var(--space-2) 0;
  letter-spacing: 0.04em;
}
.wk-sun { color: var(--color-status-danger); }
.wk-sat { color: var(--color-brand-secondary); }

.grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 6px; }
.cell {
  position: relative;
  min-height: 64px;
  padding: var(--space-2);
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-md);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  cursor: pointer;
  transition: background var(--motion-base) var(--motion-ease),
              border-color var(--motion-base) var(--motion-ease);
}
.cell:hover { border-color: var(--color-border-strong); }
.cell--outside { color: var(--color-text-muted); background: var(--color-surface-sunken); }
.cell--today { box-shadow: 0 0 0 2px var(--color-brand-primary-soft); border-color: var(--color-brand-primary); }
.cell--selected {
  background: var(--color-brand-primary-soft);
  border-color: var(--color-brand-primary);
}
.cell__day { font-size: var(--font-size-xs); font-weight: var(--font-weight-semibold); }
.cell__first {
  font-size: 11px;
  color: var(--color-text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}
.cell__dot {
  position: absolute;
  bottom: 6px;
  right: 6px;
  width: 6px;
  height: 6px;
  background: var(--color-brand-primary);
  border-radius: var(--radius-full);
}
.cell--selected .cell__dot { background: var(--color-brand-primary-hover); }

.detail-head { display: flex; align-items: center; gap: var(--space-2); color: var(--color-text-secondary); font-size: var(--font-size-sm); }
.detail-list { list-style: none; margin: 0; padding: 0; }
.detail-list li {
  padding: var(--space-2) 0;
  border-bottom: 1px solid var(--color-border-subtle);
  font-size: var(--font-size-sm);
}
.detail-list li:last-child { border-bottom: none; }
.detail-empty { color: var(--color-text-muted); font-size: var(--font-size-sm); }
</style>
