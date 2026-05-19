<script setup lang="ts">
import { computed, ref, watchEffect } from 'vue'
import { api } from '@/api/client'
import { localDateKey } from '@/lib/date'
import { useChildStore } from '@/stores/child'
import type { Report } from '@/types'
import PageHeader from '@/components/common/PageHeader.vue'
import BaseCard from '@/components/common/BaseCard.vue'
import BaseInput from '@/components/common/BaseInput.vue'
import BaseEmptyState from '@/components/common/BaseEmptyState.vue'
import Icon from '@/components/common/Icon.vue'

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

interface TimelineEvent {
  time: string
  text: string
}

interface ParsedReport {
  events: TimelineEvent[]
  summary: string
}

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
    events.push({ time: markers[i].time, text: body })
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
