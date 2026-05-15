<script setup lang="ts">
/**
 * 녹화 시작·중지·저장/버리기 + 재생 트리거 + 라이브 상태 표시.
 *
 * 상위 (DanceManager / GreetingManager) 가 kind + name 만 prop 으로 넘기면
 * 본 컴포넌트가 /api/eduping/{kind}/{name}/record/{start|stop} + /play 를 호출.
 *
 * 상태는 useEdupingRecordingWs 한 인스턴스를 부모/형제와 공유 (provide/inject 안 씀 —
 * 단순히 자체 인스턴스). 서버측 단일 state machine 이라 복수 클라이언트가 같은 값 봄.
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { useEdupingRecordingWs } from '@/composables/useEdupingRecordingWs';
import { useEdupingStateWs } from '@/composables/useEdupingStateWs';
import WarningModal from '@/common/WarningModal.vue';
import Icon from '@/common/Icon.vue';

const props = defineProps<{
  kind: 'dance' | 'greeting';
  name: string;
  /** 비활성화 (예: name 미선택) */
  disabled?: boolean;
}>();

const emit = defineEmits<{
  (e: 'recorded', payload: { frame_count: number; duration_s: number }): void;
  (e: 'played', payload: { ok: boolean; duration_s: number }): void;
}>();

const recWs = useEdupingRecordingWs();
recWs.start();
const stateWs = useEdupingStateWs();
stateWs.start();

const inflight = ref(false);
const lastError = ref('');
const countdown = ref<number | null>(null);
const liveTeleop = ref(false);   // 실물 동기화 토글 — 녹화/재생과 독립적으로 leader→실물 mirror
const teleopBusy = ref(false);   // 토글 POST 진행 중 잠금
const playConfirmOpen = ref(false);

// 재생 진행 상태 — 서버가 응답한 duration_s 기준 wall-clock 추정.
const playStartMs = ref<number | null>(null);
const playDuration = ref(0);
const playElapsed = ref(0);
let progressTimer: number | null = null;

const playProgressPct = computed(() => {
  if (playDuration.value <= 0) return 0;
  return Math.min(100, (playElapsed.value / playDuration.value) * 100);
});

function fmtTime(s: number): string {
  if (s < 0 || !Number.isFinite(s)) return '0:00';
  const total = Math.floor(s);
  const m = Math.floor(total / 60);
  const r = total % 60;
  return `${m}:${r.toString().padStart(2, '0')}`;
}

function clearProgressTimer(): void {
  if (progressTimer !== null) {
    window.clearInterval(progressTimer);
    progressTimer = null;
  }
}

onBeforeUnmount(clearProgressTimer);

const realActive = computed(() => stateWs.realActive.value);
const leaderActive = computed(() => stateWs.leaderActive.value);

// 실물 끊기면 teleop 자동 OFF (controller 가 사라져서 publish 가 의미 없어짐).
watch(realActive, (real) => {
  if (!real && liveTeleop.value) {
    liveTeleop.value = false;
  }
});

// 토글 변화 → 즉시 /api/eduping/teleop POST. 실패 시 상태 롤백.
watch(liveTeleop, async (newVal, oldVal) => {
  if (newVal === oldVal) return;
  teleopBusy.value = true;
  try {
    const res = await fetch('/api/eduping/teleop', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ enabled: newVal }),
    });
    const json = await res.json().catch(() => null);
    if (!res.ok || (json && json.switch === 'failed')) {
      const msg = json?.hint ?? json?.detail ?? `teleop ${newVal ? '켜기' : '끄기'} 실패`;
      lastError.value = String(msg);
      // 롤백
      liveTeleop.value = oldVal;
    } else {
      lastError.value = '';
    }
  } catch (err) {
    lastError.value = (err as Error).message;
    liveTeleop.value = oldVal;
  } finally {
    teleopBusy.value = false;
  }
});

const isMine = computed(
  () => recWs.recording.value?.active && recWs.recording.value.kind === props.kind && recWs.recording.value.name === props.name,
);

function urlPrefix(): string {
  return `/api/eduping/${props.kind}/${encodeURIComponent(props.name)}`;
}

