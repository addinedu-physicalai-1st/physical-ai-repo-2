<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, ApiError } from '@/api/client'
import { seoulDateKey } from '@/lib/date'
import { defaultKoreanReportName, polishReportKorean } from '@/lib/korean'
import type { Child, Photo, Report } from '@/types'
import ReportEditor from '@/components/teacher/ReportEditor.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import BaseCard from '@/components/common/BaseCard.vue'
import BaseSelect from '@/components/common/BaseSelect.vue'
import ReportDateField from '@/components/teacher/ReportDateField.vue'
import BaseEmptyState from '@/components/common/BaseEmptyState.vue'
import BaseAvatar from '@/components/common/BaseAvatar.vue'
import BaseBadge from '@/components/common/BaseBadge.vue'
import BaseTextarea from '@/components/common/BaseTextarea.vue'
import BaseButton from '@/components/common/BaseButton.vue'
import Icon from '@/components/common/Icon.vue'

const route = useRoute()

function parseIsoDateQuery(v: unknown): string | null {
  if (typeof v !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(v)) return null
  return v
}

const children = ref<Child[]>([])
const className = ref<string>('')
const date = ref(parseIsoDateQuery(route.query.date) ?? seoulDateKey())
const maxReportDate = computed(() => seoulDateKey())
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
const clearingReport = ref(false)

/** 타임라인 한 줄 인라인 편집 (JSON 이벤트의 text 만 갱신) */
const editingEventIndex = ref<number | null>(null)
const editingDraft = ref('')
const timelineSavingIndex = ref<number | null>(null)
const timelineSaveError = ref<string | null>(null)

const editingSummary = ref(false)
const summaryDraft = ref('')
const summarySaving = ref(false)
const summarySaveError = ref<string | null>(null)

const classNames = computed(() => {
  const set = new Set(children.value.map((c) => c.class_name))
  return [...set].sort()
})

const filtered = computed(() =>
  children.value
    .filter((c) => !className.value || c.class_name === className.value)
    .sort((a, b) => a.name.localeCompare(b.name)),
)

const childSelectOptions = computed(() =>
  filtered.value.map((c) => ({
    value: String(c.id),
    label: `${c.name} · ${reports.value.get(c.id) ? '작성됨' : '대기'}`,
  })),
)

const selectedChildIdStr = computed({
  get: () => (selectedChildId.value == null ? '' : String(selectedChildId.value)),
  set: (v: string) => {
    if (!v.trim()) {
      selectedChildId.value = null
      return
    }
    const n = Number(v)
    selectedChildId.value = Number.isFinite(n) ? n : null
  },
})

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
  /** 같은 세션의 사진을 한 줄로 묶을 때 클러스터의 전체 photo_id 를 시간순으로 보존.
   *  레거시 보고서(서버 변경 전)는 이 필드가 없으니 photo_id 단일로 fallback. */
  photo_ids?: number[]
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

/** 보고서 조사 후처리에 쓰는 호칭 — 서버와 동일: given_name 우선, 없으면 성 제거 추정 */
const reportAddressName = computed(() => {
  const c = selectedChild.value
  if (!c) return ''
  return (c.given_name ?? '').trim() || defaultKoreanReportName(c.name)
})

