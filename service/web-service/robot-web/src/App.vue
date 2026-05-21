<script setup lang="ts">
import { computed, onBeforeUnmount, provide, ref } from 'vue';
import { storeToRefs } from 'pinia';
import { useModeStore } from '@/stores/mode';
import { useVoiceStore } from '@/stores/voice';
import { useVoiceController, type VoiceController } from '@/composables/useVoiceController';
import { VOICE_CONTROLLER_KEY } from '@/composables/voiceControllerKey';
import { useModeAnnouncer } from '@/composables/useModeAnnouncer';
import { postModeClick } from '@/composables/useIntentDispatch';
import EmotionDisplay from '@/common/EmotionDisplay.vue';
import ModeSelectorFab from '@/common/ModeSelectorFab.vue';
import BottomDock from '@/common/BottomDock.vue';
import StartOverlay from '@/common/StartOverlay.vue';
import AttendanceCamera from '@/eduping/AttendanceCamera.vue';
import DanceManager from '@/eduping/DanceManager.vue';
import DancePlayPopup from '@/eduping/DancePlayPopup.vue';
import GreetingManager from '@/eduping/GreetingManager.vue';
import MugunghwaArmManager from '@/eduping/MugunghwaArmManager.vue';
import MugunghwaGame from '@/eduping/MugunghwaGame.vue';
import OXQuiz from '@/noriarm/OXQuiz.vue';
import BlockStacking from '@/noriarm/BlockStacking.vue';
import { useCameraPan } from '@/gogoping/composables/useCameraPan';
import { CAMERA_PAN_KEY } from '@/gogoping/cameraPanKey';
import { useGogopingStateWs } from '@/gogoping/composables/useGogopingStateWs';
import CameraView from '@/gogoping/CameraView.vue';
import PanTiltControl from '@/gogoping/PanTiltControl.vue';
import FollowFaceAuth from '@/gogoping/FollowFaceAuth.vue';
import HideAndSeekGame from '@/gogoping/HideAndSeekGame.vue';
import AdminOpenArmEmbed from '@/admin/AdminOpenArmEmbed.vue';
import AdminOpenArmCompare from '@/admin/AdminOpenArmCompare.vue';

// `?embed=openarm`         → fullscreen OpenArm viewer for the PyQt admin app
// `?embed=openarm-compare` → side-by-side two-viewer comparison popup
const embedMode = (() => {
  if (typeof window === 'undefined') return null;
  try {
    return new URLSearchParams(window.location.search).get('embed');
  } catch {
    return null;
  }
})();
const isAdminOpenArmEmbed = embedMode === 'openarm';
const isAdminOpenArmCompare = embedMode === 'openarm-compare';

const mode = useModeStore();
const voice = useVoiceStore();
const { robot, currentEmotion, currentMode } = storeToRefs(mode);
const { lastError } = storeToRefs(voice);

function clearVoiceError(): void {
  voice.setError(null);
}

const attendanceMode = computed<'IN' | 'OUT' | null>(() => {
  if (robot.value.id !== 'eduping') return null;
  if (currentMode.value === '등원') return 'IN';
  if (currentMode.value === '하원') return 'OUT';
  return null;
});

const showOXQuiz = computed(() => robot.value.id === 'noriarm');
const showDanceManager = computed(() => robot.value.id === 'eduping' && currentMode.value === '율동 등록');
const showDancePopup = computed(() => robot.value.id === 'eduping' && currentMode.value === '율동');
const showGreetingManager = computed(() => robot.value.id === 'eduping' && currentMode.value === '등하원 인사 설정');
const showMugunghwaArm = computed(() => robot.value.id === 'eduping' && currentMode.value === '무궁화 율동 등록');
const showMugunghwa = computed(() => robot.value.id === 'eduping' && currentMode.value === '무궁화꽃이 피었습니다');

const showGogopingManual = computed(
  () => robot.value.id === 'gogoping' && currentMode.value === '수동'
);

// gogoping 일 때만 useCameraPan 인스턴스를 생성해서 두 컴포넌트 공유
const cameraPan = robot.value.id === 'gogoping' ? useCameraPan() : null;
if (cameraPan) provide(CAMERA_PAN_KEY, cameraPan);

// gogoping 일 때만 BT snapshot WS 구독 — admin UI 가 mode 바꾸면 자동 반영
const gogopingStateWs = robot.value.id === 'gogoping' ? useGogopingStateWs() : null;

onBeforeUnmount(() => {
  cameraPan?.stop();
  gogopingStateWs?.stop();
});

const voiceController: VoiceController = useVoiceController(robot.value);
provide(VOICE_CONTROLLER_KEY, voiceController);

// 추종 모드 동안 FollowFaceAuth 가 항상 mount — 인증 전엔 중앙 모달, 인증 후엔 좌상단 PiP 로
// 디버그용 카메라 뷰를 유지. 모드를 벗어나면 unmount 되며 카메라 정지.
const showGogopingFollowAuth = computed(
  () => robot.value.id === 'gogoping' && currentMode.value === '추종'
);

const isHideAndSeek = computed<boolean>(
  () => robot.value.id === 'gogoping' && currentMode.value === '숨바꼭질',
);

async function onFollowAuthenticated(_name: string): Promise<void> {
  voiceController.speak('선생님 확인 완료, 추종을 시작합니다.');
  try {
    await postModeClick('추종', robot.value.id);
  } catch {
    /* BT 미연결이어도 UI 는 진행 */
  }
}

