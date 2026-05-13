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
import BaseAvatar from '@/components/common/BaseAvatar.vue'
import Icon from '@/components/common/Icon.vue'

const today = localDateKey()
const records = ref<AttendanceRecord[]>([])
const menu = ref<MenuEntry | null>(null)
const pendingReports = ref<Report[]>([])
const schedule = ref<Record<string, string>>({})
const loading = ref(true)

// Lunch image state
const lunchImageUrl = ref<string | null>(null)
const lunchImageLoading = ref(false)
const lunchImageError = ref(false)

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

// TheMealDB — 무료, API key 불필요, CORS allow-all.
// `Korean` 영역은 데이터가 0개라 동아시아 4개 영역을 풀링한 뒤 오늘 일자(day-of-year)
// 기준으로 한 장을 결정적으로 고른다. 같은 날엔 새로고침해도 같은 사진, 일자가 바뀌면
// 다른 음식. 풀 크기 ~90개로 한 학년 안에서 ~2회 반복.
const MEALDB_AREAS = ['Japanese', 'Chinese', 'Thai', 'Vietnamese']
const MEALDB_FILTER = (area: string) =>
  `https://www.themealdb.com/api/json/v1/1/filter.php?a=${encodeURIComponent(area)}`

interface MealDBMeal {
  idMeal: string
  strMeal: string
  strMealThumb: string
}

async function loadLunchImage(menuItems: string[]) {
  if (!menuItems.length) return
  lunchImageLoading.value = true
  lunchImageError.value = false

  try {
    const responses = await Promise.all(
      MEALDB_AREAS.map((a) =>
        fetch(MEALDB_FILTER(a))
          .then((r) => (r.ok ? r.json() : { meals: null }))
          .catch(() => ({ meals: null })),
      ),
    )
    const pool: MealDBMeal[] = responses
      .flatMap((body: { meals: MealDBMeal[] | null }) => body.meals ?? [])
      // idMeal 로 정렬해 매 호출 순서가 같도록 — day-of-year 인덱싱의 안정성 보장.
      .sort((a, b) => a.idMeal.localeCompare(b.idMeal))
    if (!pool.length) throw new Error('Empty meal pool')

    const dayOfYear = Math.floor(
      (Date.now() - new Date(new Date().getFullYear(), 0, 0).getTime()) / 86_400_000,
    )
    lunchImageUrl.value = pool[dayOfYear % pool.length].strMealThumb
  } catch (e) {
    console.warn('[LunchImage] CDN fetch failed:', e)
    lunchImageError.value = true
    lunchImageUrl.value = null
  } finally {
    lunchImageLoading.value = false
  }
}

onMounted(async () => {
  try {
    const [att, m, reps, s] = await Promise.all([
      api.get<AttendanceRecord[]>(`/api/attendance?date=${today}`),
      api.get<MenuEntry>(`/api/menu?date=${today}`),
      api.get<Report[]>(`/api/reports?date=${today}&status=pending`),
      api.get<Record<string, string>>('/api/schedule').catch(() => ({})),
    ])
    records.value = att
    menu.value = m
    pendingReports.value = reps
    schedule.value = s

    // Load lunch image after menu is available
    if (m && m.items.length) {
      await loadLunchImage(m.items)
    }
  } finally {
    loading.value = false
  }
})

const CUTE_COLORS = [
  '#FF6B6B', // Red
  '#FF922B', // Orange
  '#FCC419', // Yellow
  '#51CF66', // Green
  '#339AF0', // Blue
  '#5C7CFA', // Indigo
  '#BE4BDB', // Violet
]

function getCuteColor(index: number) {
  return CUTE_COLORS[index % CUTE_COLORS.length]
}

