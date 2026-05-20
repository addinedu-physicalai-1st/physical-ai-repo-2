<script setup lang="ts">
/**
 * Compare page for admin QWebEngineView — two OpenarmViewer panes.
 * Clip precompute runs in a Web Worker; PyQt loads recording on a QThread.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import OpenarmViewer from '@/eduping/OpenarmViewer.vue';
import type { JointSnapshot as StreamJointSnapshot } from '@/eduping/useDanceStream';

interface JointLimit { min: number; max: number; }
interface CompareRecording {
  joint_names: string[];
  frames: number[][];
  frame_hz: number;
  duration_s: number;
  name?: string;
}
interface CompareData {
  recording: CompareRecording;
  limits_before: Record<string, JointLimit>;
  limits_after: Record<string, JointLimit>;
}

type CompareStatus = 'loading' | 'preparing' | 'warming' | 'ready' | 'error';

const data = ref<CompareData | null>(null);
const status = ref<CompareStatus>('loading');
const errorMsg = ref('');
const playing = ref(false);
const cursorMs = ref(0);
const durationMs = ref(0);
const snapBefore = ref<StreamJointSnapshot | null>(null);
const snapAfter = ref<StreamJointSnapshot | null>(null);
/** Mount both viewers only after clip worker finishes. */
const showViewers = ref(false);
const clipDone = ref(false);
const leftViewerReady = ref(false);
const rightViewerReady = ref(false);
interface StlProgress {
  ready: number;
  total: number;
  gripperReady: number;
  gripperTotal: number;
}
const leftStlProgress = ref<StlProgress>({
  ready: 0, total: 0, gripperReady: 0, gripperTotal: 0,
});
const rightStlProgress = ref<StlProgress>({
  ready: 0, total: 0, gripperReady: 0, gripperTotal: 0,
});

interface CameraSyncState {
  position: [number, number, number];
  target: [number, number, number];
}
const sharedCamera = ref<CameraSyncState | null>(null);

const preBefore = ref<Float32Array[]>([]);
const preAfter = ref<Float32Array[]>([]);

let clipWorker: Worker | null = null;
let _playTimer = 0;
let _wallStartMs = 0;
let _cursorStartMs = 0;

/** Playback + render cadence in QWebEngine (20 FPS). */
const TICK_MS = 50;

function clipPose(
  pose: number[],
  names: string[],
  limits: Record<string, JointLimit>,
): Float32Array {
  const out = new Float32Array(pose.length);
  for (let i = 0; i < pose.length; i++) {
    const lim = limits[names[i]];
    const v = pose[i];
    out[i] = lim ? Math.min(Math.max(v, lim.min), lim.max) : v;
  }
  return out;
}

function applyFrameAt(tMs: number): void {
  const d = data.value;
  if (!d) return;
  const dur = durationMs.value;
  if (dur <= 0) return;
  const tt = Math.max(0, Math.min(tMs, dur));
  const totalFrames = d.recording.frames.length;
  const idx = Math.min(
    totalFrames - 1,
    Math.floor((tt * d.recording.frame_hz) / 1000),
  );
  const names = d.recording.joint_names;
  const now = Date.now();

  if (preBefore.value.length > idx && preAfter.value.length > idx) {
    snapBefore.value = {
      jointNames: names,
      positions: preBefore.value[idx],
      tMs: now,
    };
    snapAfter.value = {
      jointNames: names,
      positions: preAfter.value[idx],
      tMs: now,
    };
    return;
  }

  const pose = d.recording.frames[idx];
  if (!pose) return;
  snapBefore.value = {
    jointNames: names,
    positions: clipPose(pose, names, d.limits_before),
    tMs: now,
  };
  snapAfter.value = {
    jointNames: names,
    positions: clipPose(pose, names, d.limits_after),
    tMs: now,
  };
}

function onPlayTick(): void {
  if (!playing.value || !data.value) return;
  const elapsed = performance.now() - _wallStartMs;
  let tMs = _cursorStartMs + elapsed;
  const dur = durationMs.value;
  if (tMs >= dur) {
    _wallStartMs = performance.now();
    _cursorStartMs = 0;
    tMs = 0;
  }
  cursorMs.value = tMs;
  applyFrameAt(tMs);
}

function play(): void {
  if (!data.value || status.value !== 'ready') return;
  if (cursorMs.value >= durationMs.value - 1) cursorMs.value = 0;
  _wallStartMs = performance.now();
  _cursorStartMs = cursorMs.value;
  playing.value = true;
  if (_playTimer === 0) {
    _playTimer = window.setInterval(onPlayTick, TICK_MS);
  }
}

function pause(): void {
  playing.value = false;
  if (_playTimer !== 0) {
    window.clearInterval(_playTimer);
    _playTimer = 0;
  }
}

function togglePlay(): void {
  if (playing.value) pause();
  else play();
}

function onScrub(): void {
  applyFrameAt(cursorMs.value);
  if (playing.value) {
    _wallStartMs = performance.now();
    _cursorStartMs = cursorMs.value;
  }
}

