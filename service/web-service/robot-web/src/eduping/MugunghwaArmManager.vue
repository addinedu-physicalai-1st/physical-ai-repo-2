<script setup lang="ts">
/**
 * 무궁화 율동 등록 — 무궁화꽃이 피었습니다 (SR-PLAY-004) 의 양팔 가리기 모션 단일 녹화.
 *
 * 게임 흐름: 가리기(정방향) 재생 완료 → 음악 재생(팔은 가리기 자세 정지 유지) →
 * 음악 종료 → 같은 모션 역재생(떼기). 별도 떼기 녹화 없음. 고정 속도(자연 속도)로
 * 재생한다 — 동적 변속(tempo pattern) 없음. 저장 경로 shared/openarm_mugunghwa/motion.yaml.
 * REST 경로 /api/eduping/mugunghwa/motion/{record/start,record/stop,play}.
 *
 * 박자 가이드 — `public/sounds/yeonghui_mugunghwa.mp3` (자연 속도, ~4.6s). 녹화한 가리기
 * 동작이 게임에서 그대로(고정 속도) 재생되므로, 교사는 이 박자에 맞춰 한 번의 자연스러운
 * 가리기 동작을 녹화하면 된다.
 */
import { onMounted, ref } from 'vue';
import { useModeStore } from '@/stores/mode';
import { useEdupingStateWs } from '@/composables/useEdupingStateWs';
import Icon from '@/common/Icon.vue';
import OpenarmViewer from './OpenarmViewer.vue';
import RecorderControls from './RecorderControls.vue';

const MOTION_NAME = 'motion';
// 가리기 모션 녹화에는 박자 가이드 음악·길이 제한이 없다 — 새 흐름은 녹화 모션을 고정
// 속도로 그대로 재생하므로(음악과 동기 불필요), 교사가 자유 길이로 한 번 녹화하면 된다.

interface MotionMeta {
  duration_s?: number;
  keyframe_count?: number;
  recorded_at?: string;
  sample_hz?: number;
}

const mode = useModeStore();
const stateWs = useEdupingStateWs();
stateWs.start();

const meta = ref<MotionMeta | null>(null);
const loading = ref(false);
const error = ref('');

const isPlaying = ref(false);
let playbackTimer: number | null = null;
function onPlayed(payload: { ok: boolean; duration_s: number }): void {
  if (!payload.ok) return;
  if (playbackTimer !== null) window.clearTimeout(playbackTimer);
  isPlaying.value = true;
  const ms = Math.max(200, Math.round(payload.duration_s * 1000));
  mode.setEmotionTransient('sleep', ms);
  playbackTimer = window.setTimeout(() => {
    isPlaying.value = false;
    playbackTimer = null;
  }, ms);
}

async function refresh(): Promise<void> {
  loading.value = true;
  error.value = '';
  try {
    const res = await fetch('/api/eduping/mugunghwa');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    meta.value = (json.motion as MotionMeta | null) ?? null;
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}

function close(): void {
  mode.setMode('대기');
}

onMounted(() => {
  void refresh();
});
</script>

<template>
  <div class="mugung-mgr">
    <header class="bar">
      <h2>무궁화 율동 등록</h2>
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
        <section class="slot-card">
          <h3>
            <Icon name="play" :size="18" />
            가리기 모션
          </h3>
          <p class="hint">
            노래 단계에서 재생할 양팔 가리기 모션입니다. <br />
            게임 흐름: <strong>가리기</strong>(정방향) 완료 → 음악 재생(팔은 가리기 자세로
            정지) → 음악 종료 → 같은 녹화의 <strong>떼기</strong>(역재생). 별도 떼기 녹화 없음.
            <br />
            녹화 시 음악·길이 제한 없음 — 양팔로 눈을 가리는 동작을 원하는 길이로 한 번
            녹화하세요. 게임에서는 이 녹화를 고정 속도로 그대로 재생합니다.
          </p>

          <div v-if="loading" class="muted">로딩…</div>
          <div v-else-if="error" class="err">{{ error }}</div>
          <div v-else>
            <div v-if="meta" class="meta">
              <div><strong>녹화일</strong> {{ meta.recorded_at || '—' }}</div>
              <div><strong>길이</strong> {{ meta.duration_s?.toFixed(2) ?? '—' }} s</div>
              <div><strong>키프레임</strong> {{ meta.keyframe_count ?? '—' }}</div>
              <div><strong>샘플레이트</strong> {{ meta.sample_hz ?? '—' }} Hz</div>
            </div>
            <div v-else class="muted">
              아직 녹화 안 됨 — 아래 [녹화 시작] 으로 첫 녹화를 시작하세요.
            </div>
          </div>

          <RecorderControls
            kind="mugunghwa"
            :name="MOTION_NAME"
            @recorded="refresh"
            @played="onPlayed"
          />
        </section>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.mugung-mgr {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  background: rgba(253, 242, 248, 0.96);
  z-index: 50;
}
.bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 24px;
  background: rgba(236, 72, 153, 0.10);
}
.bar h2 { margin: 0; font-size: 22px; color: #be185d; }
.btn-close {
  padding: 6px 14px;
  background: white;
  border: 1px solid #f0d0e0;
  border-radius: 8px;
  cursor: pointer;
  font-weight: 600;
  color: #6b4258;
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

.slot-card {
  background: rgba(255,255,255,0.9);
  padding: 16px;
  border-radius: 12px;
}
.slot-card h3 {
  margin: 0 0 8px 0;
  font-size: 18px;
  color: #334155;
  display: flex;
  align-items: center;
  gap: 8px;
}
.hint {
  margin: 0 0 14px;
  font-size: 13px;
  color: #6b4258;
  line-height: 1.6;
}
.hint strong { color: #be185d; font-weight: 700; }
.meta {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px 16px;
  font-size: 13px;
  color: #475569;
  margin-bottom: 12px;
}
.meta strong {
  color: #be185d;
  font-weight: 700;
  margin-right: 4px;
}
.muted { color: #94a3b8; font-size: 13px; margin-bottom: 12px; }
.err {
  color: #b91c1c;
  background: #fef2f2;
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 13px;
  margin-bottom: 12px;
}
</style>