/** 해당 일 보고서 미작성 원아 — 출결 명단과 조인해 표시 이름 확보 (일과 보고서 「대기」와 동일 기준) */
const pendingReportCards = computed(() =>
  [...pendingReports.value]
    .map((r) => {
      const rec = records.value.find((x) => x.child_id === r.child_id)
      return {
        report: r,
        childName: rec?.child_name?.trim() || `원아 #${r.child_id}`,
      }
    })
    .sort((a, b) => a.childName.localeCompare(b.childName, 'ko')),
)
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

    <BaseCard class="grid-card grid-card--attendance" :padded="true">
      <template #header>
        <div class="grid-card__head">
          <Icon name="users-round" :size="16" />
          <span>반 명단</span>
        </div>
      </template>
      <AttendanceGrid v-if="records.length" :records="records" />
      <BaseEmptyState
        v-else
        icon="users-round"
        title="오늘 등록된 어린이가 없습니다"
        description="어린이를 등록하면 여기서 출결 현황을 확인할 수 있어요."
      />
    </BaseCard>

    <div class="bottom">
      <BaseCard :padded="true" class="grid-card--lunch">
        <template #header>
          <div class="bottom__head"><Icon name="utensils" :size="16" /><span>오늘 점심</span></div>
        </template>
        <div v-if="menu && menu.items.length" class="cute-container">
          <div class="lunch-hero">
            <div v-if="lunchImageLoading" class="lunch-hero__skeleton">
              <div class="lunch-hero__spinner"></div>
              <span class="lunch-hero__spinner-text">음식 사진 불러오는 중…</span>
            </div>
            <img
              v-else-if="lunchImageUrl"
              :src="lunchImageUrl"
              alt="오늘 점심 사진"
              class="lunch-hero__img"
              loading="lazy"
            />
            <div v-else-if="lunchImageError" class="lunch-hero__skeleton">
              <span class="lunch-hero__spinner-text">사진을 불러오지 못했어요</span>
            </div>
          </div>
          <div class="cute-list">
            <div v-for="(item, index) in menu.items" :key="index" class="cute-tag" :style="`--tag-color: ${getCuteColor(index)}`">
              {{ item }}
            </div>
          </div>
        </div>
        <p class="bottom__value" v-else>미등록</p>
      </BaseCard>
      <BaseCard :padded="true" class="grid-card--schedule">
        <template #header>
          <div class="bottom__head"><Icon name="calendar" :size="16" /><span>일과표</span></div>
        </template>
        <div class="cute-container">
          <div class="cute-schedule">
            <div v-for="(activity, time, index) in schedule" :key="time" class="cute-activity" :style="`--item-color: ${getCuteColor(index)}`">
              <div class="cute-index">{{ index + 1 }}</div>
              <div class="cute-content">
                <span class="cute-time numeric">{{ time }}</span>
                <span class="cute-text">{{ activity }}</span>
              </div>
            </div>
          </div>
        </div>
      </BaseCard>
      <BaseCard :padded="true" class="grid-card--reports">
        <template #header>
          <div class="bottom__head bottom__head--reports">
            <span class="bottom__head-start">
              <Icon name="file-text" :size="16" />
              <span>미작성 보고서</span>
            </span>
            <span
              v-if="pendingReports.length"
              class="pending-count"
              aria-label="미작성 건수"
            >
              <span class="numeric">{{ pendingReports.length }}</span>
            </span>
          </div>
        </template>
        <div
          class="cute-container"
          :class="{ 'cute-container--reports-pending': pendingReports.length > 0 }"
        >
          <template v-if="pendingReports.length">
            <p class="pending-lead">오늘 날짜로 보고서가 아직 없는 어린이예요. 탭하면 작성 화면으로 이동해요.</p>
            <div class="pending-grid" role="list">
              <RouterLink
                v-for="(row, index) in pendingReportCards"
                :key="row.report.child_id"
                class="pending-card"
                role="listitem"
                :style="{ '--accent': getCuteColor(index) }"
                :to="{
                  path: '/teacher/reports',
                  query: { child: String(row.report.child_id), date: today },
                }"
              >
                <BaseAvatar class="pending-card__avatar" :name="row.childName" :size="40" />
                <span class="pending-card__name">{{ row.childName }}</span>
                <Icon name="pen-line" :size="16" class="pending-card__icon" />
              </RouterLink>
            </div>
          </template>
          <div v-else class="pending-zero">
            <p class="bottom__value bottom__value--zero">
              <span class="numeric">0</span><span class="bottom__unit">건</span>
            </p>
            <p class="pending-zero__hint">오늘은 미작성이 없어요</p>
          </div>
        </div>
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

.bottom { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--space-3); align-items: stretch; }
.bottom__head { display: flex; align-items: center; gap: var(--space-2); color: var(--color-text-secondary); font-size: var(--font-size-sm); font-weight: var(--font-weight-bold); }
.bottom__head span { font-weight: var(--font-weight-bold); }
.bottom__head--reports {
  justify-content: space-between;
  width: 100%;
  gap: var(--space-3);
}
.bottom__head-start {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
}
.pending-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 28px;
  height: 28px;
  padding: 0 9px;
  border-radius: var(--radius-full);
  background: color-mix(in srgb, var(--color-status-danger), transparent 86%);
  color: var(--color-status-danger);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-bold);
}
.bottom__value { font-size: var(--font-size-lg); font-weight: var(--font-weight-semibold); color: var(--color-text-primary); margin: 0; }
.bottom__value--zero { color: var(--color-text-muted); }
.bottom__unit { font-size: var(--font-size-sm); color: var(--color-text-muted); margin-left: 2px; }

.grid-card--attendance,
.grid-card--lunch,
.grid-card--schedule,
.grid-card--reports {
  position: relative;
  overflow: hidden;
  background-image: 
    radial-gradient(circle at 2px 2px, rgba(255, 255, 255, 0.05) 1px, transparent 0);
  background-size: 24px 24px;
}

.grid-card--attendance::after,
.grid-card--lunch::after,
.grid-card--schedule::after,
.grid-card--reports::after {
  position: absolute;
  bottom: -20px;
  right: -20px;
  font-size: 140px;
  opacity: 0.12;
  transform: rotate(-15deg);
  pointer-events: none;
}

