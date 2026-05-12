<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { api } from '@/api/client'
import { localDateKey } from '@/lib/date'
import type { Child, Photo, Report } from '@/types'
import ReportEditor from '@/components/teacher/ReportEditor.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import BaseCard from '@/components/common/BaseCard.vue'
import BaseSelect from '@/components/common/BaseSelect.vue'
import BaseInput from '@/components/common/BaseInput.vue'
import BaseEmptyState from '@/components/common/BaseEmptyState.vue'
import BaseAvatar from '@/components/common/BaseAvatar.vue'
import BaseBadge from '@/components/common/BaseBadge.vue'
import Icon from '@/components/common/Icon.vue'

const today = localDateKey()
const children = ref<Child[]>([])
const className = ref<string>('')
const date = ref(today)
// child_id → 그날의 Report (null 이면 미작성)
const reports = ref<Map<number, Report | null>>(new Map())
// child_id → 그날의 자연 촬영 사진 (lazy — 선택된 자녀만 fetch)
const photos = ref<Map<number, Photo[]>>(new Map())
const selectedChildId = ref<number | null>(null)
const loading = ref(false)
const photosLoading = ref(false)
const error = ref<string | null>(null)
const generating = ref<Set<number>>(new Set())
const generateError = ref<Map<number, string>>(new Map())

const classNames = computed(() => {
  const set = new Set(children.value.map((c) => c.class_name))
  return [...set].sort()
})

const filtered = computed(() =>
  children.value
    .filter((c) => !className.value || c.class_name === className.value)
    .sort((a, b) => a.name.localeCompare(b.name)),
)

const selectedChild = computed(() =>
  filtered.value.find((c) => c.id === selectedChildId.value) ?? null,
)
const selectedReport = computed(() =>
  selectedChildId.value !== null ? reports.value.get(selectedChildId.value) ?? null : null,
)
const selectedPhotos = computed(() =>
  selectedChildId.value !== null ? photos.value.get(selectedChildId.value) ?? [] : [],
)

// 사진 ID → Photo 매핑 — 타임라인 이벤트가 photo_id 로 참조할 때 빠른 lookup.
const selectedPhotosById = computed(() => {
  const map = new Map<number, Photo>()
  for (const p of selectedPhotos.value) map.set(p.id, p)
  return map
})

interface ReportEvent {
  time: string // "HH:MM"
  photo_id: number | null
  text: string
}
interface ReportTimeline {
  events: ReportEvent[]
  summary: string
}

// 보고서 본문을 JSON 으로 파싱. 실패 시 (legacy 평문) summary 에 담아 events 는 비움.
const parsedReport = computed<ReportTimeline | null>(() => {
  const r = selectedReport.value
  if (!r) return null
  try {
    const obj = JSON.parse(r.content)
    if (obj && Array.isArray(obj.events)) {
      return {
        events: obj.events as ReportEvent[],
        summary: typeof obj.summary === 'string' ? obj.summary : '',
      }
    }
  } catch {
    // 평문 보고서는 summary 만 채워 표시.
  }
  return { events: [], summary: r.content }
})

onMounted(async () => {
  children.value = await api.get<Child[]>('/api/children')
  if (classNames.value.length) className.value = classNames.value[0]
})

// 반/날짜 바뀌면 보고서 목록만 일괄 fetch (사진은 선택 시 lazy).
watch([filtered, date], async () => {
  if (!filtered.value.length) {
    reports.value = new Map()
    photos.value = new Map()
    selectedChildId.value = null
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
    photos.value = new Map() // 날짜 바뀜 — 사진 캐시 무효화
    // 기존 선택이 새 목록에 없으면 첫 자녀 자동 선택 (빈 디테일 패널 방지).
    if (!filtered.value.find((c) => c.id === selectedChildId.value)) {
      selectedChildId.value = filtered.value[0]?.id ?? null
    }
  } catch {
    error.value = '보고서를 불러올 수 없습니다.'
  } finally {
    loading.value = false
  }
}, { immediate: true })

// 자녀 선택 → 그날의 사진 lazy fetch (캐시 있으면 skip).
watch(selectedChildId, async (id) => {
  if (id === null || photos.value.has(id)) return
  photosLoading.value = true
  try {
    const list = await api.get<Photo[]>(`/api/children/${id}/photos?date=${date.value}`)
    photos.value.set(id, list)
  } catch {
    // 조회 실패는 디테일 패널 안의 "사진 없음" 으로 자연스럽게 표시됨.
    photos.value.set(id, [])
  } finally {
    photosLoading.value = false
  }
})

