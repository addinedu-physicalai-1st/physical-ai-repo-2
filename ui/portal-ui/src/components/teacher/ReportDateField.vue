<script setup lang="ts">
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import Icon from '@/components/common/Icon.vue'
import { seoulDateKey } from '@/lib/date'

const props = withDefaults(
  defineProps<{
    modelValue: string
    maxDate: string
    label?: string
  }>(),
  { label: '날짜' },
)

const emit = defineEmits<{ (e: 'update:modelValue', v: string): void }>()

function parseParts(ymd: string): { y: number; m0: number; d: number } | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(ymd.trim())
  if (!m) return null
  return { y: Number(m[1]), m0: Number(m[2]) - 1, d: Number(m[3]) }
}

function toKey(y: number, m0: number, d: number): string {
  return `${y}-${String(m0 + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`
}

function initialVisibleMonth(): { y: number; m0: number } {
  const p = parseParts(props.modelValue)
  if (p) return { y: p.y, m0: p.m0 }
  const t = parseParts(seoulDateKey())
  return t ? { y: t.y, m0: t.m0 } : { y: new Date().getFullYear(), m0: new Date().getMonth() }
}

const rootRef = ref<HTMLElement | null>(null)
const open = ref(false)
const visible = ref(initialVisibleMonth())

function syncVisibleFromModel() {
  const p = parseParts(props.modelValue)
  if (p) visible.value = { y: p.y, m0: p.m0 }
}

watch(() => props.modelValue, syncVisibleFromModel, { immediate: true })

const monthTitle = computed(() => {
  const d = new Date(visible.value.y, visible.value.m0, 1)
  return new Intl.DateTimeFormat('ko-KR', { year: 'numeric', month: 'long' }).format(d)
})

const todayKey = computed(() => seoulDateKey())

const weekdayLabels = ['일', '월', '화', '수', '목', '금', '토']

const gridCells = computed(() => {
  const { y, m0 } = visible.value
  const firstDow = new Date(y, m0, 1).getDay()
  const lastDate = new Date(y, m0 + 1, 0).getDate()
  const cells: { key: string | null; day: number | null }[] = []
  for (let i = 0; i < firstDow; i++) cells.push({ key: null, day: null })
  for (let d = 1; d <= lastDate; d++) cells.push({ key: toKey(y, m0, d), day: d })
  return cells
})

function isDisabled(key: string): boolean {
  return key > props.maxDate
}

function selectDay(key: string) {
  if (isDisabled(key)) return
  emit('update:modelValue', key)
  open.value = false
}

function prevMonth() {
  let { y, m0 } = visible.value
  m0 -= 1
  if (m0 < 0) {
    m0 = 11
    y -= 1
  }
  visible.value = { y, m0 }
}

const canNextMonth = computed(() => {
  const { y, m0 } = visible.value
  const firstNext = new Date(y, m0 + 1, 1)
  const fk = toKey(firstNext.getFullYear(), firstNext.getMonth(), 1)
  return fk <= props.maxDate
})

function nextMonth() {
  if (!canNextMonth.value) return
  let { y, m0 } = visible.value
  m0 += 1
  if (m0 > 11) {
    m0 = 0
    y += 1
  }
  visible.value = { y, m0 }
}

function goToday() {
  const t = todayKey.value
  const pick = t > props.maxDate ? props.maxDate : t
  emit('update:modelValue', pick)
  const p = parseParts(pick)
  if (p) visible.value = { y: p.y, m0: p.m0 }
  open.value = false
}

const displayLabel = computed(() => {
  const p = parseParts(props.modelValue)
  if (!p) return props.modelValue
  const d = new Date(p.y, p.m0, p.d)
  return new Intl.DateTimeFormat('ko-KR', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    weekday: 'short',
  }).format(d)
})

function onDocMouseDown(e: MouseEvent) {
  if (!open.value || !rootRef.value) return
  if (!rootRef.value.contains(e.target as Node)) open.value = false
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') open.value = false
}