/** 화면 표시용 — es-hangul 규칙으로 이/가·은/는 등만 다듬음 (저장 본문은 그대로) */
const parsedReportDisplay = computed<ReportTimeline | null>(() => {
  const raw = parsedReport.value
  if (!raw) return null
  const addr = reportAddressName.value.trim()
  if (!addr) return raw
  const cls = (selectedChild.value?.class_name ?? '').trim()
  return {
    events: raw.events.map((ev) => ({
      ...ev,
      text: polishReportKorean(addr, ev.text, cls),
    })),
    summary: polishReportKorean(addr, raw.summary, cls),
  }
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

watch(
  () => [route.fullPath, filtered.value.map((c) => c.id).join(',')] as const,
  () => {
    if (!route.path.startsWith('/teacher/reports')) return
    if (!filtered.value.length) return
    const ds = parseIsoDateQuery(route.query.date)
    if (ds) date.value = ds
    const qc = route.query.child
    if (typeof qc !== 'string' || !/^\d+$/.test(qc)) return
    const id = Number(qc)
    if (!filtered.value.some((c) => c.id === id)) return
    selectedChildId.value = id
  },
)

watch(
  [selectedChildId, date, () => selectedReport.value?.id ?? null, () => selectedReport.value?.updated_at ?? ''],
  () => {
    cancelInlineEdits()
  },
)

// 자녀 선택 → 그날의 사진 lazy fetch (캐시 있으면 skip).
function cancelInlineEdits() {
  editingEventIndex.value = null
  editingDraft.value = ''
  timelineSaveError.value = null
  editingSummary.value = false
  summaryDraft.value = ''
  summarySaveError.value = null
}

function beginTimelineEdit(eventIndex: number) {
  const disp = parsedReportDisplay.value
  if (!disp?.events[eventIndex]) return
  editingSummary.value = false
  summaryDraft.value = ''
  summarySaveError.value = null
  editingEventIndex.value = eventIndex
  editingDraft.value = disp.events[eventIndex].text
  timelineSaveError.value = null
}

function beginSummaryEdit() {
  const disp = parsedReportDisplay.value
  if (!disp?.summary) return
  editingEventIndex.value = null
  editingDraft.value = ''
  timelineSaveError.value = null
  editingSummary.value = true
  summaryDraft.value = disp.summary
  summarySaveError.value = null
}

async function saveSummary() {
  const r = selectedReport.value
  if (!r) return
  summarySaveError.value = null
  let obj: { events: ReportEvent[]; summary?: string }
  try {
    obj = JSON.parse(r.content) as { events: ReportEvent[]; summary?: string }
  } catch {
    summarySaveError.value = '보고서 형식을 읽을 수 없습니다. 아래 JSON 편집을 이용해 주세요.'
    return
  }
  const summary = summaryDraft.value.trim()
  if (!summary) {
    summarySaveError.value = '내용을 입력해 주세요.'
    return
  }
  const newContent = JSON.stringify({
    events: Array.isArray(obj.events) ? obj.events : [],
    summary,
  })
  summarySaving.value = true
  try {
    const updated = await api.patch<Report>(`/api/reports/${r.id}`, {
      content: newContent,
    })
    onSaved(updated)
    cancelInlineEdits()
  } catch {
    summarySaveError.value = '저장에 실패했습니다. 잠시 후 다시 시도해 주세요.'
  } finally {
    summarySaving.value = false
  }
}

async function saveTimelineEvent(eventIndex: number) {
  const r = selectedReport.value
  if (!r) return
  timelineSaveError.value = null
  let obj: { events: ReportEvent[]; summary?: string }
  try {
    obj = JSON.parse(r.content) as { events: ReportEvent[]; summary?: string }
  } catch {
    timelineSaveError.value = '보고서 형식을 읽을 수 없습니다. 아래 JSON 편집을 이용해 주세요.'
    return
  }
  if (!Array.isArray(obj.events) || !obj.events[eventIndex]) {
    timelineSaveError.value = '해당 타임라인 줄을 찾을 수 없습니다.'
    return
  }
  const text = editingDraft.value.trim()
  if (!text) {
    timelineSaveError.value = '내용을 입력해 주세요.'
    return
  }
  const nextEvents = obj.events.map((ev, j) =>
    j === eventIndex ? { ...ev, text } : ev,
  )
  const newContent = JSON.stringify({
    events: nextEvents,
    summary: typeof obj.summary === 'string' ? obj.summary : '',
  })
  timelineSavingIndex.value = eventIndex
  try {
    const updated = await api.patch<Report>(`/api/reports/${r.id}`, {
      content: newContent,
    })
    onSaved(updated)
    cancelInlineEdits()
  } catch {
    timelineSaveError.value = '저장에 실패했습니다. 잠시 후 다시 시도해 주세요.'
  } finally {
    timelineSavingIndex.value = null
  }
}

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
  } catch (e) {
    const fallback = '보고서 생성 실패 — 잠시 후 다시 시도해 주세요.'
    if (e instanceof ApiError) {
      const d = e.detail?.trim()
      generateError.value.set(
        childId,
        d
          ? `${d} (HTTP ${e.status})`
          : `요청 실패 (HTTP ${e.status}). ${fallback}`,
      )
    } else {
      generateError.value.set(childId, fallback)
    }
  } finally {
    generating.value.delete(childId)
  }
}

