<script setup lang="ts">
/**
 * 율동 재생 팝업 — EduPing 의 '율동' 모드 진입 시 표시.
 *
 * 라이브러리 (GET /api/eduping/dance) 를 띄우고, 곡 선택 시 단일 양방향
 * WS (/api/eduping/dance/stream) 로 컨트롤 + audio/motion frame 을 주고받음 (useDanceStream).
 * 정지·자연 종료 시 같은 채널로 home ramp motion frame 이 흘러와 시각화 단절 없음.
 * 실물 팔/sim_twin JointTrajectory 발사도 백엔드가 WS 컨트롤에 묶어서 처리 — 별도 REST 콜 불필요.
 *
 * 녹화 기능은 본 팝업에 없음 — 녹화는 '율동 등록' 모드의 DanceManager 가 담당.
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { useModeStore } from '@/stores/mode';
import Icon from '@/common/Icon.vue';
import OpenarmViewer from './OpenarmViewer.vue';
import { useDanceStream } from './useDanceStream';

interface DanceItem {
  slug: string;
  display_name: string;
  duration_s?: number;
  recorded_at?: string;
  has_song?: boolean;
  has_motion?: boolean;
}

const mode = useModeStore();
const stream = useDanceStream();

const items = ref<DanceItem[]>([]);
const loading = ref(false);
const error = ref('');

const playingSlug = ref<string>('');
const playingItem = computed(() => items.value.find((i) => i.slug === playingSlug.value) ?? null);

const playDurationS = computed(() => stream.durationMs.value / 1000);
const playElapsedS = computed(() => stream.elapsedMs.value / 1000);
const progressPct = computed(() => {
  if (playDurationS.value <= 0) return 0;
  return Math.min(100, (playElapsedS.value / playDurationS.value) * 100);
});

stream.onEnd(() => {
  playingSlug.value = '';
});

watch(stream.error, (e) => {
  if (e) error.value = e;
});

async function refresh(): Promise<void> {
  loading.value = true;
  error.value = '';
  try {
    const res = await fetch('/api/eduping/dance');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    items.value = (json.items ?? []).filter((i: DanceItem) => i.has_motion !== false);
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}

function play(item: DanceItem): void {
  playingSlug.value = item.slug;
  error.value = '';
  stream.play(item.slug);
}

function stop(): void {
  stream.stop();
  playingSlug.value = '';
}

function close(): void {
  stream.stop();  // home ramp 시작
  mode.setMode('대기');  // 팝업 unmount → onUnmounted 가 stream.close()
}

onMounted(() => {
  void refresh();
  stream.connect();
});
onUnmounted(() => {
  stream.close();
});
</script>

<template>
  <Transition name="fade">
    <div class="popup-overlay" @click.self="close">
      <Transition name="pop" appear>
        <div class="popup-card" role="dialog" aria-modal="true" aria-label="율동 선택">
          <header class="popup-head">
            <h2>
              <Icon name="music" :size="22" />
              어떤 율동 출까요?
            </h2>
            <button type="button" class="btn-close" aria-label="닫기" @click="close">×</button>
          </header>

          <div class="popup-body">
            <div class="viewer-pane">
              <OpenarmViewer source="follower" :external-snapshot="stream.currentSnapshot.value" />
              <div v-if="playingItem" class="now-playing">
                <div class="np-name">
                  <Icon name="music" :size="16" />
                  <strong>{{ playingItem.display_name }}</strong>
                </div>
                <div class="np-progress">
                  <div class="np-bar"><div class="np-fill" :style="{ width: `${progressPct}%` }" /></div>
                  <span class="np-time">{{ playElapsedS.toFixed(1) }} / {{ playDurationS.toFixed(1) }}s</span>
                </div>
                <button type="button" class="btn-stop" @click="stop">
                  <Icon name="stop" :size="14" /> 정지
                </button>
              </div>
            </div>

            <aside class="list-pane">
              <div v-if="loading" class="hint">불러오는 중…</div>
              <div v-else-if="error" class="err">{{ error }}</div>
              <ul v-else-if="items.length > 0" class="list">
                <li
                  v-for="item in items"
                  :key="item.slug"
                  class="item"
                  :class="{ playing: item.slug === playingSlug }"
                  @click="play(item)"
                >
                  <div class="item-icon">
                    <Icon :name="item.slug === playingSlug ? 'stop' : 'play'" :size="18" />
                  </div>
                  <div class="item-meta">
                    <div class="item-name">{{ item.display_name }}</div>
                    <div class="item-sub">
                      <span v-if="item.duration_s">{{ item.duration_s.toFixed(1) }}초</span>
                      <span v-if="item.has_song === false" class="warn">곡 없음</span>
                    </div>
                  </div>
                </li>
              </ul>
              <div v-else class="hint">
                저장된 율동이 없어요.<br/>
                <small>'율동 등록' 모드에서 새 곡을 추가하세요.</small>
              </div>
            </aside>
          </div>
        </div>
      </Transition>
    </div>
  </Transition>
</template>

<style scoped>
.popup-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  z-index: 60;
}
.popup-card {
  background: white;
  width: 100dvw;
  height: 100dvh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.popup-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 32px 16px;
  background: linear-gradient(135deg, rgba(252, 231, 243, 0.9) 0%, rgba(253, 242, 248, 0.95) 100%);
  border-bottom: 1px solid rgba(236, 72, 153, 0.12);
}
.popup-head h2 {
  margin: 0;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 22px;
  color: #be185d;
  letter-spacing: -0.01em;
}
.btn-close {
  background: rgba(255, 255, 255, 0.7);
  border: none;
  width: 36px;
  height: 36px;
  border-radius: 12px;
  font-size: 26px;
  line-height: 1;
  color: #94748b;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}
.btn-close:hover { background: white; color: #475569; }

.popup-body {
  flex: 1;
  display: grid;
  grid-template-columns: 1fr clamp(320px, 32vw, 480px);
  gap: 0;
  min-height: 0;
}
.viewer-pane {
  position: relative;
  background: #f8fafc;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.viewer-pane :deep(canvas) {
  display: block;
}
/* OpenarmViewer 가 viewer-pane 을 채우도록 */
.viewer-pane > :first-child {
  flex: 1;
  min-height: 0;
}