.grid-card--attendance::after { content: '🎒'; }
.grid-card--lunch::after      { content: '🍱'; }
.grid-card--schedule::after   { content: '⏰'; }
.grid-card--reports::after    { content: '📝'; }

.grid-card--lunch :deep(.card__body),
.grid-card--schedule :deep(.card__body) {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.grid-card--reports :deep(.card__body) {
  flex: 0 1 auto;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.cute-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  justify-content: center;
  align-items: center;
}

.lunch-hero {
  width: 100%;
  margin-bottom: var(--space-4);
  border-radius: var(--radius-lg);
  overflow: hidden;
  box-shadow: var(--shadow-sm);
  border: 1px solid var(--color-border-subtle);
  /* Responsive: use aspect-ratio so image scales with card width */
  aspect-ratio: 16 / 9;
  position: relative;
}
.lunch-hero__img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.lunch-hero__skeleton {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, var(--color-surface-sunken) 0%, var(--color-surface-elevated) 100%);
  gap: var(--space-3);
}
.lunch-hero__spinner {
  width: 36px;
  height: 36px;
  border: 3px solid var(--color-border-subtle);
  border-top-color: var(--color-primary, #5C7CFA);
  border-radius: 50%;
  animation: spin 0.9s linear infinite;
}
.lunch-hero__spinner-text {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  letter-spacing: 0.02em;
}
@keyframes spin { to { transform: rotate(360deg); } }

.cute-icon-hero {
  display: none;
}

.cute-list {
  display: flex;
  flex-direction: column;
  gap: 20px;
  width: 100%;
  padding-bottom: 20px;
}
.cute-tag {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 8px 18px;
  min-height: 44px;
  border-radius: var(--radius-full);
  background: color-mix(in srgb, var(--tag-color), transparent 82%);
  border: 2px solid var(--tag-color);
  color: var(--color-text-primary);
  font-weight: var(--font-weight-bold);
  font-size: var(--font-size-md);
  text-align: center;
  transition: all 0.2s ease;
  box-shadow: 0 4px 8px rgba(0, 0, 0, 0.08);
}

.cute-schedule {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 100%;
}
.cute-activity {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  border-radius: var(--radius-lg);
  background: var(--color-surface-sunken);
  border-left: 5px solid var(--item-color);
  transition: transform 0.2s;
  font-weight: var(--font-weight-bold);
}
.cute-activity:hover {
  transform: translateX(4px);
}
.cute-index {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: var(--item-color);
  color: white;
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-bold);
  flex-shrink: 0;
}
.cute-content {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.cute-time {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  font-weight: var(--font-weight-medium);
}
.cute-text {
  font-size: var(--font-size-sm);
  color: var(--color-text-primary);
  font-weight: var(--font-weight-bold);
  background: rgba(255, 255, 255, 0.08);
  padding: 4px 14px;
  border-radius: var(--radius-full);
  display: inline-block;
  margin-top: 2px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}

.cute-container--reports-pending {
  height: auto;
  align-items: stretch;
  justify-content: flex-start;
  width: 100%;
  min-width: 0;
  padding-top: var(--space-1);
}
.pending-lead {
  margin: 0 0 var(--space-3);
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  line-height: 1.5;
  text-align: center;
}
.pending-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 8.5rem), 1fr));
  gap: 8px;
  width: 100%;
  min-width: 0;
  padding-bottom: var(--space-2);
}
.pending-card {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  min-width: 0;
  border-radius: var(--radius-lg);
  text-decoration: none;
  color: inherit;
  background: linear-gradient(
    135deg,
    color-mix(in srgb, var(--accent), var(--color-surface-raised) 88%) 0%,
    var(--color-surface-raised) 100%
  );
  border: 1.5px solid color-mix(in srgb, var(--accent), transparent 50%);
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.06);
  transition: transform 0.18s var(--motion-ease, ease), box-shadow 0.18s var(--motion-ease, ease);
}
.pending-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 16px color-mix(in srgb, var(--accent), transparent 75%);
}
.pending-card:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.pending-card__name {
  flex: 1;
  min-width: 0;
  font-weight: var(--font-weight-semibold);
  font-size: var(--font-size-sm);
  color: var(--color-text-primary);
  letter-spacing: -0.01em;
}
.pending-card__icon {
  color: var(--accent);
  flex-shrink: 0;
  opacity: 0.85;
}
.pending-zero {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
}
.pending-zero__hint {
  margin: 0;
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}

@media (max-width: 1100px) {
  .bottom {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .grid-card--reports {
    grid-column: 1 / -1;
  }
}

@media (max-width: 720px) {
  .kpis {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .bottom {
    grid-template-columns: minmax(0, 1fr);
  }
  .grid-card--reports {
    grid-column: auto;
  }
  .pending-grid {
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 7.5rem), 1fr));
  }
}
</style>