async function postJson(url: string, body?: object): Promise<any> {
  inflight.value = true;
  lastError.value = '';
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: body ? { 'content-type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    const txt = await res.text();
    let json: any = null;
    try {
      json = txt ? JSON.parse(txt) : null;
    } catch {
      /* not json */
    }
    if (!res.ok) {
      const detail = json?.detail ?? txt ?? `HTTP ${res.status}`;
      throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }
    return json;
  } catch (err) {
    lastError.value = (err as Error).message;
    throw err;
  } finally {
    inflight.value = false;
  }
}

async function startRecording(): Promise<void> {
  if (props.disabled || inflight.value) return;
  // 카운트다운 3 → 2 → 1 → REC
  countdown.value = 3;
  await new Promise((r) => setTimeout(r, 700));
  countdown.value = 2;
  await new Promise((r) => setTimeout(r, 700));
  countdown.value = 1;
  await new Promise((r) => setTimeout(r, 700));
  countdown.value = null;
  try {
    await postJson(`${urlPrefix()}/record/start`);
  } catch {
    /* error in lastError already */
  }
}

async function stopRecording(): Promise<void> {
  if (inflight.value) return;
  try {
    const result = await postJson(`${urlPrefix()}/record/stop`, { save: true });
    emit('recorded', {
      frame_count: result?.frame_count ?? 0,
      duration_s: result?.duration_s ?? 0,
    });
  } catch {
    /* error in lastError */
  }
}

async function play(): Promise<void> {
  if (props.disabled || inflight.value) return;
  if (realActive.value) {
    playConfirmOpen.value = true;
    return;
  }
  await doPlay();
}

async function doPlay(): Promise<void> {
  const target = realActive.value ? 'real' : 'sim';
  try {
    const result = await postJson(`${urlPrefix()}/play`, { target });
    const ok = !!result?.ok;
    const dur = Number(result?.duration_s ?? 0);
    if (ok && dur > 0) {
      clearProgressTimer();
      playStartMs.value = Date.now();
      playDuration.value = dur;
      playElapsed.value = 0;
      progressTimer = window.setInterval(() => {
        if (playStartMs.value === null) return;
        const e = (Date.now() - playStartMs.value) / 1000;
        if (e >= playDuration.value) {
          playElapsed.value = playDuration.value;
          clearProgressTimer();
          window.setTimeout(() => {
            playStartMs.value = null;
            playDuration.value = 0;
            playElapsed.value = 0;
          }, 600);
        } else {
          playElapsed.value = e;
        }
      }, 50);
    }
    emit('played', { ok, duration_s: dur });
  } catch {
    /* error in lastError */
  }
}

function onPlayConfirmed(): void {
  void doPlay();
}
</script>

<template>
  <div class="recorder">
    <div class="status" :class="{ active: isMine, disconnected: !recWs.connected.value }">
      <template v-if="countdown != null">
        <span class="countdown">{{ countdown }}</span>
        <span class="label">시작 대기…</span>
      </template>
      <template v-else-if="isMine">
        <span class="dot" />
        <span class="label">REC</span>
        <span class="metric">{{ recWs.recording.value?.frame_count ?? 0 }} frame</span>
        <span class="metric">{{ (recWs.recording.value?.elapsed_s ?? 0).toFixed(1) }}s</span>
      </template>
      <template v-else-if="recWs.recording.value?.active">
        <span class="label other">다른 항목 녹화중: {{ recWs.recording.value.kind }}/{{ recWs.recording.value.name }}</span>
      </template>
      <template v-else-if="!recWs.connected.value">
        <span class="label disconnected">recording WS 끊김</span>
      </template>
      <template v-else>
        <span class="label idle">대기</span>
      </template>
    </div>

    <label
      v-if="realActive"
      class="teleop-toggle"
      :class="{ active: liveTeleop }"
    >
      <input
        type="checkbox"
        v-model="liveTeleop"
        :disabled="teleopBusy || !leaderActive"
      />
      <span class="teleop-label">
        {{ teleopBusy ? '전환 중…' : (liveTeleop ? '실물 동기화 ON' : '실물 동기화 OFF') }}
      </span>
    </label>

    <button
      v-if="!isMine"
      type="button"
      class="btn btn-block btn-rec"
      :disabled="props.disabled || inflight || countdown != null || !leaderActive"
      @click="startRecording"
    >
      <Icon name="record" :size="14" />
      녹화 시작
    </button>
    <button
      v-else
      type="button"
      class="btn btn-block btn-stop-save"
      :disabled="inflight"
      @click="stopRecording"
    >
      <Icon name="stop" :size="14" />
      중지 · 저장
    </button>

    <button
      type="button"
      class="btn btn-block btn-play"
      :class="{ 'btn-play-real': realActive }"
      :disabled="props.disabled || inflight || isMine || playStartMs !== null"
      @click="play"
    >
      <Icon name="play" :size="14" />
      재생{{ realActive ? ' (실물)' : '' }}
    </button>

    <div v-if="playStartMs !== null" class="play-progress">
      <div class="play-bar">
        <div class="play-fill" :style="{ width: playProgressPct + '%' }" />
      </div>
      <div class="play-times">
        <span>{{ fmtTime(playElapsed) }}</span>
        <span class="play-total">{{ fmtTime(playDuration) }}</span>
      </div>
    </div>

    <div v-if="lastError" class="err">{{ lastError }}</div>

    <WarningModal
      v-model:open="playConfirmOpen"
      title="실물 로봇이 연결되어 있습니다"
      :message="'재생 시 양팔이 움직입니다.\n주변에 사람이나 장애물이 없는지 확인해주세요.\n\n계속하시겠습니까?'"
      okText="계속"
      cancelText="취소"
      @ok="onPlayConfirmed"
    />
  </div>