function resetPostProcessGates(): void {
  clipDone.value = false;
  leftViewerReady.value = false;
  rightViewerReady.value = false;
  leftStlProgress.value = {
    ready: 0, total: 0, gripperReady: 0, gripperTotal: 0,
  };
  rightStlProgress.value = {
    ready: 0, total: 0, gripperReady: 0, gripperTotal: 0,
  };
  showViewers.value = false;
}

function onViewerMeshProgress(side: 'before' | 'after', p: StlProgress): void {
  if (side === 'before') leftStlProgress.value = p;
  else rightStlProgress.value = p;
}

function maybeFinishPostProcessAndPlay(): void {
  if (!clipDone.value || !leftViewerReady.value || !rightViewerReady.value) {
    return;
  }
  if (status.value === 'ready') return;
  status.value = 'ready';
  applyFrameAt(0);
  play();
}

function onViewerReady(side: 'before' | 'after'): void {
  if (side === 'before') leftViewerReady.value = true;
  else rightViewerReady.value = true;
  maybeFinishPostProcessAndPlay();
}

function onViewerError(message: string): void {
  pause();
  status.value = 'error';
  errorMsg.value = message;
}

function startClipWorker(d: CompareData): void {
  pause();
  resetPostProcessGates();
  status.value = 'preparing';
  clipWorker?.terminate();
  clipWorker = new Worker(
    new URL('./compareClip.worker.ts', import.meta.url),
    { type: 'module' },
  );
  clipWorker.onmessage = (ev: MessageEvent<{ before: Float32Array[]; after: Float32Array[] }>) => {
    preBefore.value = ev.data.before;
    preAfter.value = ev.data.after;
    clipWorker?.terminate();
    clipWorker = null;
    clipDone.value = true;
    showViewers.value = true;
    status.value = 'warming';
    maybeFinishPostProcessAndPlay();
  };
  clipWorker.onerror = () => {
    clipWorker?.terminate();
    clipWorker = null;
    preBefore.value = [];
    preAfter.value = [];
    clipDone.value = true;
    showViewers.value = true;
    status.value = 'warming';
    maybeFinishPostProcessAndPlay();
  };
  clipWorker.postMessage({
    frames: d.recording.frames,
    jointNames: d.recording.joint_names,
    limitsBefore: d.limits_before,
    limitsAfter: d.limits_after,
  });
}

const statusOverlayText = computed(() => {
  switch (status.value) {
    case 'preparing':
      return '클립 계산 중 (워커)… 재생은 준비가 끝난 뒤 시작됩니다.';
    case 'warming': {
      const l = leftStlProgress.value;
      const r = rightStlProgress.value;
      if (l.total > 0 || r.total > 0) {
        return (
          `STL 로드 중… 모델 L ${l.ready}/${l.total} R ${r.ready}/${r.total} · `
          + `그리퍼 L ${l.gripperReady}/${l.gripperTotal} R ${r.gripperReady}/${r.gripperTotal} `
          + '(그리퍼 STL 포함 전부 후 재생)'
        );
      }
      return '3D 뷰어 준비 중… 그리퍼 STL 까지 로드되면 재생합니다.';
    }
    case 'loading':
      return '데이터 로딩 중…';
    default:
      return '';
  }
});

function readPyQtInjectedData(): CompareData | null {
  const w = window as Window & { __ADMIN_COMPARE_DATA__?: CompareData };
  const d = w.__ADMIN_COMPARE_DATA__;
  if (d?.recording && Array.isArray(d.recording.frames)) return d;
  return null;
}

function waitForPyQtInjectedData(timeoutMs = 120_000): Promise<CompareData | null> {
  const existing = readPyQtInjectedData();
  if (existing) return Promise.resolve(existing);
  return new Promise((resolve) => {
    const done = () => {
      const d = readPyQtInjectedData();
      if (d) resolve(d);
    };
    window.addEventListener('admin-compare-data', done);
    const tick = window.setInterval(() => {
      const d = readPyQtInjectedData();
      if (d) {
        window.clearInterval(tick);
        window.clearTimeout(timer);
        window.removeEventListener('admin-compare-data', done);
        resolve(d);
      }
    }, 200);
    const timer = window.setTimeout(() => {
      window.clearInterval(tick);
      window.removeEventListener('admin-compare-data', done);
      resolve(readPyQtInjectedData());
    }, timeoutMs);
  });
}