async function clearSelectedReport() {
  const r = selectedReport.value
  const cid = selectedChildId.value
  const child = selectedChild.value
  if (!r || cid === null || !child) return
  const ok = window.confirm(
    `「${child.name}」의 ${date.value} 일과 보고서를 삭제할까요? 삭제 후에는 AI 로 다시 생성할 수 있습니다.`,
  )
  if (!ok) return
  clearingReport.value = true
  generateError.value.delete(cid)
  try {
    await api.delete(`/api/reports/${r.id}`)
    reports.value.set(cid, null)
  } catch {
    generateError.value.set(cid, '보고서 삭제에 실패했습니다. 잠시 후 다시 시도해 주세요.')
  } finally {
    clearingReport.value = false
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

/** 이벤트의 사진 목록 — `photo_ids` 배열(신규 포맷) 우선, 없으면 단일 `photo_id` 로 fallback.
 *  selectedPhotosById 에 없는 id 는 (드물게) 누락된 사진이므로 제외. */
function eventPhotos(ev: ReportEvent): Photo[] {
  const ids = ev.photo_ids ?? (ev.photo_id != null ? [ev.photo_id] : [])
  const out: Photo[] = []
  for (const id of ids) {
    const p = selectedPhotosById.value.get(id)
    if (p) out.push(p)
  }
  return out
}

/** 이벤트의 대표 감정 — entry 색 분류용. 대표는 photo_id(서버가 score 최고로 고른 것),
 *  대표가 없으면 첫 photo_ids 의 감정. */
function eventPrimaryEmotion(ev: ReportEvent): string {
  const primaryId = ev.photo_id ?? ev.photo_ids?.[0]
  if (primaryId == null) return 'unknown'
  return selectedPhotosById.value.get(primaryId)?.emotion ?? 'unknown'
}

</script>

<template>
  <section>
    <PageHeader
      title="일과 보고서"
      description="반과 날짜를 선택한 뒤 어린이를 고르면 그날의 표정 타임라인과 보고서가 표시됩니다."
    />

    <div class="filters">
      <BaseSelect
        v-model="className"
        label="반"
        :options="classNames.map(cn => ({ value: cn, label: cn }))"
      />
      <ReportDateField v-model="date" label="날짜" :max-date="maxReportDate" />
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
      <BaseSelect
        v-model="selectedChildIdStr"
        class="child-select-mobile"
        label="어린이"
        :options="childSelectOptions"
        placeholder="선택…"
      />

      <BaseCard class="list child-list-desktop" :padded="false">
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
          description="목록이나 위쪽 선택란에서 보고서를 볼 어린이를 고릅니다."
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

          <section class="block block--timeline">
            <h3 class="timeline-section-title"><Icon name="clock" :size="14" /> 오늘의 일과 타임라인</h3>

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
              <div
                v-if="parsedReportDisplay && parsedReportDisplay.events.length > 0"
                class="timeline-wrap"
              >
              <ol class="timeline">
                <li
                  v-for="(ev, i) in parsedReportDisplay.events"
                  :key="`${ev.time}-${i}`"
                  class="timeline__entry"
                  :class="[
                    eventPhotos(ev).length > 0
                      ? `timeline__entry--${eventPrimaryEmotion(ev)}`
                      : 'timeline__entry--note',
                  ]"
                >
                  <div class="timeline__time">{{ ev.time }}</div>
                  <div class="timeline__rail">
                    <span class="timeline__dot" />
                  </div>
                  <div
                    class="timeline__card"
                    :class="{
                      'timeline__card--text': eventPhotos(ev).length === 0,
                      'timeline__card--multi': eventPhotos(ev).length > 1,
                      'timeline__card--editing': editingEventIndex === i,
                    }"
                  >
                    <div
                      v-if="editingEventIndex === i"
                      class="timeline__edit"
                      @click.stop
                      @keydown.escape.prevent="cancelInlineEdits"
                    >
                      <div v-if="eventPhotos(ev).length > 0" class="timeline__strip">
                        <a
                          v-for="p in eventPhotos(ev)"
                          :key="p.id"
                          :href="p.url"
                          target="_blank"
                          rel="noopener"
                          class="timeline__thumb-link"
                          @click.stop
                        >
                          <img
                            :src="p.url"
                            :alt="emotionLabel(p.emotion)"
                            class="timeline__thumb"
                            loading="lazy"
                          />
                        </a>
                      </div>
                      <BaseTextarea
                        v-model="editingDraft"
                        :rows="eventPhotos(ev).length > 0 ? 3 : 4"
                        :disabled="timelineSavingIndex === i"
                        autofocus
                        hint="저장하면 이 시간대 문장만 바뀝니다. Esc 로 취소."
                      />
                      <div class="timeline__edit-actions">
                        <BaseButton
                          variant="ghost"
                          size="sm"
                          :disabled="timelineSavingIndex === i"
                          @click="cancelInlineEdits"
                        >
                          취소
                        </BaseButton>
                        <BaseButton
                          variant="primary"
                          size="sm"
                          icon-start="save"
                          :loading="timelineSavingIndex === i"
                          @click="saveTimelineEvent(i)"
                        >
                          저장
                        </BaseButton>
                      </div>
                      <p v-if="timelineSaveError" class="timeline__edit-err">{{ timelineSaveError }}</p>
                    </div>
                    <template v-else-if="eventPhotos(ev).length > 0">
                      <div class="timeline__strip">
                        <a
                          v-for="p in eventPhotos(ev)"
                          :key="p.id"
                          :href="p.url"
                          target="_blank"
                          rel="noopener"
                          class="timeline__thumb-link"
                          :title="`${timeLabel(p.taken_at)} · ${emotionLabel(p.emotion)}`"
                          @click.stop
                        >
                          <img
                            :src="p.url"
                            :alt="emotionLabel(p.emotion)"
                            class="timeline__thumb"
                            loading="lazy"
                          />
                          <span v-if="eventPhotos(ev).length > 1" class="timeline__thumb-time">
                            {{ timeLabel(p.taken_at) }}
                          </span>
                        </a>
                      </div>
                      <div
                        class="timeline__body timeline__body--editable"
                        role="button"
                        tabindex="0"
                        title="탭하여 이 문장 편집"
                        @click="beginTimelineEdit(i)"
                        @keydown.enter.prevent="beginTimelineEdit(i)"
                      >
                        <p class="timeline__text">{{ ev.text }}</p>
                        <div class="timeline__meta">
                          <span v-if="eventPhotos(ev).length > 1" class="timeline__count">
                            사진 {{ eventPhotos(ev).length }}장
                          </span>
                          <template v-else>
                            <span class="timeline__emotion">{{ emotionLabel(eventPhotos(ev)[0].emotion) }}</span>
                            <span v-if="eventPhotos(ev)[0].mode" class="timeline__mode">
                              {{ eventPhotos(ev)[0].mode }}
                            </span>
                            <span class="timeline__score">
                              강도 {{ ((eventPhotos(ev)[0].emotion_score ?? 0) * 100).toFixed(0) }}%
                            </span>
                          </template>
                        </div>
                      </div>
                    </template>
                    <template v-else>
                      <button
                        type="button"
                        class="timeline__text-card"
                        title="탭하여 이 문장 편집"
                        @click="beginTimelineEdit(i)"
                      >
                        <p class="timeline__text">{{ ev.text }}</p>
                      </button>
                    </template>
                  </div>
                </li>
              </ol>
              </div>

              <!-- legacy 평문 보고서 (events 없음) — content 전체를 한 블록으로. -->
              <div v-else-if="parsedReportDisplay && parsedReportDisplay.summary" class="legacy-report">
                {{ parsedReportDisplay.summary }}
              </div>

              <!-- 하루 정리 -->
              <div
                v-if="
                  parsedReportDisplay &&
                  parsedReportDisplay.events.length > 0 &&
                  parsedReportDisplay.summary
                "
                class="summary-wrap"
              >
                <div
                  v-if="editingSummary"
                  class="summary summary--editing"
                  @keydown.escape.prevent="cancelInlineEdits"
                >
                  <BaseTextarea
                    v-model="summaryDraft"
                    :rows="5"
                    :disabled="summarySaving"
                    autofocus
                    hint="저장하면 하루 정리 문장만 바뀝니다. Esc 로 취소."
                  />
                  <div class="summary__actions">
                    <BaseButton
                      variant="ghost"
                      size="sm"
                      :disabled="summarySaving"
                      @click="cancelInlineEdits"
                    >
                      취소
                    </BaseButton>
                    <BaseButton
                      variant="primary"
                      size="sm"
                      icon-start="save"
                      :loading="summarySaving"
                      @click="saveSummary"
                    >
                      저장
                    </BaseButton>
                  </div>
                  <p v-if="summarySaveError" class="summary__err">{{ summarySaveError }}</p>
                </div>
                <button
                  v-else
                  type="button"
                  class="summary summary--clickable"
                  title="탭하여 하루 정리 편집"
                  @click="beginSummaryEdit"
                >
                  {{ parsedReportDisplay.summary }}
                </button>
              </div>
            </template>

            <div class="actions">
              <button
                type="button"
                class="generate-btn"
                :disabled="generating.has(selectedChild.id) || clearingReport"
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
              <!-- 항상 같은 자리에 둠 — 보고서 없으면 비활성(숨기지 않음) -->
              <button
                type="button"
                class="clear-btn"
                :disabled="!selectedReport || generating.has(selectedChild.id) || clearingReport"
                :title="selectedReport ? '이 날짜 보고서를 DB에서 삭제합니다' : '삭제할 보고서가 없습니다'"
                @click="clearSelectedReport"
              >
                {{ clearingReport ? '삭제 중…' : '🗑 보고서 비우기' }}
              </button>
              <span v-if="generateError.get(selectedChild.id)" class="err">
                {{ generateError.get(selectedChild.id) }}
              </span>
            </div>
          </section>

          <!-- 원본 편집 (raw JSON / 평문) — 접어둠. 필요 시 펼쳐서 직접 수정 가능. -->
          <details v-if="selectedReport" class="raw-edit">
            <summary>고급: JSON·전체 본문 직접 편집</summary>
            <ReportEditor :report="selectedReport" @saved="onSaved" />
          </details>
        </div>
      </BaseCard>
    </div>
  </section>
