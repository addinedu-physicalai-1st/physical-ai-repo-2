<script setup lang="ts">
/**
 * 순찰 단계 — 모든 웨이포인트를 한 번씩 지나가면서 노드마다 카메라 회전.
 * 메인은 GogoPing 라이브 카메라 화면 (CameraView). 우측에 웨이포인트 진행,
 * 하단에 참가자 상태 strip. 발견 토스트는 카메라 위에 띄움.
 *
 * 카메라뷰 위에 `useHideSeekRecognition` 인식 파이프라인을 mount —
 * 매 frame face detect + identify, 등록자 매칭 시 음성 호명 + caught API +
 * 부모로 caught 이벤트 emit. 로봇은 정지하지 않고 다음 노드로 계속 진행.
 */
import { computed, inject, onBeforeUnmount, onMounted, ref } from 'vue';
import CameraView from '../CameraView.vue';
import type { CaptureBanner, Participant } from '../useHideAndSeekState';
import type { Waypoint } from '../fixtures';
import { VOICE_CONTROLLER_KEY } from '@/composables/voiceControllerKey';
import { useHideSeekRecognition } from '../composables/useHideSeekRecognition';
import { postCaught } from '../api/hideseekApi';

const props = defineProps<{
  waypoints: Waypoint[];
  currentIdx: number;
  waypointStatus: (idx: number) => 'visited' | 'rotating' | 'pending';
  participants: Participant[];
  captureBanners: CaptureBanner[];
}>();

const emit = defineEmits<{
  caught: [childId: number, childName: string, waypointLabel: string | undefined];
}>();

const total = computed(() => props.waypoints.length);
const visitedCount = computed(() =>
  Math.max(0, Math.min(props.currentIdx, total.value)),
);
const remaining = computed(() => Math.max(0, total.value - visitedCount.value));
const currentLabel = computed(() => {
  if (props.currentIdx < 0 || props.currentIdx >= total.value) return null;
  return props.waypoints[props.currentIdx].label;
});

const hidingParticipants = computed(() =>
  props.participants.filter((p) => p.registered && !p.caught),
);
const caughtParticipants = computed(() =>
  props.participants.filter((p) => p.registered && p.caught),
);

const voiceController = inject(VOICE_CONTROLLER_KEY);
const cameraViewRef = ref<{ getImgEl: () => HTMLImageElement | null } | null>(null);
const captureCanvasRef = ref<HTMLCanvasElement | null>(null);
const cameraImgEl = computed(() => cameraViewRef.value?.getImgEl() ?? null);

const currentWaypointLabel = computed<string | undefined>(() => {
  if (props.currentIdx < 0 || props.currentIdx >= props.waypoints.length) return undefined;
  return props.waypoints[props.currentIdx].label;
});

const recognition = useHideSeekRecognition({
  imgEl: cameraImgEl,
  captureCanvas: captureCanvasRef,
  isRegistered: (id) => props.participants.find((p) => p.id === id)?.registered ?? false,
  isCaught: (id) => props.participants.find((p) => p.id === id)?.caught ?? false,
  onCaught: (childId, childName) => {
    voiceController?.speak(`${childName} 찾았다!`);
    void postCaught(childId, currentWaypointLabel.value);
    emit('caught', childId, childName, currentWaypointLabel.value);
  },
});

onMounted(() => recognition.start());
onBeforeUnmount(() => recognition.stop());
</script>

<template>
  <section class="patrol">
    <header class="patrol-head">
      <div class="header-row">
        <h2 class="title">친구들을 찾는 중…</h2>
        <div class="progress">{{ visitedCount }} / {{ total }} 곳 확인</div>
      </div>
      <div v-if="currentLabel" class="now">
        지금: <strong>{{ currentLabel }}</strong>
        <span class="rotate-tag">📷 회전 중</span>
      </div>
    </header>

    <div class="body">
      <!-- 카메라 — 라이브 영상 (useVideoStream + CAMERA_PAN_KEY 주입은 App.vue 에서 처리) -->
      <div class="camera-wrap">
        <CameraView ref="cameraViewRef" />
        <canvas ref="captureCanvasRef" hidden />
        <div class="banners">
          <TransitionGroup name="banner">
            <div
              v-for="b in captureBanners"
              :key="b.id"
              class="banner"
            >
              🎯 <strong>{{ b.participantName }}</strong> 찾았다!
              <span class="banner-where">{{ b.waypointLabel }}</span>
            </div>
          </TransitionGroup>
        </div>
      </div>

      <!-- 웨이포인트 진행 (세로 스택) -->
      <ol class="waypoints">
        <li
          v-for="(wp, idx) in waypoints"
          :key="wp.key"
          class="wp"
          :class="waypointStatus(idx)"
        >
          <div class="wp-marker">
            <span v-if="waypointStatus(idx) === 'visited'">✓</span>
            <span v-else-if="waypointStatus(idx) === 'rotating'" class="cam">📷</span>
            <span v-else>{{ idx + 1 }}</span>
          </div>
          <div class="wp-text">
            <div class="wp-label">{{ wp.label }}</div>
            <div class="wp-status">
              <template v-if="waypointStatus(idx) === 'visited'">확인 완료</template>
              <template v-else-if="waypointStatus(idx) === 'rotating'">카메라 회전 중</template>
              <template v-else>대기 중</template>
            </div>
          </div>
        </li>
      </ol>
    </div>

    <footer class="patrol-foot">
      <div class="participants">
        <div class="grp">
          <div class="grp-title">숨은 친구 <strong>{{ hidingParticipants.length }}</strong></div>
          <ul>
            <li v-for="p in hidingParticipants" :key="p.id" class="chip hiding">
              {{ p.name }}
            </li>
            <li v-if="hidingParticipants.length === 0" class="empty">모두 찾았어요!</li>
          </ul>
        </div>
        <div class="grp">
          <div class="grp-title">잡힌 친구 <strong>{{ caughtParticipants.length }}</strong></div>
          <ul>
            <li v-for="p in caughtParticipants" :key="p.id" class="chip caught">
              {{ p.name }}
              <span v-if="p.caughtAt" class="where">@ {{ p.caughtAt }}</span>
            </li>
            <li v-if="caughtParticipants.length === 0" class="empty">아직 없음</li>
          </ul>
        </div>
      </div>
      <div class="remaining">{{ remaining }} 곳 남았어요</div>
    </footer>
  </section>