async function onFollowAuthCancel(): Promise<void> {
  // 인증 취소 — 모드를 대기로 되돌리면 showGogopingFollowAuth=false → 오버레이 unmount + 카메라 정지.
  mode.setMode('대기');
  try {
    await postModeClick('대기', robot.value.id);
  } catch {
    /* 무시 */
  }
}

// 모드 전환 시 voiceController.speak 로 서버 TTS 안내, BGM mp3 도 같이 처리.
useModeAnnouncer(voiceController, {
  자장가: { src: '/audio/lullaby.mp3', loop: true, volume: 0.7 },
});

const started = ref(false);

function handleStart(): void {
  // 첫 user gesture — WebRTC PC + wake ONNX + 마이크 권한. voice 모드일 때만.
  if (voice.voiceMode === 'voice') voiceController.start();
  started.value = true;
}
</script>

<template>
  <!-- Embed mode for the PyQt admin app's QWebEngineView — fullscreen OpenArm
       viewer, no overlays/voice/mode-selector. -->
  <AdminOpenArmEmbed v-if="isAdminOpenArmEmbed" />
  <AdminOpenArmCompare v-else-if="isAdminOpenArmCompare" />
  <div v-else class="app" :class="`bg-${robot.id}`">
    <EmotionDisplay :emotion="currentEmotion" />
    <BottomDock />
    <ModeSelectorFab />
    <div class="brand">{{ robot.displayName }}</div>
    <AttendanceCamera :mode="attendanceMode" />
    <OXQuiz v-if="showOXQuiz" />
    <BlockStacking v-if="showOXQuiz" />
    <DanceManager v-if="showDanceManager" />
    <DancePlayPopup v-if="showDancePopup" />
    <GreetingManager v-if="showGreetingManager" />
    <MugunghwaArmManager v-if="showMugunghwaArm" />
    <MugunghwaGame v-if="showMugunghwa" />
    <CameraView v-if="showGogopingManual" />
    <PanTiltControl v-if="showGogopingManual" />
    <FollowFaceAuth
      v-if="showGogopingFollowAuth"
      :active="showGogopingFollowAuth"
      @authenticated="onFollowAuthenticated"
      @cancel="onFollowAuthCancel"
    />
    <HideAndSeekGame v-if="isHideAndSeek" />
    <Transition name="err-fade">
      <button v-if="lastError" class="voice-err" @click="clearVoiceError" :title="lastError">
        ⚠ {{ lastError }}
      </button>
    </Transition>
    <StartOverlay v-if="!started" @start="handleStart" />
  </div>
</template>

<style scoped>
.app {
  position: fixed;
  inset: 0;
  width: 100dvw;
  height: 100dvh;
  overflow: hidden;
  font-family: -apple-system, 'Pretendard', 'Apple SD Gothic Neo', sans-serif;
}
.app.bg-eduping {
  background: linear-gradient(135deg, #fff1f2 0%, #ffe4e6 100%);
}
.app.bg-gogoping {
  background: linear-gradient(135deg, #eef8b8 0%, #d4ec90 100%);
}
.app.bg-noriarm {
  background: linear-gradient(135deg, #e8f5fb 0%, #c5e4f3 100%);
}
.brand {
  position: absolute;
  bottom: 36px;
  left: 44px;
  font-size: 38px;
  font-weight: 800;
  letter-spacing: -1px;
  text-shadow: 0 2px 6px rgba(255, 255, 255, 0.6);
  pointer-events: none;
}
.bg-eduping .brand {
  color: rgba(219, 39, 119, 0.7);
}
.bg-gogoping .brand {
  color: rgba(0, 0, 0, 0.6);
}
.bg-noriarm .brand {
  color: rgba(40, 110, 160, 0.7);
}

.voice-err {
  position: absolute;
  top: calc(env(safe-area-inset-top, 0px) + 8px);
  left: 50%;
  transform: translateX(-50%);
  max-width: min(90vw, 520px);
  padding: 8px 16px;
  border: none;
  border-radius: 999px;
  background: rgba(220, 38, 38, 0.92);
  color: white;
  font-size: 13px;
  font-weight: 700;
  font-family: inherit;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  cursor: pointer;
  box-shadow: 0 4px 14px rgba(220, 38, 38, 0.35);
  z-index: 100;
}
.err-fade-enter-active, .err-fade-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}
.err-fade-enter-from, .err-fade-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(-6px);
}

@media (max-width: 768px), (pointer: coarse) {
  .brand {
    bottom: calc(env(safe-area-inset-bottom, 0px) + 8px);
    left: 12px;
    font-size: 20px;
  }
  .voice-err {
    font-size: 11px;
    padding: 6px 12px;
  }
}

/* 가로 휴대전화: brand 는 dock 과 겹치므로 숨김, voice-err 는 좁은 화면용 사이즈 */
@media (pointer: coarse) and (orientation: landscape),
       (max-height: 500px) and (orientation: landscape) {
  .brand {
    display: none;
  }
  .voice-err {
    top: calc(env(safe-area-inset-top, 0px) + 4px);
    font-size: 10px;
    padding: 4px 10px;
    max-width: calc(100vw - 80px); /* 우측 hamburger 만큼 빼고 */
  }
}
</style>

<style>
/* 전역 — kiosk 풀스크린, 스크롤 없음 */
html,
body,
#app {
  margin: 0;
  padding: 0;
  width: 100dvw;
  height: 100dvh;
  overflow: hidden;
  overscroll-behavior: none;
}
*,
*::before,
*::after {
  box-sizing: border-box;
}
</style>