</template>

<style scoped>
section {
  min-width: 0;
}

.filters {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: var(--space-3);
  margin-bottom: var(--space-5);
}
.info { color: var(--color-text-muted); padding: var(--space-5) 0; }
.muted { color: var(--color-text-muted); }
.muted.small { font-size: var(--font-size-sm); padding: var(--space-2) 0; }

.child-select-mobile {
  display: none;
}

.layout {
  display: grid;
  grid-template-columns: minmax(260px, 320px) 1fr;
  gap: var(--space-4);
  align-items: start;
  min-width: 0;
}

.layout > * {
  min-width: 0;
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

.block--timeline {
  gap: var(--space-4);
}
.timeline-section-title {
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  letter-spacing: -0.02em;
}

.timeline-empty {
  padding: var(--space-4);
  background: var(--color-surface-sunken);
  border-radius: var(--radius-md);
  color: var(--color-text-muted);
  text-align: center;
  font-size: var(--font-size-sm);
}

/* ── Vertical timeline (kindergarten-friendly) ─────────── */
.timeline-wrap {
  padding: var(--space-4) var(--space-3) var(--space-3);
  border-radius: 20px;
  background:
    linear-gradient(165deg, rgba(255, 248, 240, 0.95) 0%, rgba(255, 252, 250, 0.98) 45%, rgba(240, 249, 255, 0.55) 100%);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.85),
    0 8px 28px rgba(15, 23, 42, 0.06);
  border: 1px solid rgba(251, 207, 232, 0.45);
}
.timeline {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
}
.timeline__entry {
  display: grid;
  grid-template-columns: 58px 28px 1fr;
  align-items: stretch;
  gap: var(--space-3);
  min-height: 96px;
}
.timeline__time {
  padding-top: 20px;
  font-variant-numeric: tabular-nums;
  font-weight: var(--font-weight-semibold);
  color: #9d6b8a;
  text-align: right;
  font-size: var(--font-size-sm);
  line-height: 1.2;
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
  width: 4px;
  margin-left: -2px;
  border-radius: 999px;
  background: linear-gradient(
    180deg,
    rgba(251, 191, 36, 0.35) 0%,
    rgba(244, 114, 182, 0.45) 42%,
    rgba(147, 197, 253, 0.5) 100%
  );
  box-shadow: 0 0 12px rgba(244, 114, 182, 0.15);
}
.timeline__entry:first-child .timeline__rail::before {
  top: 28px;
}
.timeline__entry:last-child .timeline__rail::before {
  bottom: calc(100% - 36px);
}
.timeline__dot {
  position: relative;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: linear-gradient(145deg, #fde68a, #fbbf24);
  margin-top: 24px;
  border: 3px solid #fffef8;
  box-shadow:
    0 0 0 2px rgba(251, 191, 36, 0.35),
    0 3px 10px rgba(15, 23, 42, 0.12);
  z-index: 1;
}
.timeline__entry--happy .timeline__dot {
  background: linear-gradient(145deg, #fcd34d, #f59e0b);
  box-shadow:
    0 0 0 2px rgba(245, 158, 11, 0.4),
    0 3px 10px rgba(245, 158, 11, 0.25);
}
.timeline__entry--sad .timeline__dot {
  background: linear-gradient(145deg, #e5e7eb, #9ca3af);
  box-shadow:
    0 0 0 2px rgba(156, 163, 175, 0.35),
    0 3px 10px rgba(15, 23, 42, 0.1);
}
.timeline__entry--note .timeline__dot {
  background: linear-gradient(145deg, #faf5ff, #e9d5ff);
  border-color: #fffef8;
  box-shadow:
    0 0 0 2px rgba(196, 181, 253, 0.5),
    0 3px 10px rgba(139, 92, 246, 0.12);
}
.timeline__card {
  display: flex;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  margin: var(--space-2) 0;
  background: rgba(255, 255, 255, 0.82);
  backdrop-filter: blur(6px);
  border: 1px solid rgba(255, 255, 255, 0.9);
  border-radius: 16px;
  border-left: 4px solid rgba(251, 191, 36, 0.65);
  box-shadow:
    0 4px 16px rgba(15, 23, 42, 0.06),
    inset 0 1px 0 rgba(255, 255, 255, 0.95);
  color: inherit;
}
.timeline__entry--happy .timeline__card {
  border-left-color: rgba(245, 158, 11, 0.85);
}
.timeline__entry--sad .timeline__card {
  border-left-color: rgba(148, 163, 184, 0.9);
}
.timeline__entry--note .timeline__card {
  border-left-color: rgba(167, 139, 250, 0.75);
}
.timeline__card--text {
  background: rgba(255, 251, 245, 0.92);
  border-style: solid;
  border-color: rgba(254, 215, 170, 0.55);
}
.timeline__card--editing {
  flex-direction: column;
  align-items: stretch;
  border-color: rgba(251, 146, 60, 0.5);
  box-shadow:
    0 4px 20px rgba(251, 146, 60, 0.12),
    inset 0 1px 0 rgba(255, 255, 255, 0.95);
}
.timeline__edit {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  width: 100%;
  min-width: 0;
}
.timeline__edit .timeline__thumb-link {
  align-self: flex-start;
}
.timeline__edit-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  flex-wrap: wrap;
}
.timeline__edit-err {
  margin: 0;
  font-size: var(--font-size-xs);
  color: var(--color-status-danger);
}
.timeline__body--editable {
  cursor: pointer;
  border-radius: 10px;
  padding: 2px 4px;
  margin: -2px -4px;
  outline: none;
  transition: background var(--motion-base) var(--motion-ease);
}
.timeline__body--editable:hover {
  background: rgba(255, 255, 255, 0.65);
}
.timeline__body--editable:focus-visible {
  box-shadow: var(--focus-ring);
}
.timeline__text-card {
  display: block;
  width: 100%;
  margin: 0;
  padding: 0;
  border: none;
  background: transparent;
  cursor: pointer;
  text-align: left;
  font: inherit;
  color: inherit;
  border-radius: 8px;
  transition: background var(--motion-base) var(--motion-ease);
}
.timeline__text-card:hover {
  background: rgba(255, 255, 255, 0.45);
}
.timeline__text-card:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}
.timeline__thumb-link {
  position: relative;
  display: block;
  flex-shrink: 0;
  text-decoration: none;
  transition: transform var(--motion-base) var(--motion-ease);
  border-radius: 14px;
  overflow: hidden;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.08);
  scroll-snap-align: start;
}
.timeline__thumb-link:hover {
  transform: scale(1.03) rotate(-0.5deg);
}
.timeline__thumb {
  width: 96px;
  height: 96px;
  object-fit: cover;
  border-radius: 14px;
  background: var(--color-surface-sunken);
  display: block;
}
/* 다중 사진 strip — 한 줄 가로 스크롤, 모바일에서도 자연스럽게 swipe. */
.timeline__strip {
  display: flex;
  gap: var(--space-2);
  overflow-x: auto;
  overflow-y: hidden;
  scroll-snap-type: x mandatory;
  scrollbar-width: thin;
  padding-bottom: 4px;
  margin: 0;
  /* card 너비를 강제로 차지 — 옆 텍스트 카드의 column-shrink 와 충돌 방지 */
  min-width: 0;
}
.timeline__strip::-webkit-scrollbar {
  height: 6px;
}
.timeline__strip::-webkit-scrollbar-thumb {
  background: rgba(148, 163, 184, 0.4);
  border-radius: 999px;
}
.timeline__thumb-time {
  position: absolute;
  left: 4px;
  bottom: 4px;
  padding: 1px 6px;
  font-size: 10px;
  font-weight: var(--font-weight-semibold);
  color: white;
  background: rgba(15, 23, 42, 0.55);
  border-radius: 999px;
  font-variant-numeric: tabular-nums;
  pointer-events: none;
}
.timeline__count {
  padding: 2px 10px;
  background: rgba(244, 114, 182, 0.15);
  border: 1px solid rgba(244, 114, 182, 0.4);
  color: #be185d;
  border-radius: 999px;
  font-weight: var(--font-weight-semibold);
  font-size: var(--font-size-xs);
}
/* 다중 사진 카드는 strip 가 가로로 확장될 수 있게 본문을 아래로 배치 */
.timeline__card--multi {
  flex-direction: column;
  align-items: stretch;
  gap: var(--space-2);
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
  line-height: 1.55;
  color: var(--color-text-primary);
}
.timeline__emotion {
  font-weight: var(--font-weight-semibold);
  color: #b45309;
}
.timeline__entry--sad .timeline__emotion {
  color: #64748b;
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
  padding: 2px 10px;
  background: rgba(255, 255, 255, 0.75);
  border-radius: 999px;
  border: 1px solid rgba(226, 232, 240, 0.8);
}
.timeline__score {
  font-variant-numeric: tabular-nums;
}

/* 하루 정리 — 타임라인 아래 한 문장 */
.summary-wrap {
  margin-top: var(--space-3);
}

.summary {
  margin: 0;
  padding: var(--space-4);
  background: linear-gradient(135deg, rgba(255, 237, 213, 0.65), rgba(254, 243, 199, 0.5));
  border-radius: 16px;
  border: 1px solid rgba(251, 191, 36, 0.35);
  box-shadow: 0 4px 14px rgba(251, 146, 60, 0.08);
  font-size: var(--font-size-sm);
  color: var(--color-text-primary);
  line-height: 1.55;
}

.summary--clickable {
  display: block;
  width: 100%;
  text-align: left;
  cursor: pointer;
  font-family: inherit;
  transition: box-shadow 0.15s, border-color 0.15s;
}

.summary--clickable:hover {
  border-color: rgba(251, 146, 60, 0.55);
  box-shadow: 0 6px 18px rgba(251, 146, 60, 0.12);
}

.summary--editing {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.summary__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  justify-content: flex-end;
}

.summary__err {
  margin: 0;
  font-size: var(--font-size-xs);
  color: var(--color-status-danger);
}

/* legacy 평문 보고서 */
.legacy-report {
  white-space: pre-wrap;
  padding: var(--space-4);
  background: rgba(255, 255, 255, 0.75);
  border-radius: 16px;
  border: 1px dashed rgba(203, 213, 225, 0.9);
  font-size: var(--font-size-sm);
  line-height: 1.55;
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
  flex-wrap: wrap;
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
.clear-btn {
  background: transparent;
  color: var(--color-status-danger);
  border: 1px solid var(--color-border-strong);
  padding: 10px 16px;
  border-radius: 999px;
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
  transition: opacity 0.15s, background 0.15s;
  font-family: inherit;
}
.clear-btn:hover:not(:disabled) {
  background: color-mix(in srgb, var(--color-status-danger) 12%, transparent);
}
.clear-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.err { font-size: var(--font-size-xs); color: var(--color-status-danger); }

@media (max-width: 767px) {
  .filters {
    grid-template-columns: 1fr;
  }

  .child-select-mobile {
    display: flex;
    flex-direction: column;
    margin-bottom: var(--space-2);
  }

  .child-list-desktop {
    display: none;
  }

  .layout {
    grid-template-columns: 1fr;
    gap: var(--space-3);
  }

  .ul {
    max-height: none;
  }

  .detail__head {
    flex-wrap: wrap;
    gap: var(--space-2);
  }

  .timeline-wrap {
    padding: var(--space-3) var(--space-2);
    border-radius: 16px;
  }

  .timeline__entry {
    grid-template-columns: 46px 22px minmax(0, 1fr);
    gap: var(--space-2);
    min-height: 0;
  }

  .timeline__time {
    padding-top: 14px;
    font-size: var(--font-size-xs);
  }

  .timeline__dot {
    width: 14px;
    height: 14px;
    margin-top: 18px;
  }

  .timeline__entry:first-child .timeline__rail::before {
    top: 22px;
  }

  .timeline__entry:last-child .timeline__rail::before {
    bottom: calc(100% - 30px);
  }

  .timeline__card {
    flex-direction: column;
    align-items: stretch;
  }

  /* 모바일 — 단일 사진은 큰 썸네일, 다중 사진은 가로 스크롤 strip 유지. */
  .timeline__card:not(.timeline__card--multi) .timeline__thumb {
    width: 100%;
    max-width: 200px;
    height: auto;
    aspect-ratio: 1;
    align-self: flex-start;
  }
  .timeline__card--multi .timeline__thumb {
    width: 84px;
    height: 84px;
  }
}

@media (min-width: 768px) {
  .filters {
    grid-template-columns: 200px minmax(200px, 1fr);
  }
}
</style>
