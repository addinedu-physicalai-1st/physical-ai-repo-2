<script setup lang="ts">
import { inject, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { VIDEO_STREAM_KEY } from '@/gogoping/videoStreamKey';
import { forceReconnectWebRTCStream, useWebRTCStream } from '@/gogoping/composables/useWebRTCStream';

const props = defineProps<{
  /** true 면 스트림 연결하고 매칭 시도. false 면 teardown. */
  active: boolean;
}>();

const emit = defineEmits<{
  (e: 'authenticated', payload: { name: string; teacher_id: string }): void;
  (e: 'cancel'): void;
}>();

interface MatchResult {
  matched: boolean;
  teacher_id: string | null;
  name: string | null;
  distance: number | null;
  threshold: number;
}

const DEVICE_TOKEN = import.meta.env.VITE_ROBOT_TOKEN ?? 'dev-robot-token-change-me';
// 매 N ms 마다 한 장씩 서버로 보내 매칭 시도. 얼굴 없을 땐 server 의 InsightFace 가 빠르게
// matched=false 리턴하므로 빈 프레임 사전 필터는 불필요.
const POLL_INTERVAL_MS = 1500;

const injected = inject(VIDEO_STREAM_KEY, null);
const ownHandle = injected ? null : useWebRTCStream('robot-web');
const stream = injected ?? { stream: ownHandle!.stream, status: ownHandle!.status };

const videoEl = ref<HTMLVideoElement | null>(null);
// frame capture 용 hidden canvas — face 매칭 API 가 jpeg blob 을 받으므로 매 폴링마다 video 를 그려 toBlob.
const captureCanvas = (typeof document !== 'undefined') ? document.createElement('canvas') : null;

// watch source 에 videoEl 도 포함 — stream 이 mount 전에 set 되거나 videoEl 이
// stream set 후 mount 되는 race 모두 대응 (둘 중 늦은 쪽이 채워질 때 fire).
watch(
  [() => stream.stream.value, videoEl],
  ([s, el]) => {
    if (el) el.srcObject = s ?? null;
  },
  { immediate: true },
);

// 모드 재진입 시 stream singleton 살아있어도 video track 이 ended 상태이거나
// 디코더가 깨우지지 않는 경우를 처리.
//
// IMPORTANT: stream 이 null 인 케이스 (아직 ontrack 안 옴) 에선 forceReconnect 호출 X.
// 그 때 호출하면 healthy connecting 상태를 끊어 reconnect 폭주 발생. watch immediate 가
// 이미 stream.value 변경을 감지하고 있어 ontrack 시 자동 binding.
onMounted(async () => {
  const el = videoEl.value;
  const s = stream.stream.value;
  if (!el || !s) return;
  // track 이 dead 일 때만 강제 reconnect
  if (s.getVideoTracks().length === 0 || s.getVideoTracks().every(t => t.readyState === 'ended')) {
    forceReconnectWebRTCStream();
    return;
  }
  // 살아있는 track 이면 디코더 재시동
  el.srcObject = null;
  await nextTick();
  el.srcObject = s;
  try { await el.play(); } catch { /* autoplay policy 등 — 무시 */ }
});

const status = ref<string>('교사 얼굴을 인식 중...');

let pollTimer: number | null = null;
let busy = false;
// 인증 성공 후에도 스트림은 살려둬 "고고핑이 보는 화면" 디버그 PiP 로 표시한다.
// template 분기를 위해 ref.
const succeeded = ref(false);

function stopPolling(): void {
  // 스트림은 유지하고 폴링만 정지 — 인증 성공 후 PiP 디버그용.
  if (pollTimer !== null) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
  busy = false;
}

function teardown(): void {
  stopPolling();
  // shared stream 은 부모(App.vue)가 lifecycle 관리. own handle 인 경우만 stop.
  ownHandle?.stop();
  succeeded.value = false;
}

async function captureFrame(): Promise<Blob | null> {
  // 현재 <video> 의 프레임을 hidden canvas 에 그려 jpeg blob 으로 변환.
  // WebRTC track 이 연결돼 있고 video 가 디코딩된 시점에만 유효.
  const video = videoEl.value;
  const canvas = captureCanvas;
  if (!video || !canvas) return null;
  if (video.readyState < 2 || video.videoWidth === 0 || video.videoHeight === 0) return null;
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  ctx.drawImage(video, 0, 0);
  return await new Promise<Blob | null>((resolve) =>
    canvas.toBlob((b) => resolve(b), 'image/jpeg', 0.85),
  );
}

async function matchFace(blob: Blob): Promise<MatchResult | null> {
  const form = new FormData();
  form.append('file', blob, 'frame.jpg');
  const res = await fetch('/api/teachers/match-face', {
    method: 'POST',
    headers: { 'X-Device-Token': DEVICE_TOKEN },
    body: form,
  });
  if (!res.ok) return null;
  return (await res.json()) as MatchResult;
}

async function runRecognize(): Promise<void> {
  if (!props.active || succeeded.value || busy) return;
  busy = true;
  try {
    const blob = await captureFrame();
    if (!blob) return;
    const result = await matchFace(blob);
    if (!result) {
      status.value = '서버 오류 — 잠시 후 다시 시도해요';
      return;
    }
    if (!result.matched || !result.name) {
      status.value = '교사를 찾을 수 없어요 — 다시 카메라를 봐주세요';
      return;
    }
    succeeded.value = true;
    status.value = `${result.name} 선생님 확인`;
    emit('authenticated', { name: result.name, teacher_id: result.teacher_id ?? '' });
    // 더 이상 매칭 시도하지 않고 PiP 로 전환. 스트림만 유지.
    stopPolling();
  } finally {
    busy = false;
  }
}

watch(
  () => props.active,
  (now) => {
    if (!now) {
      teardown();
      return;
    }
    status.value = '교사 얼굴을 인식 중...';
    succeeded.value = false;
    if (pollTimer === null) {
      pollTimer = window.setInterval(() => {
        void runRecognize();
      }, POLL_INTERVAL_MS);
    }
  },
  { immediate: true },
);

onBeforeUnmount(() => {
  stopPolling();
  ownHandle?.stop();
});
</script>

<template>
  <div class="follow-auth-root" :class="{ minimized: succeeded }">
    <div v-if="!succeeded" class="backdrop" />
    <div class="auth-card">
      <video
        ref="videoEl"
        class="cam-img"
        autoplay
        playsinline
        muted
      />
      <div v-if="!stream.stream.value" class="cam-placeholder">영상 대기 중…</div>

      <template v-if="!succeeded">
        <div class="top-bar">
          <div class="title">추종 시작 — 교사 인증</div>
          <button
            type="button"
            class="close-btn"
            aria-label="인증 취소"
            @click="emit('cancel')"
          >
            ✕
          </button>
        </div>
        <div class="bottom-bar">
          <p class="status">{{ status }}</p>
          <p class="hint">전신이 화면에 들어오도록 한두 걸음 떨어져 정면을 봐주세요.</p>
        </div>
      </template>

      <div v-else class="pip-badge">● 추종 중</div>
    </div>
  </div>
</template>

<style scoped>
.follow-auth-root {
  position: absolute;
  z-index: 50;
}
.follow-auth-root:not(.minimized) {
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}
.follow-auth-root.minimized {
  top: 16px;
  left: 16px;
}
.backdrop {
  position: absolute;
  inset: 0;
  background: rgba(20, 30, 25, 0.55);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
}
.auth-card {
  position: relative;
  background: #000;
  border-radius: 18px;
  overflow: hidden;
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.4);
}
.follow-auth-root:not(.minimized) .auth-card {
  width: min(560px, 80vw);
  aspect-ratio: 4 / 3;
}
.follow-auth-root.minimized .auth-card {
  width: 240px;
  aspect-ratio: 4 / 3;
  border: 2px solid rgba(255, 255, 255, 0.55);
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.45);
}
.cam-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.cam-placeholder {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #aaa;
}
.top-bar {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  padding: 12px 14px;
  display: flex;
  align-items: center;
  gap: 10px;
  background: linear-gradient(to bottom, rgba(0, 0, 0, 0.6), rgba(0, 0, 0, 0));
  pointer-events: none;
}
.title {
  font-size: 18px;
  font-weight: 800;
  color: white;
  letter-spacing: -0.4px;
  text-shadow: 0 2px 8px rgba(0, 0, 0, 0.6);
  flex: 1;
}
.close-btn {
  pointer-events: auto;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: 1px solid rgba(255, 255, 255, 0.4);
  background: rgba(0, 0, 0, 0.55);
  color: white;
  font-size: 15px;
  font-weight: 700;
  cursor: pointer;
  font-family: inherit;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.close-btn:hover { background: rgba(0, 0, 0, 0.75); }
.bottom-bar {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 14px 14px 18px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  background: linear-gradient(to top, rgba(0, 0, 0, 0.7), rgba(0, 0, 0, 0));
}
.status {
  margin: 0;
  text-align: center;
  font-size: 17px;
  font-weight: 800;
  color: white;
  text-shadow: 0 2px 8px rgba(0, 0, 0, 0.7);
}
.hint {
  margin: 0;
  text-align: center;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.78);
  text-shadow: 0 1px 4px rgba(0, 0, 0, 0.6);
}
.pip-badge {
  position: absolute;
  top: 6px;
  left: 8px;
  padding: 2px 8px;
  background: rgba(34, 197, 94, 0.88);
  color: white;
  font-size: 11px;
  font-weight: 800;
  border-radius: 999px;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.4);
  letter-spacing: 0.3px;
}

@media (max-width: 768px), (pointer: coarse) {
  .follow-auth-root:not(.minimized) .auth-card { width: 88vw; }
  .title { font-size: 15px; }
  .close-btn { width: 28px; height: 28px; font-size: 13px; }
  .bottom-bar { padding: 10px 12px 14px; }
  .status { font-size: 14px; }
  .hint { font-size: 11px; }
  .follow-auth-root.minimized .auth-card { width: 180px; }
}
</style>