async function fetchDataFromPort(): Promise<CompareData | null> {
  const params = new URLSearchParams(window.location.search);
  const port = params.get('data-port');
  if (!port || !/^\d+$/.test(port)) return null;
  for (const host of ['127.0.0.1', 'localhost']) {
    try {
      const resp = await fetch(`http://${host}:${port}/data.json`, {
        cache: 'no-store',
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      return await resp.json();
    } catch (e) {
      console.warn(`[AdminOpenArmCompare] fetch ${host}:${port} failed`, e);
    }
  }
  return null;
}

function fmtTime(ms: number): string {
  return (ms / 1000).toFixed(1);
}

onMounted(async () => {
  const params = new URLSearchParams(window.location.search);
  const hasDataPort = Boolean(params.get('data-port'));
  status.value = 'loading';
  if (!hasDataPort && !readPyQtInjectedData()) {
    errorMsg.value = '관리자에서 비교 데이터 준비 중…';
  }

  let d = readPyQtInjectedData();
  if (!d) d = await waitForPyQtInjectedData();
  if (!d && hasDataPort) d = await fetchDataFromPort();
  if (!d && hasDataPort) d = await waitForPyQtInjectedData(15_000);
  if (!d || !d.recording || !Array.isArray(d.recording.frames)) {
    status.value = 'error';
    errorMsg.value
      = '데이터 로드 실패. robot-web(dev) 실행 후 [웹뷰어에서 비교 재생] 을 다시 누르세요.';
    return;
  }
  errorMsg.value = '';
  data.value = d;
  durationMs.value = d.recording.duration_s * 1000;
  cursorMs.value = 0;
  startClipWorker(d);
});

onBeforeUnmount(() => {
  pause();
  clipWorker?.terminate();
  clipWorker = null;
});
</script>

<template>
  <div class="compare-root">
    <header class="bar">
      <div class="title">
        녹화 안전 분석 비교
        <span v-if="data" class="subtitle">— {{ data.recording.name ?? '?' }}</span>
      </div>
      <button class="play-btn" type="button" :disabled="status !== 'ready'" @click="togglePlay">
        {{ playing ? '■ 정지' : '▶ 재생' }}
      </button>
      <input
        class="scrub"
        type="range"
        :min="0"
        :max="durationMs"
        step="50"
        :disabled="status !== 'ready'"
        v-model.number="cursorMs"
        @input="onScrub"
      />
      <div class="time">
        {{ fmtTime(cursorMs) }}s / {{ fmtTime(durationMs) }}s
      </div>
    </header>

    <div class="stage">
      <template v-if="showViewers">
        <section class="cell">
          <div class="cell-label cell-label-before">
            분석 전 (원본 한계) — 자기충돌 발생 가능
          </div>
          <div class="viewer-wrap">
            <OpenarmViewer
              source="leader"
              render-lite
              :external-snapshot="snapBefore"
              link-camera
              v-model:cameraSync="sharedCamera"
              @viewer-ready="onViewerReady('before')"
              @viewer-mesh-progress="onViewerMeshProgress('before', $event)"
              @viewer-error="onViewerError"
            />
          </div>
        </section>
        <section class="cell">
          <div class="cell-label cell-label-after">
            분석 후 (안전 한계) — clip 으로 충돌 회피
          </div>
          <div class="viewer-wrap">
            <OpenarmViewer
              source="leader"
              render-lite
              :external-snapshot="snapAfter"
              link-camera
              v-model:cameraSync="sharedCamera"
              @viewer-ready="onViewerReady('after')"
              @viewer-mesh-progress="onViewerMeshProgress('after', $event)"
              @viewer-error="onViewerError"
            />
          </div>
        </section>
      </template>
      <div v-if="status === 'error'" class="overlay error">
        {{ errorMsg }}
      </div>
      <div v-else-if="status !== 'ready'" class="overlay">
        {{ statusOverlayText }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.compare-root {
  position: fixed;
  inset: 0;
  background: #0f172a;
  color: #e2e8f0;
  display: flex;
  flex-direction: column;
  font-family: system-ui, -apple-system, 'Pretendard', sans-serif;
}
.bar {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 10px 18px;
  background: #1e293b;
  border-bottom: 1px solid #334155;
}
.title { font-size: 14px; font-weight: 700; }
.subtitle { font-weight: 500; color: #94a3b8; }
.play-btn {
  background: #16a34a;
  color: white;
  border: none;
  border-radius: 6px;
  padding: 6px 14px;
  font-weight: 700;
  font-size: 13px;
  cursor: pointer;
}
.play-btn:hover { background: #15803d; }
.play-btn:disabled { background: #475569; cursor: not-allowed; }
.scrub { flex: 1; accent-color: #60a5fa; }
.scrub:disabled { opacity: 0.4; }
.time {
  font-variant-numeric: tabular-nums;
  font-size: 12px;
  color: #cbd5e1;
  min-width: 110px;
  text-align: right;
}
.stage {
  flex: 1;
  position: relative;
  display: grid;
  overflow: hidden;
  grid-template-columns: 1fr 1fr;
  gap: 2px;
  background: #334155;
  min-height: 0;
}
.cell {
  background: #eaf3fa;
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
  overflow: hidden;
}
.cell-placeholder {
  background: #dbeafe;
  align-items: center;
  justify-content: center;
}
.cell-label {
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 700;
  color: white;
}
.cell-label-before { background: #b91c1c; }
.cell-label-after { background: #047857; }
.viewer-wrap {
  flex: 1;
  position: relative;
  min-height: 0;
  min-width: 0;
}
.viewer-wrap :deep(.openarm-viewer-wrap) {
  width: 100%;
  height: 100%;
}
.overlay {
  position: absolute;
  inset: 0;
  z-index: 20;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(15, 23, 42, 0.85);
  color: white;
  text-align: center;
}
.overlay.error { color: #fecaca; max-width: 100%; }
</style>