onMounted(() => {
  document.addEventListener('mousedown', onDocMouseDown)
  document.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => {
  document.removeEventListener('mousedown', onDocMouseDown)
  document.removeEventListener('keydown', onKey)
})

function toggleOpen() {
  open.value = !open.value
  if (open.value) syncVisibleFromModel()
}
</script>

<template>
  <div ref="rootRef" class="report-date">
    <span class="report-date__label">{{ label }}</span>
    <button
      type="button"
      class="report-date__trigger"
      :aria-expanded="open"
      aria-haspopup="dialog"
      :aria-label="`${label}, ${displayLabel}`"
      @click="toggleOpen"
    >
      <span class="report-date__value numeric">{{ displayLabel }}</span>
      <Icon name="calendar-days" :size="18" class="report-date__icon" />
    </button>
    <p class="report-date__hint">미래 날짜는 선택할 수 없습니다 · 기준: 한국시간</p>

    <Transition name="report-date-pop">
      <div
        v-if="open"
        class="report-date__popover"
        role="dialog"
        aria-modal="true"
        :aria-label="`${monthTitle} 달력`"
      >
        <div class="report-date__head">
          <button
            type="button"
            class="report-date__nav"
            aria-label="이전 달"
            @click="prevMonth"
          >
            <Icon name="chevron-left" :size="20" />
          </button>
          <strong class="report-date__month">{{ monthTitle }}</strong>
          <button
            type="button"
            class="report-date__nav"
            :disabled="!canNextMonth"
            aria-label="다음 달"
            @click="nextMonth"
          >
            <Icon name="chevron-right" :size="20" />
          </button>
        </div>

        <div class="report-date__weekdays">
          <span v-for="w in weekdayLabels" :key="w" class="report-date__wd">{{ w }}</span>
        </div>

        <div class="report-date__grid">
          <template v-for="(cell, i) in gridCells" :key="i">
            <div v-if="cell.key === null" class="report-date__cell report-date__cell--pad" />
            <button
              v-else
              type="button"
              class="report-date__cell"
              :class="{
                'report-date__cell--muted': isDisabled(cell.key),
                'report-date__cell--selected': cell.key === modelValue,
                'report-date__cell--today': cell.key === todayKey && cell.key !== modelValue,
              }"
              :disabled="isDisabled(cell.key)"
              @click="selectDay(cell.key!)"
            >
              {{ cell.day }}
            </button>
          </template>
        </div>

        <div class="report-date__footer">
          <button type="button" class="report-date__today" @click="goToday">
            오늘로 이동
          </button>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.report-date {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  min-width: 0;
}

.report-date__label {
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-secondary);
}

.report-date__trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  width: 100%;
  min-height: 40px;
  padding: 9px 12px;
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  cursor: pointer;
  text-align: left;
  transition:
    border-color var(--motion-base) var(--motion-ease),
    box-shadow var(--motion-base) var(--motion-ease);
}
.report-date__trigger:hover {
  border-color: var(--color-text-muted);
}
.report-date__trigger:focus-visible {
  outline: none;
  border-color: var(--color-brand-primary);
  box-shadow: var(--focus-ring);
}

.report-date__value {
  font-size: var(--font-size-sm);
  color: var(--color-text-primary);
  font-weight: var(--font-weight-medium);
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.report-date__icon {
  flex-shrink: 0;
  color: var(--color-text-muted);
}

.report-date__hint {
  margin: 0;
  font-size: 11px;
  color: var(--color-text-muted);
  line-height: 1.35;
}

.report-date__popover {
  position: absolute;
  z-index: 40;
  top: calc(100% + 6px);
  left: 0;
  width: min(100%, 300px);
  min-width: 260px;
  padding: var(--space-4);
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
}

.report-date-pop-enter-active,
.report-date-pop-leave-active {
  transition:
    opacity var(--motion-base) var(--motion-ease),
    transform var(--motion-base) var(--motion-ease);
}
.report-date-pop-enter-from,
.report-date-pop-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}

.report-date__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}

.report-date__month {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}

.report-date__nav {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: none;
  border-radius: var(--radius-md);
  background: var(--color-surface-sunken);
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: background var(--motion-base) var(--motion-ease), color var(--motion-base) var(--motion-ease);
}
.report-date__nav:hover:not(:disabled) {
  background: var(--color-brand-primary-soft);
  color: var(--color-brand-primary);
}
.report-date__nav:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.report-date__weekdays {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 2px;
  margin-bottom: var(--space-2);
  text-align: center;
}

.report-date__wd {
  font-size: 11px;
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-muted);
  padding: 4px 0;
}
.report-date__wd:first-child {
  color: var(--color-status-danger);
}
.report-date__wd:last-child {
  color: var(--color-status-info);
}

.report-date__grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 4px;
}

.report-date__cell {
  aspect-ratio: 1;
  max-height: 40px;
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-primary);
  cursor: pointer;
  transition:
    background var(--motion-fast) var(--motion-ease),
    color var(--motion-fast) var(--motion-ease),
    transform 0.1s var(--motion-ease);
}
.report-date__cell:hover:not(:disabled) {
  background: var(--color-surface-sunken);
  transform: scale(1.04);
}
.report-date__cell--pad {
  pointer-events: none;
}
.report-date__cell--muted,
.report-date__cell:disabled {
  opacity: 0.32;
  cursor: not-allowed;
  transform: none;
}
.report-date__cell--today:not(:disabled) {
  box-shadow: inset 0 0 0 2px var(--color-brand-primary);
  color: var(--color-brand-primary);
}
.report-date__cell--selected {
  background: var(--color-brand-primary) !important;
  color: #fff !important;
  font-weight: var(--font-weight-semibold);
  box-shadow: none;
  transform: none;
}
.report-date__cell--selected:hover:not(:disabled) {
  background: var(--color-brand-primary-hover) !important;
}

.report-date__footer {
  margin-top: var(--space-4);
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-border-subtle);
  display: flex;
  justify-content: center;
}

.report-date__today {
  border: none;
  background: transparent;
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-semibold);
  color: var(--color-brand-primary);
  cursor: pointer;
  padding: 6px 12px;
  border-radius: var(--radius-full);
  transition: background var(--motion-base) var(--motion-ease);
}
.report-date__today:hover {
  background: var(--color-brand-primary-soft);
}
</style>
