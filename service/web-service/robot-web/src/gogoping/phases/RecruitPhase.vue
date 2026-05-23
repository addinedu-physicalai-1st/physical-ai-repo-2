<script setup lang="ts">
/**
 * 숨바꼭질 모집 단계.
 * 좌: GogoPing 라이브 카메라 + 얼굴 자동 등록 (face tracker 캐시).
 * 우: 등록 어린이 명단 카드 — 카드 탭으로 수동 토글 가능.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import CameraView from '../CameraView.vue';
import type { Participant } from '../useHideAndSeekState';
import { useFaceDetector } from '@/composables/useFaceDetector';
import { useFaceTracker, type TrackedFace } from '@/composables/useFaceTracker';
import { useFaceIdentityCache, type IdentityResult } from '@/composables/useFaceIdentityCache';
import { mapMatchesToTracks, postRecognizeMulti } from '@/composables/identifyTracksFromFrame';

const props = defineProps<{
  participants: Participant[];
  registeredCount: number;
}>();

const emit = defineEmits<{
  toggle: [id: number];
  register: [id: number];
  start: [];
}>();

const canStart = computed(() => props.registeredCount > 0);

const DEVICE_TOKEN = import.meta.env.VITE_ROBOT_TOKEN ?? 'dev-robot-token-change-me';
const STABLE_FRAMES_REQUIRED = 5;

const cameraViewRef = ref<{ getImgEl: () => HTMLImageElement | null } | null>(null);
const captureCanvasRef = ref<HTMLCanvasElement | null>(null);
const cameraImgEl = computed(() => cameraViewRef.value?.getImgEl() ?? null);

const tracker = useFaceTracker();
let latestTracks: TrackedFace[] = [];

const identityCache = useFaceIdentityCache({
  stableFramesRequired: STABLE_FRAMES_REQUIRED,
  identify: async (tracks): Promise<IdentityResult[]> => identifyTracks(tracks),
});

const detector = useFaceDetector({
  onDetections: (faces) => {
    latestTracks = tracker.update(faces.map((f) => ({ bbox: f.bbox })));
    void identityCache.feed(latestTracks).then(applyBindings);
  },
});

let rafId: number | null = null;

async function identifyTracks(tracks: TrackedFace[]): Promise<IdentityResult[]> {
  const canvas = captureCanvasRef.value;
  if (!canvas) return [];
  const blob = await new Promise<Blob | null>((resolve) =>
    canvas.toBlob((b) => resolve(b), 'image/jpeg', 0.85),
  );
  if (!blob) return [];
  const matches = await postRecognizeMulti(blob, DEVICE_TOKEN);
  return mapMatchesToTracks(tracks, matches).map((p) => p.result);
}

function applyBindings(): void {
  for (const t of latestTracks) {
    const childId = identityCache.getChildId(t.trackId);
    if (childId == null) continue;
    const p = props.participants.find((x) => x.id === childId);
    if (!p || p.registered) continue;
    emit('register', childId);
  }
}

async function loop(): Promise<void> {
  const img = cameraImgEl.value;
  const canvas = captureCanvasRef.value;
  if (img && canvas && img.complete && img.naturalWidth > 0) {
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    const ctx = canvas.getContext('2d');
    if (ctx) {
      ctx.drawImage(img, 0, 0);
      try { await detector.send(canvas); } catch { /* noop */ }
    }
  }
  rafId = requestAnimationFrame(() => { void loop(); });
}

onMounted(() => {
  detector.start();
  rafId = requestAnimationFrame(() => { void loop(); });
});

onBeforeUnmount(() => {
  if (rafId !== null) cancelAnimationFrame(rafId);
  rafId = null;
  detector.close();
  tracker.reset();
  identityCache.reset();
  latestTracks = [];
});
</script>