.now-playing {
  position: absolute;
  left: 16px;
  right: 16px;
  bottom: 16px;
  background: rgba(255, 255, 255, 0.95);
  border-radius: 14px;
  padding: 12px 14px;
  box-shadow: 0 10px 30px -8px rgba(15, 23, 42, 0.25);
  display: flex;
  flex-direction: column;
  gap: 8px;
  backdrop-filter: blur(6px);
}
.np-name {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #334155;
  font-size: 15px;
}
.np-progress {
  display: flex;
  align-items: center;
  gap: 10px;
}
.np-bar {
  flex: 1;
  height: 6px;
  background: #fce7f3;
  border-radius: 999px;
  overflow: hidden;
}
.np-fill {
  height: 100%;
  background: linear-gradient(90deg, #ec4899, #f59e0b);
  border-radius: 999px;
  transition: width 0.1s linear;
}
.np-time {
  font-size: 12px;
  color: #64748b;
  font-variant-numeric: tabular-nums;
  min-width: 80px;
  text-align: right;
}
.btn-stop {
  align-self: flex-start;
  background: #fef2f2;
  color: #b91c1c;
  border: 1px solid #fecaca;
  border-radius: 10px;
  padding: 6px 14px;
  font-weight: 600;
  font-size: 13px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.btn-stop:hover { background: #fee2e2; }

.list-pane {
  background: white;
  border-left: 1px solid #f1f5f9;
  overflow-y: auto;
  padding: 14px 12px;
}
.list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border-radius: 12px;
  cursor: pointer;
  background: #fdf2f8;
  border: 1px solid transparent;
  transition: background 0.12s, border-color 0.12s, transform 0.05s;
}
.item:hover {
  background: #fce7f3;
  border-color: #f9a8d4;
}
.item:active { transform: translateY(1px); }
.item.playing {
  background: #ec4899;
  border-color: #be185d;
}
.item.playing .item-name,
.item.playing .item-sub,
.item.playing .item-icon {
  color: white;
}
.item-icon {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: rgba(236, 72, 153, 0.15);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #be185d;
  flex-shrink: 0;
}
.item.playing .item-icon {
  background: rgba(255, 255, 255, 0.25);
}
.item-meta { min-width: 0; flex: 1; }
.item-name {
  font-weight: 700;
  font-size: 15px;
  color: #334155;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.item-sub {
  margin-top: 2px;
  font-size: 12px;
  color: #94a3b8;
  display: flex;
  gap: 8px;
}
.item-sub .warn { color: #b45309; }
.hint {
  text-align: center;
  color: #94a3b8;
  font-size: 14px;
  padding: 28px 12px;
  line-height: 1.6;
}
.hint small { color: #cbd5e1; font-size: 12px; }
.err {
  color: #b91c1c;
  background: #fef2f2;
  padding: 10px 12px;
  border-radius: 10px;
  font-size: 13px;
}

/* 모바일 / 좁은 화면 — 위·아래 2단으로 */
@media (max-width: 720px) {
  .popup-body {
    grid-template-columns: 1fr;
    grid-template-rows: 1fr auto;
  }
  .list-pane {
    border-left: none;
    border-top: 1px solid #f1f5f9;
    max-height: 40vh;
  }
}

.fade-enter-active, .fade-leave-active { transition: opacity 0.18s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
.pop-enter-active { transition: opacity 0.22s ease, transform 0.22s cubic-bezier(.16,1,.3,1); }
.pop-leave-active { transition: opacity 0.16s ease, transform 0.16s ease; }
.pop-enter-from { opacity: 0; transform: scale(0.94) translateY(10px); }
.pop-leave-to { opacity: 0; transform: scale(0.97); }
</style>