</template>

<style scoped>
.recorder {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 14px 16px;
  background: rgba(255, 255, 255, 0.92);
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
  font-size: 14px;
}
.status {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 600;
  min-height: 24px;
  padding: 6px 10px;
  background: #f8fafc;
  border-radius: 8px;
}
.status .dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #c14545;
  animation: pulse 1.1s ease-in-out infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}
.status .countdown {
  font-size: 28px;
  font-weight: 800;
  color: #c14545;
}
.status .label.idle { color: #94a3b8; }
.status .label.other { color: #b45309; }
.status .label.disconnected { color: #c14545; }
.status .metric {
  margin-left: auto;
  font-variant-numeric: tabular-nums;
  color: #475569;
  font-weight: 500;
}
.status .metric + .metric { margin-left: 8px; }

.btn {
  border: none;
  border-radius: 10px;
  font-size: 15px;
  font-weight: 700;
  cursor: pointer;
  transition: filter 0.1s, transform 0.05s;
}
.btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.btn:not(:disabled):hover { filter: brightness(1.06); }
.btn:not(:disabled):active { transform: translateY(1px); }
.btn-block {
  width: 100%;
  padding: 14px 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}
.btn-rec :deep(.icon) { color: #b91c1c; }
.btn-stop-save :deep(.icon) { color: #065f46; }
.btn-play :deep(.icon) { color: #1d4ed8; }
.btn-play-real :deep(.icon) { color: #b45309; }
.btn-rec        { background: #fee2e2; color: #b91c1c; }
.btn-stop-save  { background: #d1fae5; color: #065f46; }
.btn-play       { background: #dbeafe; color: #1d4ed8; }
.btn-play-real  { background: #fef3c7; color: #b45309; border: 1px solid #f59e0b; }

.err {
  color: #c14545;
  font-size: 13px;
  background: #fef2f2;
  padding: 6px 10px;
  border-radius: 8px;
}

.play-progress {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px 4px 2px;
}
.play-bar {
  height: 8px;
  background: #e2e8f0;
  border-radius: 999px;
  overflow: hidden;
}
.play-fill {
  height: 100%;
  background: linear-gradient(90deg, #60a5fa, #2563eb);
  border-radius: 999px;
  transition: width 0.1s linear;
}
.play-times {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  color: #475569;
}
.play-total { color: #94a3b8; }

.teleop-toggle {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
  user-select: none;
  background: #f8fafc;
  transition: background 0.12s, border-color 0.12s;
}
.teleop-toggle:hover { background: #f1f5f9; }
.teleop-toggle.active {
  background: #fef3c7;
  border-color: #f59e0b;
  color: #78350f;
}
.teleop-toggle input[type='checkbox'] {
  margin: 0;
  width: 18px;
  height: 18px;
  accent-color: #f59e0b;
}
.teleop-label { flex: 1; }
.spinning {
  animation: spin 0.9s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
