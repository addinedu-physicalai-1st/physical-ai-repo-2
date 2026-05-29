<script setup lang="ts">
/**
 * GogoPing 수동 탭 디버그 패널 — RECOVERY/Hint/PAN/State 테스트.
 *
 * 표시 조건은 App.vue 의 v-if 가 결정 (import.meta.env.DEV || ?debug=1).
 * 추후 hide 시 v-if="false" 또는 import 제거 한 줄로 완전 제거.
 */
import { computed, ref } from 'vue';
import { useFollowHint, type HintDirection } from './composables/useFollowHint';
import { useTrackingStateWs } from './composables/useTrackingStateWs';

const { sendHint } = useFollowHint();
const { state, connected } = useTrackingStateWs();

const panTarget = ref(90);
const tiltTarget = ref(100);
const toast = ref<string | null>(null);
const isSweeping = ref(false);

// hint 방향 → PAN target (recovery 의 hint_to_action 매핑과 동일)
// search/resume 은 sweep 시뮬 대상이 아니라 follow_node 가 직접 처리 — 본 매핑엔 의미 없음.
const HINT_PAN_TARGET: Record<HintDirection, number> = {
  right: 30,
  left: 150,
  front: 90,
  back: 90,    // base 180° 회전은 UI 에서 불가 — 좌/우 양쪽 sweep 으로 대체
  search: 90,  // 미사용 (onVoiceSearch 가 별도 처리)
  resume: 90,  // 미사용 (onVoiceResume 가 별도 처리)
};
const SWEEP_RATE_DEG_S = 10;   // 슬로우 sweep 속도 (follow_node config 와 동일)
const SWEEP_DWELL_MS = 2500;   // dwell (RECOVERY_HINT_DWELL_S 와 동일)
const SWEEP_TICK_MS = 100;     // 10 Hz publish

function showToast(msg: string) {
  toast.value = msg;
  setTimeout(() => {
    if (toast.value === msg) toast.value = null;
  }, 2000);
}

function sleep(ms: number): Promise<void> {
  return new Promise(r => setTimeout(r, ms));
}

async function publishPan(pan: number, silent = false) {
  try {
    const res = await fetch('/camera_pan/cmd', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pan }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    if (!silent) showToast(`PAN → ${pan}°`);
  } catch (e) {
    if (!silent) showToast(`PAN 실패: ${(e as Error).message}`);
    throw e;
  }
}

async function publishTilt(tilt: number) {
  try {
    const res = await fetch('/camera_pan/cmd', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tilt }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    showToast(`TILT → ${tilt}°`);
  } catch (e) {
    showToast(`TILT 실패: ${(e as Error).message}`);
  }
}

async function publishPanTiltHome() {
  // PAN+TILT 동시 home 복귀 — 한 요청으로 둘 다 보냄
  try {
    const res = await fetch('/camera_pan/cmd', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pan: 90, tilt: 100 }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    panTarget.value = 90;
    tiltTarget.value = 100;
    showToast('home 복귀: PAN 90° / TILT 100°');
  } catch (e) {
    showToast(`home 복귀 실패: ${(e as Error).message}`);
  }
}

/** 현재 panTarget 에서 target 까지 SWEEP_RATE_DEG_S 속도로 천천히 이동. */
async function panSlowMoveTo(target: number) {
  const stepDeg = (SWEEP_RATE_DEG_S * SWEEP_TICK_MS) / 1000;  // 1°/tick @ 10 Hz
  while (panTarget.value !== target) {
    const diff = target - panTarget.value;
    const step = Math.sign(diff) * Math.min(stepDeg, Math.abs(diff));
    const next = Math.round((panTarget.value + step) * 10) / 10;
    panTarget.value = Math.abs(next - target) < 0.5 ? target : Math.round(next);
    await publishPan(panTarget.value, true);
    await sleep(SWEEP_TICK_MS);
  }
}

async function onVoiceSearch() {
  try {
    await sendHint('search');
    showToast('hint: search → VOICE_SEARCH');
  } catch (e) {
    showToast(`search 실패: ${(e as Error).message}`);
  }
}

async function onVoiceResume() {
  try {
    await sendHint('resume');
    showToast('hint: resume → VOICE_RESUME');
  } catch (e) {
    showToast(`resume 실패: ${(e as Error).message}`);
  }
}

async function onHint(direction: HintDirection) {
  if (isSweeping.value) {
    showToast('이미 sweep 중');
    return;
  }
  // 1) follow_node 로 hint 발행 (WAITING_HINT 모드면 처리, 아니면 무시 — STT 통합 대비)
  sendHint(direction).catch(() => { /* 실패 무시 — sweep 시뮬은 계속 */ });

  // 2) frontend 가 직접 PAN sweep 시뮬 — 실제 카메라 회전 시각화
  isSweeping.value = true;
  showToast(`sweep 시작: ${direction}`);
  try {
    if (direction === 'back') {
      // base 180° 회전은 UI 미지원 → 좌측 끝 ↔ 우측 끝 양쪽 sweep
      await panSlowMoveTo(5);
      await sleep(SWEEP_DWELL_MS / 2);
      await panSlowMoveTo(175);
      await sleep(SWEEP_DWELL_MS / 2);
    } else {
      const target = HINT_PAN_TARGET[direction];
      await panSlowMoveTo(target);
      await sleep(SWEEP_DWELL_MS);
    }
    await panSlowMoveTo(90);
    showToast(`sweep 완료: ${direction} → home`);
  } catch (e) {
    showToast(`sweep 중단: ${(e as Error).message}`);
  } finally {
    isSweeping.value = false;
  }
}

