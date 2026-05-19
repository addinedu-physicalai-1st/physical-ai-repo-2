<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watchEffect } from 'vue'
import { api } from '@/api/client'
import { localDateKey } from '@/lib/date'
import { useChildStore } from '@/stores/child'
import type { Photo, Report } from '@/types'
import PageHeader from '@/components/common/PageHeader.vue'
import BaseCard from '@/components/common/BaseCard.vue'
import BaseInput from '@/components/common/BaseInput.vue'
import BaseEmptyState from '@/components/common/BaseEmptyState.vue'
import Icon from '@/components/common/Icon.vue'

const child = useChildStore()
const today = localDateKey()
const date = ref(today)
const report = ref<Report | null>(null)
const photos = ref<Photo[]>([])

// 보고서 + 그 날의 자연 촬영 사진을 같이 가져온다. 백엔드는 한 세션의 여러 사진을 한 줄로
// 묶어서 보내지만(photo_ids[]), 파일 한 장의 정보(URL/감정)는 별도 API 로 조회해야 한다.
watchEffect(async () => {
  if (child.selectedChildId === null) return
  const [reportList, photoList] = await Promise.all([
    api.get<Report[]>(`/api/reports?child_id=${child.selectedChildId}&date=${date.value}`),
    api
      .get<Photo[]>(`/api/children/${child.selectedChildId}/photos?date=${date.value}`)
      .catch(() => [] as Photo[]),
  ])
  report.value = reportList[0] ?? null
  photos.value = photoList
})

const photosById = computed(() => {
  const map = new Map<number, Photo>()
  for (const p of photos.value) map.set(p.id, p)
  return map
})

interface TimelineEvent {
  time: string
  text: string
  /** 대표 사진 (서버가 클러스터의 score 최고로 고른 것) */
  photoId: number | null
  /** 같은 세션의 모든 사진 id — 클러스터 전체를 시간순으로 보존. 신규 포맷, 없으면 photoId 단일 fallback. */
  photoIds: number[]
}

interface ParsedReport {
  events: TimelineEvent[]
  summary: string
}

function eventPhotos(ev: TimelineEvent): Photo[] {
  const ids = ev.photoIds.length > 0 ? ev.photoIds : ev.photoId != null ? [ev.photoId] : []
  const out: Photo[] = []
  for (const id of ids) {
    const p = photosById.value.get(id)
    if (p) out.push(p)
  }
  return out
}

function emotionLabel(emotion: string | null): string {
  if (emotion === 'happy') return '😀 활짝'
  if (emotion === 'sad') return '😢 시무룩'
  return emotion ?? '·'
}

