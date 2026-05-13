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
import { computed, ref } from 'vue';
import { useEdupingRecordingWs } from '@/composables/useEdupingRecordingWs';

const props = defineProps<{
  kind: 'dance' | 'greeting';
  name: string;
  /** 비활성화 (예: name 미선택) */
  disabled?: boolean;
}>();

const emit = defineEmits<{
  (e: 'recorded', payload: { saved: boolean; frame_count: number; duration_s: number }): void;
  (e: 'played', payload: { ok: boolean; duration_s: number }): void;
}>();

const recWs = useEdupingRecordingWs();
recWs.start();

const inflight = ref(false);
const lastError = ref('');
const countdown = ref<number | null>(null);
const playSpeed = ref(1.0);
const playTarget = ref<'sim' | 'real'>('sim');

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

async function stopRecording(save: boolean): Promise<void> {
  if (inflight.value) return;
  try {
    const result = await postJson(`${urlPrefix()}/record/stop`, { save });
    emit('recorded', {
      saved: !!result?.saved,
      frame_count: result?.frame_count ?? 0,
      duration_s: result?.duration_s ?? 0,
    });
  } catch {
    /* error in lastError */
  }
}

async function play(): Promise<void> {
  if (props.disabled || inflight.value) return;
  try {
    const result = await postJson(`${urlPrefix()}/play`, {
      target: playTarget.value,
      speed: playSpeed.value,
    });
    emit('played', { ok: !!result?.ok, duration_s: result?.duration_s ?? 0 });
  } catch {
    /* error in lastError */
  }
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

    <div class="row">
      <button
        type="button"
        class="btn btn-rec"
        :disabled="props.disabled || inflight || isMine || countdown != null"
        @click="startRecording"
      >● 녹화 시작</button>
      <button
        type="button"
        class="btn btn-stop-save"
        :disabled="!isMine || inflight"
        @click="stopRecording(true)"
      >■ 중지 · 저장</button>
      <button
        type="button"
        class="btn btn-stop-discard"
        :disabled="!isMine || inflight"
        @click="stopRecording(false)"
      >✗ 중지 · 버리기</button>
    </div>

    <div class="row">
      <button
        type="button"
        class="btn btn-play"
        :disabled="props.disabled || inflight || isMine"
        @click="play"
      >▶ 재생</button>
      <label class="select-label">
        대상
        <select v-model="playTarget" :disabled="inflight">
          <option value="sim">sim (three.js)</option>
          <option value="real">real (실물 controller)</option>
        </select>
      </label>
      <label class="select-label">
        속도
        <select v-model.number="playSpeed" :disabled="inflight">
          <option :value="0.5">0.5×</option>
          <option :value="1.0">1.0×</option>
          <option :value="1.5">1.5×</option>
        </select>
      </label>
    </div>

    <div v-if="lastError" class="err">{{ lastError }}</div>
  </div>
</template>

<style scoped>
.recorder {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px 14px;
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

.row {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
.btn {
  padding: 8px 14px;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: filter 0.1s;
}
.btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.btn:not(:disabled):hover { filter: brightness(1.05); }
.btn-rec        { background: #fee2e2; color: #b91c1c; }
.btn-stop-save  { background: #d1fae5; color: #065f46; }
.btn-stop-discard { background: #f3f4f6; color: #475569; }
.btn-play       { background: #dbeafe; color: #1d4ed8; }
.select-label {
  font-size: 13px;
  color: #475569;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.select-label select {
  padding: 4px 6px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  background: white;
}
.err {
  color: #c14545;
  font-size: 13px;
  background: #fef2f2;
  padding: 6px 10px;
  border-radius: 8px;
}
</style>