<template>
  <section class="recruit">
    <header class="recruit-head">
      <h2 class="title">숨바꼭질 모집 중</h2>
      <p class="sub">카메라 앞에 모이면 자동으로 등록돼요. 카드를 탭해서 직접 등록/취소도 가능.</p>
    </header>

    <div class="body">
      <div class="camera-wrap">
        <CameraView ref="cameraViewRef" />
        <canvas ref="captureCanvasRef" hidden />
      </div>

      <ul class="roster">
        <li
          v-for="p in participants"
          :key="p.id"
          class="card"
          :class="{ registered: p.registered }"
          :title="p.registered ? '참가 — 탭하면 취소' : '미참가 — 탭하면 참가'"
          @click="emit('toggle', p.id)"
        >
          <div class="avatar">
            <span class="initial">{{ p.name.charAt(0) }}</span>
            <span v-if="p.registered" class="check">✓</span>
          </div>
          <div class="meta">
            <div class="name">{{ p.name }}</div>
            <div class="status">{{ p.registered ? '참가' : '대기' }}</div>
          </div>
        </li>
      </ul>
    </div>

    <footer class="actions">
      <div class="count">
        등록 <strong>{{ registeredCount }}</strong> / {{ participants.length }}
      </div>
      <button
        type="button"
        class="start-btn"
        :disabled="!canStart"
        @click="emit('start')"
      >
        모집 마치고 출발
      </button>
    </footer>
  </section>
</template>

<style scoped>
.recruit {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 18px 24px 16px;
  gap: 12px;
}
.recruit-head .title {
  margin: 0;
  font-size: 24px;
  font-weight: 800;
  color: #166534;
  letter-spacing: -0.5px;
}
.recruit-head .sub {
  margin: 4px 0 0;
  color: #4b5563;
  font-size: 13px;
}

.body {
  display: grid;
  grid-template-columns: 1fr 260px;
  gap: 14px;
  flex: 1;
  min-height: 0;
}
.camera-wrap {
  position: relative;
  border-radius: 14px;
  overflow: hidden;
  background: #000;
  box-shadow: 0 8px 22px rgba(0, 0, 0, 0.25);
  min-height: 0;
}

.roster {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  overflow-y: auto;
  overflow-x: hidden;
  min-width: 0;
}
.card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.9);
  border: 2px solid rgba(0, 0, 0, 0.08);
  cursor: pointer;
  transition: transform 0.12s ease, border-color 0.18s ease, box-shadow 0.18s ease;
  user-select: none;
  min-width: 0;
}
.card:hover { transform: translateY(-1px); }
.card.registered {
  border-color: #16a34a;
  box-shadow: 0 6px 14px rgba(22, 163, 74, 0.18);
  background: rgba(220, 252, 231, 0.95);
}
.avatar {
  position: relative;
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: linear-gradient(135deg, #d4ec90 0%, #a3e635 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  font-weight: 800;
  color: #14532d;
  flex-shrink: 0;
}
.card.registered .avatar {
  background: linear-gradient(135deg, #86efac 0%, #16a34a 100%);
  color: white;
}
.check {
  position: absolute;
  right: -3px;
  bottom: -3px;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: #16a34a;
  color: white;
  font-size: 13px;
  font-weight: 900;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.2);
}
.meta { min-width: 0; flex: 1; }
.name {
  font-size: 15px;
  font-weight: 700;
  color: #111827;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.status {
  font-size: 11px;
  color: #6b7280;
}
.card.registered .status { color: #16a34a; font-weight: 700; }

.actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 8px;
  border-top: 1px solid rgba(0, 0, 0, 0.06);
}
.count { font-size: 14px; color: #374151; }
.count strong { color: #16a34a; font-size: 20px; margin: 0 4px; }

.start-btn {
  padding: 10px 24px;
  border: none;
  border-radius: 999px;
  background: linear-gradient(135deg, #16a34a 0%, #15803d 100%);
  color: white;
  font-size: 15px;
  font-weight: 800;
  cursor: pointer;
  box-shadow: 0 6px 18px rgba(22, 163, 74, 0.3);
  transition: transform 0.12s ease, opacity 0.18s ease;
}
.start-btn:hover { transform: translateY(-1px); }
.start-btn:disabled {
  background: #9ca3af;
  box-shadow: none;
  cursor: not-allowed;
  opacity: 0.7;
}

@media (max-width: 768px), (pointer: coarse) {
  .body {
    grid-template-columns: 1fr;
    grid-template-rows: minmax(0, 1.2fr) minmax(0, 1fr);
  }
}
</style>