function timeLabel(takenAt: string): string {
  const d = new Date(takenAt)
  if (Number.isNaN(d.getTime())) return ''
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

// 라이트박스 — 타임라인 카드의 사진을 클릭하면 같은 클러스터의 모든 사진을 풀사이즈로
// 펼친다. 양옆 화살표·키보드(←/→/Esc)·하단 스트립으로 네비게이션.
const lightboxPhotos = ref<Photo[]>([])
const lightboxIndex = ref(0)
const lightboxOpen = computed(() => lightboxPhotos.value.length > 0)
const lightboxCurrent = computed<Photo | null>(
  () => lightboxPhotos.value[lightboxIndex.value] ?? null,
)

function openLightbox(list: Photo[], startIndex: number): void {
  if (list.length === 0) return
  lightboxPhotos.value = list
  lightboxIndex.value = Math.max(0, Math.min(startIndex, list.length - 1))
}

function closeLightbox(): void {
  lightboxPhotos.value = []
  lightboxIndex.value = 0
}

function lightboxNext(): void {
  if (lightboxPhotos.value.length === 0) return
  lightboxIndex.value = (lightboxIndex.value + 1) % lightboxPhotos.value.length
}

function lightboxPrev(): void {
  if (lightboxPhotos.value.length === 0) return
  const n = lightboxPhotos.value.length
  lightboxIndex.value = (lightboxIndex.value - 1 + n) % n
}

function onLightboxKey(e: KeyboardEvent): void {
  if (!lightboxOpen.value) return
  if (e.key === 'Escape') closeLightbox()
  else if (e.key === 'ArrowRight') lightboxNext()
  else if (e.key === 'ArrowLeft') lightboxPrev()
}

onMounted(() => window.addEventListener('keydown', onLightboxKey))
onUnmounted(() => window.removeEventListener('keydown', onLightboxKey))

// 모든 "HH:MM" 출현 위치 — 평문이 한 줄로 합쳐져 와도 (백엔드 polish 결과) 각 시각마다
// 새 이벤트로 쪼개기 위해 global flag 로 매칭한다. 구분자(—, –, :, ·)는 본문 시작 시
// 잘라낸다.
const TIME_TOKEN_RE = /\b(\d{1,2}:\d{2})\b/gu
const LEADING_SEPARATOR_RE = /^\s*[\-—–:·]\s*/u
const SUMMARY_PREFIX_RE = /^(?:오늘의 한 줄|하루 정리|요약)[:：]\s*/u

/** Try JSON first (teacher format). On failure, scan the text for every HH:MM marker and
 *  treat the span until the next marker as one event. Trailing un-timed text becomes summary. */
function parseReportContent(raw: string): ParsedReport {
  const stripped = raw.trim()
  if (!stripped) return { events: [], summary: '' }

  try {
    const obj = JSON.parse(stripped) as { events?: unknown; summary?: unknown }
    if (Array.isArray(obj.events)) {
      const events = obj.events
        .filter((e): e is Record<string, unknown> => !!e && typeof e === 'object')
        .map((e) => ({
          time: typeof e.time === 'string' ? e.time : '',
          text: typeof e.text === 'string' ? e.text : '',
          photoId: typeof e.photo_id === 'number' ? e.photo_id : null,
          photoIds: Array.isArray(e.photo_ids)
            ? e.photo_ids.filter((id): id is number => typeof id === 'number')
            : [],
        }))
        .filter((e) => e.time || e.text)
      return {
        events,
        summary: typeof obj.summary === 'string' ? obj.summary : '',
      }
    }
  } catch {
    /* fall through to plaintext */
  }

  // Plaintext fallback — find every HH:MM occurrence and split the string into ranges.
  const markers: { time: string; bodyStart: number; markerStart: number }[] = []
  let m: RegExpExecArray | null
  TIME_TOKEN_RE.lastIndex = 0
  while ((m = TIME_TOKEN_RE.exec(stripped)) !== null) {
    markers.push({ time: m[1], markerStart: m.index, bodyStart: m.index + m[0].length })
  }
  if (markers.length === 0) {
    return { events: [], summary: stripped.replace(SUMMARY_PREFIX_RE, '') }
  }

  const events: TimelineEvent[] = []
  for (let i = 0; i < markers.length; i++) {
    const start = markers[i].bodyStart
    const end = i + 1 < markers.length ? markers[i + 1].markerStart : stripped.length
    let body = stripped.slice(start, end).replace(LEADING_SEPARATOR_RE, '').trim()
    // 마지막 이벤트가 "오늘의 한 줄: ..." 을 끌어안았으면 prefix 위치에서 잘라 summary 로 분리.
    let trailingSummary = ''
    if (i + 1 === markers.length) {
      const summaryMatch = /(?:오늘의 한 줄|하루 정리|요약)[:：]\s*/u.exec(body)
      if (summaryMatch && summaryMatch.index !== undefined) {
        trailingSummary = body
          .slice(summaryMatch.index + summaryMatch[0].length)
          .trim()
        body = body.slice(0, summaryMatch.index).trim()
      }
    }
    events.push({ time: markers[i].time, text: body, photoId: null, photoIds: [] })
    if (trailingSummary) {
      return { events, summary: trailingSummary }
    }
  }
  const headTail = stripped.slice(0, markers[0].markerStart).trim()
  return { events, summary: headTail.replace(SUMMARY_PREFIX_RE, '') }
}

const parsed = computed<ParsedReport>(() =>
  report.value ? parseReportContent(report.value.content) : { events: [], summary: '' },
)

const dateLabel = computed(() => date.value.replace(/-/g, '.'))
</script>

<template>
  <section>
    <PageHeader title="일과 보고서" description="선생님이 작성한 일과 기록입니다.">
      <template #actions>
        <BaseInput v-model="date" type="date" />
      </template>
    </PageHeader>

    <template v-if="report">
      <BaseCard v-if="parsed.events.length" :padded="true" class="timeline-card">
        <template #header>
          <div class="timeline-head">
            <Icon name="clock" :size="16" />
            <span>오늘의 일과 타임라인</span>
            <span class="timeline-head__date numeric">{{ dateLabel }}</span>
          </div>
        </template>
        <ol class="timeline">
          <li
            v-for="(ev, i) in parsed.events"
            :key="`${ev.time}-${i}`"
            class="timeline__entry"
          >
            <div class="timeline__time numeric">{{ ev.time }}</div>
            <div class="timeline__rail">
              <span class="timeline__dot" />
            </div>
            <div class="timeline__card">
              <p class="timeline__text">{{ ev.text }}</p>
              <div v-if="eventPhotos(ev).length > 0" class="timeline__strip">
                <button
                  v-for="(p, pi) in eventPhotos(ev)"
                  :key="p.id"
                  type="button"
                  class="timeline__thumb-link"
                  :title="`${timeLabel(p.taken_at)} · ${emotionLabel(p.emotion)}`"
                  @click="openLightbox(eventPhotos(ev), pi)"
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
                </button>
              </div>
              <button
                v-if="eventPhotos(ev).length > 1"
                type="button"
                class="timeline__count"
                @click="openLightbox(eventPhotos(ev), 0)"
              >
                사진 {{ eventPhotos(ev).length }}장 모아 보기
              </button>
            </div>
          </li>
        </ol>
      </BaseCard>

      <BaseCard v-if="parsed.summary" :padded="true" class="summary-card">
        <template #header>
          <div class="summary-head">
            <Icon name="sparkles" :size="16" />
            <span>오늘의 한 줄</span>
          </div>
        </template>
        <p class="summary-text">{{ parsed.summary }}</p>
      </BaseCard>

      <!-- 보고서가 있으나 타임라인·요약 모두 비어있는 (legacy/raw) 경우의 안전망. -->
      <BaseCard v-if="!parsed.events.length && !parsed.summary" :padded="true">
        <article class="content">
          <p v-for="(line, i) in report.content.split('\n')" :key="i">{{ line }}</p>
        </article>
      </BaseCard>
    </template>

    <BaseEmptyState
      v-else
      icon="file-text"
      title="선택한 날짜에 보고서가 없습니다"
      description="다른 날짜를 선택하거나 하원 후 다시 확인하세요."
    />

    <!-- 라이트박스 — 타임라인 사진 클릭 시 같은 클러스터의 사진들을 풀사이즈로 펼친다. -->
    <Teleport to="body">
      <div
        v-if="lightboxOpen"
        class="lightbox"
        role="dialog"
        aria-modal="true"
        aria-label="사진 보기"
        @click.self="closeLightbox"
      >
        <button
          type="button"
          class="lightbox__close"
          aria-label="닫기"
          @click="closeLightbox"
        >×</button>

        <button
          v-if="lightboxPhotos.length > 1"
          type="button"
          class="lightbox__nav lightbox__nav--prev"
          aria-label="이전"
          @click="lightboxPrev"
        >‹</button>

        <figure v-if="lightboxCurrent" class="lightbox__stage">
          <img
            :src="lightboxCurrent.url"
            :alt="emotionLabel(lightboxCurrent.emotion)"
            class="lightbox__img"
          />
          <figcaption class="lightbox__caption">
            <span class="lightbox__time">{{ timeLabel(lightboxCurrent.taken_at) }}</span>
            <span class="lightbox__emotion">{{ emotionLabel(lightboxCurrent.emotion) }}</span>
            <span v-if="lightboxCurrent.mode" class="lightbox__mode">{{ lightboxCurrent.mode }}</span>
            <span class="lightbox__pos">{{ lightboxIndex + 1 }} / {{ lightboxPhotos.length }}</span>
          </figcaption>
        </figure>

        <button
          v-if="lightboxPhotos.length > 1"
          type="button"
          class="lightbox__nav lightbox__nav--next"
          aria-label="다음"
          @click="lightboxNext"
        >›</button>

        <div v-if="lightboxPhotos.length > 1" class="lightbox__strip">
          <button
            v-for="(p, pi) in lightboxPhotos"
            :key="p.id"
            type="button"
            class="lightbox__strip-thumb"
            :class="{ 'is-active': pi === lightboxIndex }"
            @click="lightboxIndex = pi"
          >
            <img :src="p.url" :alt="emotionLabel(p.emotion)" loading="lazy" />
          </button>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<style scoped>
.content p {
  line-height: var(--line-height-relaxed);
  margin: 0 0 var(--space-2);
  color: var(--color-text-primary);
  font-size: var(--font-size-base);
}
.content p:last-child { margin: 0; }

.timeline-card { margin-bottom: var(--space-4); }
.timeline-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}
.timeline-head__date {
  margin-left: auto;
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
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
  gap: var(--space-3);
  align-items: stretch;
  min-height: 76px;
}
.timeline__time {
  padding-top: 18px;
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
    rgba(244, 114, 182, 0.45) 45%,
    rgba(147, 197, 253, 0.5) 100%
  );
}
.timeline__entry:first-child .timeline__rail::before { top: 24px; }
.timeline__entry:last-child .timeline__rail::before { bottom: calc(100% - 32px); }
.timeline__dot {
  position: relative;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: linear-gradient(145deg, #fde68a, #fbbf24);
  margin-top: 22px;
  border: 3px solid var(--color-surface-raised);
  box-shadow:
    0 0 0 2px rgba(251, 191, 36, 0.32),
    0 3px 8px rgba(15, 23, 42, 0.1);
  z-index: 1;
}
.timeline__card {
  margin: var(--space-2) 0;
  padding: var(--space-3) var(--space-4);
  background: rgba(255, 251, 245, 0.85);
  border: 1px solid rgba(254, 215, 170, 0.55);
  border-left: 4px solid rgba(251, 191, 36, 0.7);
  border-radius: 14px;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
}
.timeline__text {
  margin: 0;
  color: var(--color-text-primary);
  font-size: var(--font-size-base);
  line-height: var(--line-height-relaxed);
}
.timeline__strip {
  margin-top: var(--space-2);
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}
.timeline__thumb-link {
  position: relative;
  display: inline-block;
  padding: 0;
  text-decoration: none;
  border-radius: 10px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.6);
  border: 1px solid rgba(254, 215, 170, 0.5);
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.06);
  cursor: pointer;
  transition: transform 0.12s ease, box-shadow 0.12s ease;
}
.timeline__thumb-link:hover {
  transform: translateY(-1px) scale(1.03);
  box-shadow: 0 6px 14px rgba(15, 23, 42, 0.12);
}
.timeline__thumb-link:focus-visible {
  outline: 2px solid rgba(244, 114, 182, 0.55);
  outline-offset: 2px;
}
.timeline__thumb {
  display: block;
  width: 72px;
  height: 72px;
  object-fit: cover;
}
.timeline__thumb-time {
  position: absolute;
  left: 4px;
  bottom: 4px;
  padding: 1px 6px;
  border-radius: 6px;
  background: rgba(15, 23, 42, 0.55);
  color: white;
  font-size: 10px;
  font-variant-numeric: tabular-nums;
  font-weight: var(--font-weight-semibold);
}
.timeline__count {
  margin-top: var(--space-1);
  padding: 4px 10px;
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  font-weight: var(--font-weight-semibold);
  background: rgba(254, 240, 215, 0.65);
  border: 1px solid rgba(254, 215, 170, 0.6);
  border-radius: 999px;
  cursor: pointer;
  transition: background 0.12s ease;
}
.timeline__count:hover { background: rgba(254, 215, 170, 0.85); }