</template>

<style scoped>
.patrol {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 18px 24px 16px;
  gap: 12px;
}
.patrol-head .header-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}
.title {
  margin: 0;
  font-size: 22px;
  font-weight: 800;
  color: #166534;
}
.progress {
  font-size: 13px;
  color: #4b5563;
  background: rgba(22, 163, 74, 0.08);
  padding: 4px 12px;
  border-radius: 999px;
}
.now {
  margin-top: 4px;
  font-size: 14px;
  color: #4b5563;
}
.now strong { color: #15803d; }
.rotate-tag {
  margin-left: 10px;
  padding: 3px 10px;
  border-radius: 999px;
  background: rgba(251, 191, 36, 0.2);
  border: 1px solid #fbbf24;
  color: #92400e;
  font-size: 12px;
  font-weight: 700;
}

.body {
  display: grid;
  grid-template-columns: 1fr 220px;
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

.waypoints {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  overflow-y: auto;
  overflow-x: hidden;
  min-width: 0;
}
.wp {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 12px;
  border: 2px solid rgba(0, 0, 0, 0.08);
  background: rgba(255, 255, 255, 0.85);
  transition: border-color 0.18s ease, transform 0.18s ease;
}
.wp.visited { border-color: #16a34a; background: rgba(220, 252, 231, 0.9); }
.wp.rotating {
  border-color: #fbbf24;
  background: rgba(254, 243, 199, 0.95);
  transform: scale(1.02);
  box-shadow: 0 6px 18px rgba(251, 191, 36, 0.25);
}
.wp-marker {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.08);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 800;
  color: #4b5563;
  flex-shrink: 0;
  font-size: 14px;
}
.wp.visited .wp-marker { background: #16a34a; color: white; }
.wp.rotating .wp-marker { background: #fbbf24; color: #78350f; }
.wp.rotating .cam {
  display: inline-block;
  animation: cam-rotate 1.6s linear infinite;
}
@keyframes cam-rotate {
  0% { transform: rotate(-20deg); }
  50% { transform: rotate(20deg); }
  100% { transform: rotate(-20deg); }
}
.wp-text { min-width: 0; flex: 1; }
.wp-label {
  font-size: 13px;
  font-weight: 700;
  color: #111827;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.wp-status {
  font-size: 11px;
  color: #6b7280;
  margin-top: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.patrol-foot {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  padding-top: 8px;
  border-top: 1px solid rgba(0, 0, 0, 0.06);
  gap: 14px;
}
.participants {
  display: flex;
  gap: 18px;
  flex: 1;
}
.grp { flex: 1; min-width: 0; }
.grp-title { font-size: 12px; color: #4b5563; margin-bottom: 4px; }
.grp-title strong {
  font-size: 15px;
  color: #166534;
  margin-left: 4px;
}
.grp ul { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 6px; }
.chip {
  padding: 3px 9px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  background: rgba(22, 163, 74, 0.12);
  color: #166534;
}
.chip.caught {
  background: rgba(156, 163, 175, 0.2);
  color: #6b7280;
  text-decoration: line-through;
}
.chip .where {
  margin-left: 6px;
  font-size: 11px;
  font-weight: 500;
  text-decoration: none;
}
.empty { font-size: 11px; color: #9ca3af; padding: 3px 0; }

.remaining {
  font-size: 13px;
  color: #4b5563;
  padding: 6px 12px;
  border-radius: 999px;
  background: rgba(251, 191, 36, 0.15);
  border: 1px dashed #fbbf24;
  white-space: nowrap;
}

.banners {
  position: absolute;
  top: 12px;
  left: 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  pointer-events: none;
  z-index: 10;
}
.banner {
  background: rgba(22, 163, 74, 0.95);
  color: white;
  padding: 9px 14px;
  border-radius: 14px;
  font-size: 14px;
  font-weight: 700;
  box-shadow: 0 6px 18px rgba(22, 163, 74, 0.4);
}
.banner-where {
  margin-left: 8px;
  font-size: 12px;
  font-weight: 500;
  opacity: 0.85;
}
.banner-enter-active, .banner-leave-active {
  transition: opacity 0.25s ease, transform 0.25s ease;
}
.banner-enter-from { opacity: 0; transform: translateY(-10px); }
.banner-leave-to   { opacity: 0; transform: translateX(-20px); }

@media (max-width: 768px), (pointer: coarse) {
  .body {
    grid-template-columns: 1fr;
    grid-template-rows: minmax(0, 1fr) auto;
  }
  /* 가로 스크롤 대신 wrap — 2 열 칩 그리드 */
  .waypoints {
    flex-direction: row;
    flex-wrap: wrap;
    overflow: hidden;
    max-height: none;
  }
  .wp {
    flex: 1 1 calc(50% - 3px);
    min-width: 0;
  }
}
</style>
