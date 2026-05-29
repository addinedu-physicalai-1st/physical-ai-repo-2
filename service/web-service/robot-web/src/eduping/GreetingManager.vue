<script setup lang="ts">
/**
 * 등하원 인사 설정 — morning / evening 슬롯 두 개. 모션만 (곡 없음).
 *
 * - GET /api/eduping/greeting           슬롯 메타 두 개
 * - 녹화/재생은 RecorderControls 가 처리.
 */
import { computed, onMounted, ref } from 'vue';
import { useModeStore } from '@/stores/mode';
import { useEdupingStateWs } from '@/composables/useEdupingStateWs';
import { useProximityOverride } from '@/composables/useProximityOverride';
import Icon from '@/common/Icon.vue';
import OpenarmViewer from './OpenarmViewer.vue';
import RecorderControls from './RecorderControls.vue';

type SlotId = 'morning' | 'evening';

interface SlotMeta {
  slot: SlotId;
  duration_s?: number;
  keyframe_count?: number;
  recorded_at?: string;
  sample_hz?: number;
}

const SLOT_LABELS: Record<SlotId, string> = {
  morning: '등원 인사',
  evening: '하원 인사',
};
const SLOT_ICONS: Record<SlotId, string> = {
  morning: 'sunrise',
  evening: 'sunset',
};

const mode = useModeStore();
const stateWs = useEdupingStateWs();
stateWs.start();
useProximityOverride();  // 등하원 인사 설정(관리) — 교사가 팔 옆에서 녹화하므로 근접 정지 우회

const slots = ref<Record<SlotId, SlotMeta | null>>({ morning: null, evening: null });
const selected = ref<SlotId>('morning');
const loading = ref(false);
const error = ref('');

const selectedMeta = computed(() => slots.value[selected.value]);

// 재생 중에는 viewer 를 follower (재생 결과) 로 전환. 종료 후 leader 로 복귀.
const isPlaying = ref(false);
let playbackTimer: number | null = null;
function onPlayed(payload: { ok: boolean; duration_s: number }): void {
  if (!payload.ok) return;
  if (playbackTimer !== null) {
    window.clearTimeout(playbackTimer);
  }
  isPlaying.value = true;
  const ms = Math.max(200, Math.round(payload.duration_s * 1000));
  playbackTimer = window.setTimeout(() => {
    isPlaying.value = false;
    playbackTimer = null;
  }, ms);
}

async function refresh(): Promise<void> {
  loading.value = true;
  error.value = '';
  try {
    const res = await fetch('/api/eduping/greeting');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    slots.value = (json.slots ?? { morning: null, evening: null }) as Record<SlotId, SlotMeta | null>;
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}

function close(): void {
  mode.setMode('대기');
}

onMounted(refresh);
</script>

<template>
  <div class="greeting-mgr">
    <header class="bar">
      <h2>등하원 인사 설정</h2>
      <button type="button" class="btn-close" @click="close">닫기</button>
    </header>

    <div v-if="!stateWs.leaderActive.value" class="leader-warning">
      <Icon name="alert" :size="18" />
      <strong>리더 디바이스가 연결되어 있지 않습니다.</strong>
      녹화·재생을 사용하려면 리더 디바이스를 먼저 켜주세요 —
      <code>scripts/device-eduping-leader.sh 3</code>
    </div>

    <div class="grid">
      <div class="viewer">
        <OpenarmViewer :source="isPlaying ? 'follower' : 'leader'" />
      </div>

      <aside class="side">
        <div class="slot-tabs">
          <button
            v-for="slot in (['morning', 'evening'] as SlotId[])"
            :key="slot"
            type="button"
            class="tab"
            :class="{ active: selected === slot }"
            @click="selected = slot"
          >
            <Icon :name="SLOT_ICONS[slot]" :size="16" />
            {{ SLOT_LABELS[slot] }}
          </button>
        </div>

        <section class="slot-card">
          <h3>
            <Icon :name="SLOT_ICONS[selected]" :size="18" />
            {{ SLOT_LABELS[selected] }}
          </h3>

          <div v-if="loading" class="muted">로딩…</div>
          <div v-else-if="error" class="err">{{ error }}</div>
          <div v-else>
            <div v-if="selectedMeta" class="meta">
              <div><strong>녹화일</strong> {{ selectedMeta.recorded_at || '—' }}</div>
              <div><strong>길이</strong> {{ selectedMeta.duration_s?.toFixed(2) ?? '—' }} s</div>
              <div><strong>키프레임</strong> {{ selectedMeta.keyframe_count ?? '—' }}</div>
              <div><strong>샘플레이트</strong> {{ selectedMeta.sample_hz ?? '—' }} Hz</div>
            </div>
            <div v-else class="muted">
              아직 녹화 안 됨 — 아래 [녹화 시작] 으로 첫 녹화를 시작하세요.
            </div>
          </div>

          <RecorderControls
            kind="greeting"
            :name="selected"
            @recorded="refresh"
            @played="onPlayed"
          />
        </section>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.greeting-mgr {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  background: rgba(247, 251, 255, 0.96);
  z-index: 50;
}
.bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 24px;
  background: rgba(37, 99, 235, 0.08);
}
.leader-warning {
  margin: 12px 24px 0;
  padding: 10px 14px;
  background: #fef3c7;
  color: #78350f;
  border: 1px solid #f59e0b;
  border-radius: 8px;
  font-size: 14px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.leader-warning code {
  background: rgba(0, 0, 0, 0.06);
  padding: 1px 6px;
  border-radius: 4px;
  font-family: 'SF Mono', Menlo, monospace;
  font-size: 13px;
}
.bar h2 { margin: 0; font-size: 22px; color: #1d4ed8; }
.btn-close {
  padding: 6px 14px;
  background: white;
  border: 1px solid #d0e0f0;
  border-radius: 8px;
  cursor: pointer;
  font-weight: 600;
  color: #475569;
}
.grid {
  flex: 1;
  display: grid;
  grid-template-columns: 1fr 380px;
  gap: 14px;
  padding: 14px 24px 24px;
  min-height: 0;
}
.viewer { min-height: 0; }
.side { display: flex; flex-direction: column; gap: 12px; overflow-y: auto; }

.slot-tabs {
  display: flex;
  gap: 6px;
  background: rgba(255,255,255,0.5);
  padding: 4px;
  border-radius: 10px;
}
.tab {
  flex: 1;
  padding: 10px;
  border: none;
  background: transparent;
  font-weight: 600;
  color: #64748b;
  cursor: pointer;
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}
.tab.active {
  background: white;
  color: #1d4ed8;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}

.slot-card {
  background: rgba(255,255,255,0.9);
  padding: 14px;
  border-radius: 12px;
}
.slot-card h3 {
  margin: 0 0 12px 0;
  font-size: 18px;
  color: #334155;
  display: flex;
  align-items: center;
  gap: 8px;
}
.meta {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px 16px;
  font-size: 13px;
  color: #475569;
  margin-bottom: 12px;
  padding: 10px;
  background: #f1f5f9;
  border-radius: 8px;
}
.meta strong { display: block; color: #94a3b8; font-weight: 500; font-size: 11px; text-transform: uppercase; }
.muted { color: #94a3b8; padding: 12px 0; }
.err {
  color: #c14545;
  background: #fef2f2;
  padding: 6px 10px;
  border-radius: 8px;
  font-size: 13px;
}
</style>