.lightbox {
  position: fixed;
  inset: 0;
  z-index: 100;
  background: rgba(15, 23, 42, 0.85);
  display: grid;
  grid-template-rows: 1fr auto;
  align-items: center;
  justify-items: center;
  padding: 32px;
}
.lightbox__close {
  position: absolute;
  top: 16px;
  right: 16px;
  width: 44px;
  height: 44px;
  border: none;
  background: rgba(255, 255, 255, 0.15);
  color: white;
  font-size: 28px;
  line-height: 1;
  border-radius: 50%;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}
.lightbox__close:hover { background: rgba(255, 255, 255, 0.28); }

.lightbox__nav {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  width: 56px;
  height: 56px;
  border: none;
  background: rgba(255, 255, 255, 0.12);
  color: white;
  font-size: 40px;
  line-height: 1;
  border-radius: 50%;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}
.lightbox__nav:hover { background: rgba(255, 255, 255, 0.24); }
.lightbox__nav--prev { left: 24px; }
.lightbox__nav--next { right: 24px; }

.lightbox__stage {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  margin: 0;
  max-width: min(92vw, 1200px);
  max-height: 80vh;
}
.lightbox__img {
  max-width: 100%;
  max-height: 70vh;
  object-fit: contain;
  border-radius: 12px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
  background: #000;
}
.lightbox__caption {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  color: rgba(255, 255, 255, 0.92);
  font-size: 14px;
  font-weight: 600;
}
.lightbox__time { font-variant-numeric: tabular-nums; }
.lightbox__emotion {
  padding: 2px 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.18);
}
.lightbox__mode {
  padding: 2px 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.1);
  font-weight: 500;
  font-size: 13px;
}
.lightbox__pos {
  margin-left: auto;
  color: rgba(255, 255, 255, 0.7);
  font-variant-numeric: tabular-nums;
  font-size: 13px;
}

.lightbox__strip {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding: 8px 4px;
  max-width: 100%;
}
.lightbox__strip-thumb {
  flex: 0 0 auto;
  padding: 0;
  border: 2px solid transparent;
  background: none;
  border-radius: 8px;
  overflow: hidden;
  cursor: pointer;
  transition: border-color 0.12s ease, transform 0.12s ease;
}
.lightbox__strip-thumb img {
  display: block;
  width: 64px;
  height: 64px;
  object-fit: cover;
}
.lightbox__strip-thumb:hover { transform: translateY(-1px); }
.lightbox__strip-thumb.is-active { border-color: rgba(244, 114, 182, 0.85); }

.summary-card { background: var(--color-surface-raised); }
.summary-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}
.summary-text {
  margin: 0;
  color: var(--color-text-primary);
  font-size: var(--font-size-base);
  line-height: var(--line-height-relaxed);
  white-space: pre-line;
}
</style>