const statusLabel = computed(() => {
  if (!state.value.active) return 'idle';
  if (state.value.matched) return 'tracking';
  return 'searching';
});

const statusColor = computed(() => {
  switch (statusLabel.value) {
    case 'tracking': return '#3ad77b';
    case 'searching': return '#f5c14b';
    default: return '#8a8a8a';
  }
});

function fmt(n: number | null, digits = 2): string {
  return n === null ? '—' : n.toFixed(digits);
}
</script>

<template>
  <div class="debug-panel">
    <div class="header">
      디버그 패널
      <span class="badge">DEV / ?debug=1</span>
    </div>

    <section class="section">
      <h3>
        📍 TrackingState
        <span v-if="!connected" class="warn">연결 끊김</span>
      </h3>
      <div class="state-grid">
        <div>
          status:
          <strong :style="{ color: statusColor }">{{ statusLabel }}</strong>
        </div>
        <div>matched: {{ state.matched ? '✓' : '✗' }}</div>
        <div>distance: {{ fmt(state.distance_m) }} m</div>
        <div>angle: {{ fmt(state.angle_deg, 1) }}°</div>
        <div>reid_sim: {{ fmt(state.reid_sim) }}</div>
        <div>track_id: {{ state.track_id ?? '—' }}</div>
      </div>
    </section>

    <section class="section">
      <h3>
        🎤 Lost-Recovery Hint
        <span class="muted">— sweep 시뮬 + hint POST</span>
      </h3>
      <div class="hint-row">
        <button data-test="hint-btn" data-dir="left" :disabled="isSweeping" @click="onHint('left')">◀ 왼쪽</button>
        <button data-test="hint-btn" data-dir="front" :disabled="isSweeping" @click="onHint('front')">▼ 앞</button>
        <button data-test="hint-btn" data-dir="back" :disabled="isSweeping" @click="onHint('back')">▲ 뒤</button>
        <button data-test="hint-btn" data-dir="right" :disabled="isSweeping" @click="onHint('right')">▶ 오른쪽</button>
      </div>
    </section>

    <section class="section">
      <h3>🎯 Voice-Guided Search (음성 명령 시뮬)</h3>
      <div class="hint-row">
        <button data-test="voice-search-btn" :disabled="isSweeping" @click="onVoiceSearch">🔍 위치확인</button>
        <button data-test="voice-resume-btn" :disabled="isSweeping" @click="onVoiceResume">🚶 위치이동</button>
      </div>
    </section>

    <section class="section">
      <h3>🎥 PAN/TILT 직접 이동</h3>
      <div class="axis-label">PAN (5°~175°)</div>
      <div class="pan-row">
        <input
          data-test="pan-slider"
          type="range"
          min="5"
          max="175"
          step="1"
          v-model.number="panTarget"
        />
        <span class="pan-value">{{ panTarget }}°</span>
      </div>
      <div class="hint-row">
        <button data-test="pan-send" @click="publishPan(panTarget)">돌려</button>
        <button data-test="pan-home" @click="publishPan(90)">home(90°)</button>
      </div>
      <div class="axis-label">TILT (30°~150°)</div>
      <div class="pan-row">
        <input
          data-test="tilt-slider"
          type="range"
          min="30"
          max="150"
          step="1"
          v-model.number="tiltTarget"
        />
        <span class="pan-value">{{ tiltTarget }}°</span>
      </div>
      <div class="hint-row">
        <button data-test="tilt-send" @click="publishTilt(tiltTarget)">돌려</button>
        <button data-test="tilt-home" @click="publishTilt(100)">home(100°)</button>
      </div>
    </section>

    <div v-if="toast" class="toast">{{ toast }}</div>
  </div>
</template>

<style scoped>
.debug-panel {
  position: fixed;
  top: 16px;
  left: 16px;
  width: 320px;
  max-height: calc(100vh - 32px);
  overflow-y: auto;
  z-index: 9000;  /* FollowMode(30) / FollowFaceAuth(50) / HideAndSeek(80) / wake-debug(9999) 사이 — overlay 위 + 토스트 아래 */
  border: 2px dashed #f59e0b;
  background: rgba(255, 247, 230, 0.96);
  padding: 12px;
  border-radius: 8px;
  font-family: monospace;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
}
.header {
  font-weight: bold;
  margin-bottom: 8px;
}
.badge {
  background: #f59e0b;
  color: white;
  padding: 2px 6px;
  font-size: 11px;
  border-radius: 4px;
  margin-left: 6px;
}
.section { margin-bottom: 12px; }
.section h3 { margin: 0 0 6px; font-size: 14px; }
.state-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px 12px;
  font-size: 13px;
}
.hint-row { display: flex; gap: 6px; }
.hint-row button {
  padding: 6px 12px;
  cursor: pointer;
  flex: 1;
  border: 1px solid #888;
  background: white;
  border-radius: 4px;
}
.hint-row button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}
.pan-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.axis-label {
  font-size: 11px;
  color: #92400e;
  margin-top: 8px;
  margin-bottom: 4px;
  font-weight: 600;
}
.pan-row input[type="range"] { flex: 1; }
.pan-value {
  min-width: 50px;
  text-align: right;
  font-weight: bold;
}
.warn {
  color: #e35b5b;
  font-size: 12px;
  margin-left: 8px;
}
.toast {
  position: fixed;
  bottom: 16px;
  right: 16px;
  background: #333;
  color: white;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 13px;
  z-index: 9001;
}
</style>