function select(child: Child) {
  selectedChildId.value = child.id
}

function onSaved(updated: Report) {
  reports.value.set(updated.child_id, updated)
}

async function generate(childId: number) {
  if (generating.value.has(childId)) return
  generating.value.add(childId)
  generateError.value.delete(childId)
  try {
    const created = await api.post<Report>('/api/reports/generate', {
      child_id: childId,
      date: date.value,
    })
    reports.value.set(childId, created)
    // 생성 트리거가 미분류 사진을 back-fill 했을 수 있으므로 사진도 재조회.
    const list = await api.get<Photo[]>(`/api/children/${childId}/photos?date=${date.value}`)
    photos.value.set(childId, list)
  } catch {
    generateError.value.set(childId, '보고서 생성 실패 — 잠시 후 다시 시도해 주세요.')
  } finally {
    generating.value.delete(childId)
  }
}

// ─── 표시 헬퍼 ───────────────────────────────────────────────────────────

function timeLabel(takenAt: string): string {
  return new Date(takenAt).toLocaleTimeString('ko-KR', {
    timeZone: 'Asia/Seoul',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

function emotionLabel(emotion: string | null): string {
  if (emotion === 'happy') return '😀 활짝'
  if (emotion === 'sad') return '😢 시무룩'
  return emotion ?? '·'
}

</script>

<template>
  <section>
    <PageHeader title="일과 보고서" description="반과 날짜를 선택하고, 왼쪽 목록에서 어린이를 클릭하면 그날의 표정 타임라인과 보고서가 표시됩니다." />

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

    <div v-else class="layout">
      <BaseCard class="list" :padded="false">
        <template #header>
          <div class="list-head"><Icon name="users-round" :size="16" /><span>어린이 목록</span></div>
        </template>
        <ul class="ul">
          <li
            v-for="c in filtered"
            :key="c.id"
            :class="{ 'is-active': c.id === selectedChildId }"
            @click="select(c)"
          >
            <BaseAvatar :name="c.name" :src="c.photo_url ?? null" :size="36" />
            <div class="meta">
              <strong>{{ c.name }}</strong>
              <span>{{ c.class_name }}</span>
            </div>
            <BaseBadge :variant="reports.get(c.id) ? 'success' : 'neutral'" size="sm">
              {{ reports.get(c.id) ? '작성됨' : '대기' }}
            </BaseBadge>
          </li>
        </ul>
      </BaseCard>

      <BaseCard class="detail" :padded="true">
        <BaseEmptyState
          v-if="!selectedChild"
          icon="user-round"
          title="어린이를 선택하세요"
          description="왼쪽 목록에서 보고서를 볼 어린이를 선택합니다."
        />
        <div v-else class="detail__body">
          <header class="detail__head">
            <BaseAvatar :name="selectedChild.name" :src="selectedChild.photo_url ?? null" :size="56" />
            <div>
              <h2 class="detail__name">{{ selectedChild.name }}</h2>
              <p class="detail__sub">{{ selectedChild.class_name }} · {{ date }}</p>
            </div>
            <BaseBadge :variant="selectedReport ? 'success' : 'neutral'" size="md">
              {{ selectedReport ? '보고서 작성됨' : '보고서 대기' }}
            </BaseBadge>
          </header>

          <section class="block">
            <h3><Icon name="clock" :size="14" /> 오늘의 일과 타임라인</h3>

            <!-- 보고서 없음 → 빈 상태 + 생성 버튼 -->
            <template v-if="!selectedReport">
              <p v-if="photosLoading" class="muted small">사진 불러오는 중...</p>
              <div v-else class="timeline-empty">
                아직 작성된 보고서가 없습니다. 아래 버튼을 눌러 생성하세요.
                <p v-if="selectedPhotos.length > 0" class="muted small">
                  (오늘 자연 촬영 사진 {{ selectedPhotos.length }}장 발견됨)
                </p>
              </div>
            </template>

            <!-- 보고서 있음 → 타임라인 + 요약 -->
            <template v-else>
              <ol v-if="parsedReport && parsedReport.events.length > 0" class="timeline">
                <li
                  v-for="(ev, i) in parsedReport.events"
                  :key="`${ev.time}-${i}`"
                  class="timeline__entry"
                  :class="[
                    ev.photo_id ? `timeline__entry--${selectedPhotosById.get(ev.photo_id)?.emotion ?? 'unknown'}` : 'timeline__entry--note',
                  ]"
                >
                  <div class="timeline__time">{{ ev.time }}</div>
                  <div class="timeline__rail">
                    <span class="timeline__dot" />
                  </div>
                  <div class="timeline__card" :class="{ 'timeline__card--text': !ev.photo_id }">
                    <template v-if="ev.photo_id && selectedPhotosById.has(ev.photo_id)">
                      <a
                        :href="selectedPhotosById.get(ev.photo_id)!.url"
                        target="_blank"
                        rel="noopener"
                        class="timeline__thumb-link"
                      >
                        <img
                          :src="selectedPhotosById.get(ev.photo_id)!.url"
                          :alt="emotionLabel(selectedPhotosById.get(ev.photo_id)!.emotion)"
                          class="timeline__thumb"
                          loading="lazy"
                        />
                      </a>
                      <div class="timeline__body">
                        <p class="timeline__text">{{ ev.text }}</p>
                        <div class="timeline__meta">
                          <span class="timeline__emotion">{{ emotionLabel(selectedPhotosById.get(ev.photo_id)!.emotion) }}</span>
                          <span v-if="selectedPhotosById.get(ev.photo_id)!.mode" class="timeline__mode">
                            {{ selectedPhotosById.get(ev.photo_id)!.mode }}
                          </span>
                          <span class="timeline__score">
                            강도 {{ ((selectedPhotosById.get(ev.photo_id)!.emotion_score ?? 0) * 100).toFixed(0) }}%
                          </span>
                        </div>
                      </div>
                    </template>
                    <template v-else>
                      <p class="timeline__text">{{ ev.text }}</p>
                    </template>
                  </div>
                </li>
              </ol>

              <!-- legacy 평문 보고서 (events 없음) — content 전체를 한 블록으로. -->
              <div v-else-if="parsedReport && parsedReport.summary" class="legacy-report">
                {{ parsedReport.summary }}
              </div>

              <!-- 하루 정리 -->
              <p v-if="parsedReport && parsedReport.events.length > 0 && parsedReport.summary" class="summary">
                {{ parsedReport.summary }}
              </p>
            </template>

            <div class="actions">
              <button
                type="button"
                class="generate-btn"
                :disabled="generating.has(selectedChild.id)"
                @click="generate(selectedChild.id)"
              >
                <template v-if="generating.has(selectedChild.id)">
                  AI 가 작성 중…
                </template>
                <template v-else-if="selectedReport">
                  🔁 AI 로 다시 생성
                </template>
                <template v-else>
                  ✨ AI 로 보고서 생성
                </template>
              </button>
              <span v-if="generateError.get(selectedChild.id)" class="err">
                {{ generateError.get(selectedChild.id) }}
              </span>
            </div>
          </section>

          <!-- 원본 편집 (raw JSON / 평문) — 접어둠. 필요 시 펼쳐서 직접 수정 가능. -->
          <details v-if="selectedReport" class="raw-edit">
            <summary>본문 직접 편집 (개발자용)</summary>
            <ReportEditor :report="selectedReport" @saved="onSaved" />
          </details>
        </div>
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
.muted { color: var(--color-text-muted); }
.muted.small { font-size: var(--font-size-sm); padding: var(--space-2) 0; }

.layout {
  display: grid;
  grid-template-columns: minmax(260px, 320px) 1fr;
  gap: var(--space-4);
  align-items: start;
}

/* ── 좌측 목록 ───────────────────────────────────────────── */
.list-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-secondary);
  padding: var(--space-3) var(--space-4);
}
.ul {
  list-style: none;
  padding: 0;
  margin: 0;
  max-height: 70vh;
  overflow-y: auto;
}
.ul li {
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  cursor: pointer;
  border-top: 1px solid var(--color-border-subtle);
  transition: background var(--motion-base) var(--motion-ease);
}
.ul li:hover { background: var(--color-surface-sunken); }
.ul li.is-active { background: var(--color-brand-primary-soft); }
.ul li .meta {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.ul li .meta strong {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}
.ul li .meta span {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}

/* ── 우측 디테일 ─────────────────────────────────────────── */
.detail__body {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}
.detail__head {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
.detail__head h2 {
  margin: 0;
  font-size: var(--font-size-xl);
  font-weight: var(--font-weight-semibold);
}
.detail__head p {
  margin: 0;
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
.detail__name { line-height: 1.1; }
.detail__sub { margin-top: 2px; }

.block {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.block h3 {
  margin: 0;
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-secondary);
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.timeline-empty {
  padding: var(--space-4);
  background: var(--color-surface-sunken);
  border-radius: var(--radius-md);
  color: var(--color-text-muted);
  text-align: center;
  font-size: var(--font-size-sm);
}

/* ── Vertical timeline ──────────────────────────────────── */
.timeline {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
}
.timeline__entry {
  display: grid;
  grid-template-columns: 56px 24px 1fr;
  align-items: stretch;
  gap: var(--space-3);
  min-height: 96px;
}
.timeline__time {
  padding-top: 18px;
  font-variant-numeric: tabular-nums;
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-muted);
  text-align: right;
  font-size: var(--font-size-sm);
}
.timeline__rail {
  position: relative;
  display: flex;
  justify-content: center;
}
.timeline__rail::before {
  content: '';
  position: absolute;
  left: 50%;
  top: 0;
  bottom: 0;
  width: 2px;
  background: var(--color-border-subtle);
  transform: translateX(-50%);
}
/* 첫·끝 항목의 레일은 dot 까지만 그려 깔끔하게 마감 */
.timeline__entry:first-child .timeline__rail::before { top: 26px; }
.timeline__entry:last-child .timeline__rail::before { bottom: calc(100% - 32px); }
.timeline__dot {
  position: relative;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--color-text-muted);
  margin-top: 22px;
  border: 3px solid var(--color-surface-base);
  box-shadow: 0 0 0 1px var(--color-border-subtle);
  z-index: 1;
}
.timeline__entry--happy .timeline__dot { background: #f59e0b; }
.timeline__entry--sad .timeline__dot { background: #6b7280; }
.timeline__entry--note .timeline__dot {
  background: var(--color-surface-base);
  border-color: var(--color-border-strong);
}
.timeline__card {
  display: flex;
  gap: var(--space-3);
  padding: var(--space-3);
  margin: var(--space-2) 0;
  background: var(--color-surface-base);
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-md);
  color: inherit;
}
.timeline__card--text {
  background: var(--color-surface-sunken);
  border-style: dashed;
}
.timeline__thumb-link {
  display: block;
  flex-shrink: 0;
  text-decoration: none;
  transition: transform var(--motion-base) var(--motion-ease);
}
.timeline__thumb-link:hover { transform: scale(1.02); }
.timeline__thumb {
  width: 96px;
  height: 96px;
  object-fit: cover;
  border-radius: var(--radius-sm);
  background: var(--color-surface-sunken);
  display: block;
}
.timeline__body {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: var(--space-1);
  min-width: 0;
}
.timeline__text {
  margin: 0;
  font-size: var(--font-size-sm);
  line-height: 1.5;
  color: var(--color-text-primary);
}
.timeline__emotion {
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-secondary);
}
.timeline__meta {
  display: flex;
  gap: var(--space-2);
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  flex-wrap: wrap;
  align-items: center;
}
.timeline__mode {
  padding: 2px 8px;
  background: var(--color-surface-sunken);
  border-radius: 999px;
}
.timeline__score { font-variant-numeric: tabular-nums; }

/* 하루 정리 — 타임라인 아래 한 문장 */
.summary {
  margin: var(--space-3) 0 0;
  padding: var(--space-3);
  background: var(--color-brand-primary-soft);
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
  color: var(--color-text-primary);
  line-height: 1.5;
}

/* legacy 평문 보고서 */
.legacy-report {
  white-space: pre-wrap;
  padding: var(--space-3);
  background: var(--color-surface-sunken);
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
  line-height: 1.5;
}

/* 원본 편집 (접힘) */
.raw-edit {
  margin-top: var(--space-2);
}
.raw-edit summary {
  cursor: pointer;
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  padding: var(--space-2) 0;
  user-select: none;
}
.raw-edit summary:hover { color: var(--color-text-secondary); }
.raw-edit > :not(summary) { margin-top: var(--space-2); }

.actions {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-top: var(--space-2);
}
.generate-btn {
  background: var(--color-brand-primary);
  color: white;
  border: none;
  padding: 10px 18px;
  border-radius: 999px;
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  cursor: pointer;
  transition: opacity 0.15s, transform 0.1s;
  font-family: inherit;
}
.generate-btn:hover:not(:disabled) { transform: translateY(-1px); }
.generate-btn:disabled { opacity: 0.6; cursor: not-allowed; }
.err { font-size: var(--font-size-xs); color: var(--color-status-danger); }
</style>
