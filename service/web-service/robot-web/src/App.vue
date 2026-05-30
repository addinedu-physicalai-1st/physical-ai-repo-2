<script setup lang="ts">
import { computed, onBeforeUnmount, provide, ref, watch } from 'vue';
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
import DepthViewer from '@/eduping/DepthViewer.vue';
import HighfiveDetector from '@/eduping/HighfiveDetector.vue';
import ArmDepthScreen from '@/eduping/ArmDepthScreen.vue';
import GreetingManager from '@/eduping/GreetingManager.vue';
import HealthCheckCamera from '@/eduping/HealthCheckCamera.vue';
import MugunghwaArmManager from '@/eduping/MugunghwaArmManager.vue';
import MugunghwaGame from '@/eduping/MugunghwaGame.vue';
import OXQuiz from '@/noriarm/OXQuiz.vue';
import BlockStacking from '@/noriarm/BlockStacking.vue';
import StorePlay from '@/noriarm/StorePlay.vue';
import { useCameraPan } from '@/gogoping/composables/useCameraPan';
import { CAMERA_PAN_KEY } from '@/gogoping/cameraPanKey';
import { useWebRTCStream } from '@/gogoping/composables/useWebRTCStream';
import { VIDEO_STREAM_KEY } from '@/gogoping/videoStreamKey';
import { useGogopingStateWs } from '@/gogoping/composables/useGogopingStateWs';
import CameraView from '@/gogoping/CameraView.vue';
import PanTiltControl from '@/gogoping/PanTiltControl.vue';
import GogopingDebugPanel from '@/gogoping/GogopingDebugPanel.vue';
import FollowFaceAuth from '@/gogoping/FollowFaceAuth.vue';
import { useFollowStateWs } from '@/gogoping/composables/useFollowStateWs';
import { useTtsSay } from '@/composables/useTtsSay';
import HideAndSeekGame from '@/gogoping/HideAndSeekGame.vue';
import FollowMode from '@/gogoping/FollowMode.vue';
import { useErrorStore } from '@/gogoping/stores/error';
import { useGogopingFsmStore } from '@/gogoping/stores/fsm';
import { ERROR_CHILD_MESSAGE } from '@/gogoping/errorReason';
import { gogopingStateMessage } from '@/gogoping/stateMessage';
import AdminOpenArmEmbed from '@/admin/AdminOpenArmEmbed.vue';
import AdminOpenArmCompare from '@/admin/AdminOpenArmCompare.vue';
import AdminGogopingVideo from '@/admin/AdminGogopingVideo.vue';

// `?embed=openarm`          → fullscreen OpenArm viewer for the PyQt admin app
// `?embed=openarm-compare`  → side-by-side two-viewer comparison popup
// `?embed=gogoping-video`   → fullscreen WebRTC consumer for the admin
//                             camera card (peer_id='admin-ui')
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
const isAdminGogopingVideo = embedMode === 'gogoping-video';

const mode = useModeStore();
const voice = useVoiceStore();
const { robot, currentEmotion, currentMode } = storeToRefs(mode);
const { lastError } = storeToRefs(voice);

// gogoping ERROR(고장) — 별도 오버레이/버튼 없이 기존 로봇 얼굴 + 말풍선으로 안내.
// errorStore.active 는 useGogopingStateWs 가 snapshot.fsm_state==='ERROR' 일 때 set.
const errorStore = useErrorStore();
const gogopingErrorMsg = computed(() =>
  robot.value.id === 'gogoping' && errorStore.active ? ERROR_CHILD_MESSAGE : ''
);
// 고장 중엔 자는(sleep) 표정 — ShaderFace 의 Zzz 효과와 함께 "잠깐 쉬는 중" 느낌.
const faceEmotion = computed(() => (gogopingErrorMsg.value ? 'sleep' : currentEmotion.value));
// 고장 중엔 조작 버튼(하단 독·모드 FAB)을 숨겨 추가 조작을 막는다 — 얼굴 + 말풍선만 남긴다.
const isGogopingError = computed(() => robot.value.id === 'gogoping' && errorStore.active);

// gogoping 은 모드 버튼이 없고(admin/BT/음성이 모드 제어) 말풍선이 상태를 항상 알려준다.
// 현재 mode 라벨 → 상냥한 한 마디. ERROR 는 gogopingErrorMsg(override) 가 우선.
const isGogoping = computed(() => robot.value.id === 'gogoping');
const gogopingBubbleDefault = computed(() =>
  isGogoping.value ? gogopingStateMessage(currentMode.value) : ''
);
// 우상단 아주 작은 영문 FSM 상태 배지 — 디버그/교사 확인용.
const fsmStore = useGogopingFsmStore();
const { fsmState } = storeToRefs(fsmStore);
const showFsmBadge = computed(() => isGogoping.value && !!fsmState.value);

function clearVoiceError(): void {
  voice.setError(null);
}

const attendanceMode = computed<'IN' | 'OUT' | null>(() => {
  if (robot.value.id !== 'eduping') return null;
  if (currentMode.value === '등원') return 'IN';
  if (currentMode.value === '하원') return 'OUT';
  return null;
});

// 등원 신규 인식 → "하이파이브" 멘트 후 AttendanceCamera 가 보내는 highfive-request 로
// HighfiveDetector 를 띄움. 손 감지·하이파이브 완료/timeout 시 닫힘.
const arrivalHighfive = ref<{ name: string } | null>(null);
// 등원 하이파이브 동안만 high-five → 실물 OpenArm relay 를 켠다. 백엔드 갱신은
// 자체 guard (실물 bringup 없음 / teleop 켜짐 → no-op) 가 있어 sim-only 환경엔 무해.
// HighfiveDetector 는 성공·timeout (기본 ~9s) 모두 complete 를 emit → 항상 다시 꺼져
// relay 가 한 번 등원당 최대 ~9s 만 켜져 있고 평소 상태로 복원된다.
async function setArrivalHighfiveRealSync(enabled: boolean): Promise<void> {
  try {
    await fetch('/api/eduping/highfive/sync', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ enabled }),
    });
  } catch {
    /* sim-only / 백엔드 미가동 — 무시 (MuJoCo twin 은 그대로 동작) */
  }
}
function startArrivalHighfive(name: string): void {
  if (arrivalHighfive.value) return;   // 한 번에 한 명
  arrivalHighfive.value = { name };
  void setArrivalHighfiveRealSync(true);
}
function endArrivalHighfive(): void {
  arrivalHighfive.value = null;
  void setArrivalHighfiveRealSync(false);
}

// 하원/율동 — 로봇 팔 + depth cloud 를 view-only 배경 (ArmDepthScreen). 등원 은 제외 —
// depth cloud/URDF 3js 렌더가 무거워(lagging) 등원엔 안 띄운다. 등원 화면은
// EmotionDisplay(에듀핑 얼굴) + 좌상단 AttendanceCamera PiP 만, 팔 하이파이브는 MuJoCo 창에서 관찰.
const showArmScreen = computed(
  () => robot.value.id === 'eduping'
    && (currentMode.value === '하원'
      || currentMode.value === '율동'),
);

const showOXQuiz = computed(() => robot.value.id === 'noriarm');
const showDanceManager = computed(() => robot.value.id === 'eduping' && currentMode.value === '율동 등록');
const showDancePopup = computed(() => robot.value.id === 'eduping' && currentMode.value === '율동');
const showGreetingManager = computed(() => robot.value.id === 'eduping' && currentMode.value === '등하원 인사 설정');
const showMugunghwaArm = computed(() => robot.value.id === 'eduping' && currentMode.value === '무궁화 율동 등록');
const showMugunghwa = computed(() => robot.value.id === 'eduping' && currentMode.value === '무궁화꽃이 피었습니다');
// 건강검진 — OpenArm body 의 D435 RGB 영상을 의사 / 환자 양쪽에 표시. 같은 /ws/depth-stream WS 공유.
const showHealthCheck = computed(() => robot.value.id === 'eduping' && currentMode.value === '건강검진');
// 뎁스카메라 뷰 — D435 depth view + palm tracker + 하이파이브 IK 트리거.
// DepthViewer 내부에서 useDepthStream + useHandTracker + postHighfiveHandTarget 처리.
// 4b98dc6 에서 컴포넌트는 추가됐는데 App.vue 마운트가 빠져있어 UI 에서 못 보였다.
const showHighfive = computed(() => robot.value.id === 'eduping' && currentMode.value === '뎁스카메라 뷰');

const showGogopingManual = computed(
  // ERROR(고장) 중엔 수동 카메라 뷰를 내려 얼굴+말풍선 UI 로 복귀 (말풍선·버튼숨김과 동일하게
  // ERROR 에 반응 — 수동 카메라만 errorStore 를 안 봐서 ERROR 떠도 떠 있던 버그 fix).
  () => robot.value.id === 'gogoping' && currentMode.value === '수동' && !errorStore.active
);
// 디버그 패널 토글 — URL 에 ?debug=1 (대소문자 무관) 명시할 때만 표시.
// 검증 필요 시: localhost:5173/?debug=1 (또는 ?Debug=1) 식으로 접속.
// 완전 제거 시: 본 줄 + GogopingDebugPanel import + template 의 v-if 라인 삭제.
const showDebug = computed(() => {
  const params = new URLSearchParams(window.location.search.toLowerCase());
  return params.get('debug') === '1';
});
const showGogopingHideAndSeek = computed(
  // ERROR 중엔 숨바꼭질 오버레이도 내려 얼굴+말풍선 UI 로 복귀 (수동과 동일).
  () => robot.value.id === 'gogoping' && currentMode.value === '숨바꼭질' && !errorStore.active
);

// Voice-guided search — follow_node mode 전이 감지 → TTS 발화.
//   VOICE_SEARCH → VOICE_FOUND: "선생님 찾았습니다"
//   VOICE_SEARCH → IDLE (못 찾음): "선생님을 찾지 못했습니다"
const followStateWs = useFollowStateWs();
const ttsSay = useTtsSay();
let prevFollowMode: string | null = null;
watch(() => followStateWs.state.value.mode, (newMode) => {
  if (prevFollowMode === 'voice_search' && newMode === 'voice_found') {
    void ttsSay.sayText('선생님 찾았습니다');
  } else if (prevFollowMode === 'voice_search' && newMode === 'idle') {
    void ttsSay.sayText('선생님을 찾지 못했습니다');
  }
  prevFollowMode = newMode;
});

// embed (admin QWebEngineView) 페이지에서는 main app 측 gogoping 리소스를 생성하지 않는다.
// AdminGogopingVideo 가 자체적으로 useWebRTCStream('admin-ui') 을 만들기 때문에, 같은
// 페이지에서 robot-web peer 까지 동시 생성되면 control-service 에 중복 consumer 가 붙는다.
const isAnyEmbed = isAdminOpenArmEmbed || isAdminOpenArmCompare || isAdminGogopingVideo;
const isMainGogoping = !isAnyEmbed && robot.value.id === 'gogoping';

// gogoping 일 때만 useCameraPan 인스턴스를 생성해서 두 컴포넌트 공유
const cameraPan = isMainGogoping ? useCameraPan() : null;
if (cameraPan) provide(CAMERA_PAN_KEY, cameraPan);

// gogoping 일 때만 useWebRTCStream 인스턴스를 한 번만 생성해서 CameraView/FollowFaceAuth 공유.
// control-service 의 /ws/webrtc/signaling 으로 server-side offer 흐름을 받아 MediaStream 으로 표시.
const videoStream = isMainGogoping ? useWebRTCStream('robot-web') : null;
if (videoStream) provide(VIDEO_STREAM_KEY, { stream: videoStream.stream, status: videoStream.status });

// gogoping 일 때만 BT snapshot WS 구독 — admin UI 가 mode 바꾸면 자동 반영
const gogopingStateWs = isMainGogoping ? useGogopingStateWs() : null;

onBeforeUnmount(() => {
  cameraPan?.stop();
  videoStream?.stop();
  gogopingStateWs?.stop();
});

const voiceController: VoiceController = useVoiceController(robot.value);
provide(VOICE_CONTROLLER_KEY, voiceController);

const DEVICE_TOKEN = import.meta.env.VITE_ROBOT_TOKEN ?? 'dev-robot-token-change-me';

// 추종 모드 동안 FollowFaceAuth 가 항상 mount — 인증 전엔 중앙 모달, 인증 후엔 좌상단 PiP 로
// 디버그용 카메라 뷰를 유지. 모드를 벗어나면 unmount 되며 카메라 정지.
const showGogopingFollowAuth = computed(
  // ERROR 중엔 추종 인증 오버레이도 내려 얼굴+말풍선 UI 로 복귀 (수동과 동일).
  () => robot.value.id === 'gogoping' && currentMode.value === '추종' && !errorStore.active
);

// 인증 완료 여부를 별도 ref 로 관리 — FollowFaceAuth 내부 상태(succeeded)를 직접 알 수 없으므로
// authenticated event 수신 시점에 App 레벨에서 마킹.
const followAuthenticated = ref(false);

const showGogopingFollowMode = computed(
  () => robot.value.id === 'gogoping' && currentMode.value === '추종' && followAuthenticated.value && !errorStore.active
);

async function onFollowAuthenticated(payload: { name: string; teacher_id: string }): Promise<void> {
  voiceController.speak(`${payload.name} 선생님 확인 완료, 추종을 시작합니다.`);
  try {
    await postModeClick('추종', robot.value.id);
  } catch {
    /* BT 미연결이어도 UI 는 진행 */
  }
  // ROS 측 추종 시작 trigger.
  if (payload.teacher_id) {
    try {
      await fetch('/api/gogoping/follow/start', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Device-Token': DEVICE_TOKEN,
        },
        body: JSON.stringify({ teacher_id: payload.teacher_id }),
      });
    } catch {
      /* 오프라인 — UI 는 진행, ROS 추종은 미동작 */
    }
  }
  followAuthenticated.value = true;
}

async function onFollowAuthCancel(): Promise<void> {
  // UI 우선 — 서버가 hang 해도 X 버튼은 즉시 반응해야 함.
  // setMode('대기') → showGogopingFollowAuth=false → 오버레이 unmount + 카메라 정지.
  // 백엔드 stop 은 mode watch (currentMode → 추종 이탈) 가 follow/stop 재호출로 중복 보장.
  followAuthenticated.value = false;
  mode.setMode('대기');
  try {
    await fetch('/api/gogoping/follow/stop', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Device-Token': DEVICE_TOKEN,
      },
      body: '{}',
    });
  } catch { /* 오프라인 — UI 는 진행 */ }
  try {
    await postModeClick('대기', robot.value.id);
  } catch {
    /* 무시 */
  }
}

// FollowMode 내 정지 버튼 핸들러 — 로봇 정지 API 호출 후 모드를 대기로 복귀.
async function onFollowStop(): Promise<void> {
  try {
    await fetch('/api/gogoping/follow/stop', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Device-Token': DEVICE_TOKEN },
      body: '{}',
    });
  } catch { /* 오프라인 — UI 는 진행 */ }
  mode.setMode('대기');
  try {
    await postModeClick('대기', robot.value.id);
  } catch {
    /* 무시 */
  }
  followAuthenticated.value = false;
}

// 추종 → 다른 mode 전이 시 follow/stop 호출 (FollowFaceAuth cancel 경로와 중복돼도 backend idempotent).
let _prevModeForFollow = currentMode.value;
watch(currentMode, async (newMode) => {
  if (_prevModeForFollow === '추종' && newMode !== '추종') {
    try {
      await fetch('/api/gogoping/follow/stop', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Device-Token': DEVICE_TOKEN },
        body: '{}',
      });
    } catch { /* ignore */ }
    followAuthenticated.value = false;
  }
  _prevModeForFollow = newMode;
});

// 모드 전환 시 voiceController.speak 로 서버 TTS 안내, BGM mp3 도 같이 처리.
useModeAnnouncer(
  voiceController,
  {
    자장가: { src: '/audio/lullaby.mp3', loop: true, volume: 0.7 },
  },
  {
    // 율동 모드 진입 시 곡 선택을 음성으로 요구.
    율동: '어떤 노래로 율동할까요?',
    // 가게놀이는 자체 인트로 음성(voice_intro.mp3) 을 재생하므로 모드명 TTS 생략 (겹침 방지).
    가게놀이: '',
  },
);

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
  <AdminGogopingVideo v-else-if="isAdminGogopingVideo" />
  <div v-else class="app" :class="`bg-${robot.id}`">
    <EmotionDisplay
      :emotion="faceEmotion"
      :bubble-override="gogopingErrorMsg"
      :bubble-default="gogopingBubbleDefault"
    />
    <ArmDepthScreen v-if="showArmScreen" />
    <BottomDock v-if="!isGogopingError" />
    <ModeSelectorFab v-if="!isGogopingError" />
    <div v-if="showFsmBadge" class="fsm-badge">{{ fsmState }}</div>
    <div class="brand">{{ robot.displayName }}</div>
    <AttendanceCamera :mode="attendanceMode" @highfive-request="startArrivalHighfive" />
    <HighfiveDetector
      v-if="arrivalHighfive"
      @complete="endArrivalHighfive"
      @timeout="endArrivalHighfive"
    />
    <OXQuiz v-if="showOXQuiz" />
    <BlockStacking v-if="showOXQuiz" />
    <StorePlay v-if="showOXQuiz" />
    <DanceManager v-if="showDanceManager" />
    <DancePlayPopup v-if="showDancePopup" />
    <GreetingManager v-if="showGreetingManager" />
    <MugunghwaArmManager v-if="showMugunghwaArm" />
    <MugunghwaGame v-if="showMugunghwa" />
    <HealthCheckCamera v-if="showHealthCheck" />
    <DepthViewer v-if="showHighfive" />
    <CameraView v-if="showGogopingManual" />
    <PanTiltControl v-if="showGogopingManual" />
    <GogopingDebugPanel v-if="(showGogopingManual || showGogopingFollowAuth) && showDebug" />
    <FollowFaceAuth
      v-if="showGogopingFollowAuth"
      :active="showGogopingFollowAuth"
      @authenticated="onFollowAuthenticated"
      @cancel="onFollowAuthCancel"
    />
    <HideAndSeekGame v-if="showGogopingHideAndSeek" />
    <FollowMode
      v-if="showGogopingFollowMode"
      class="gogoping-follow-mode-layer"
      @stop="onFollowStop"
    />
    <Transition name="err-fade">
      <button v-if="lastError && !isGogopingError" class="voice-err" @click="clearVoiceError" :title="lastError">
        ⚠ {{ lastError }}
      </button>
    </Transition>
    <StartOverlay v-if="!started" @start="handleStart" />
    <div v-if="voiceController.debug" class="wake-debug">
      <template v-for="(score, id) in voiceController.wakeScores.value" :key="id">
        <span class="wake-debug-row" :class="{ fire: score >= voiceController.wakeThreshold }">
          {{ id }} {{ (score * 100).toFixed(1) }}%
        </span>
      </template>
    </div>
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

/* gogoping 우상단 아주 작은 FSM 영문 상태 배지 — 교사/디버그 확인용. */
.fsm-badge {
  position: absolute;
  top: calc(env(safe-area-inset-top, 0px) + 6px);
  right: 8px;
  padding: 2px 7px;
  border-radius: 6px;
  background: rgba(0, 0, 0, 0.28);
  color: rgba(255, 255, 255, 0.92);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.04em;
  line-height: 1.2;
  pointer-events: none;
  z-index: 60;
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

/* FollowFaceAuth PiP(z-index:50) 아래에 위치 — 인증 완료 후 메인 영역 전체를 차지 */
.gogoping-follow-mode-layer {
  position: fixed;
  inset: 0;
  z-index: 30;
  background: rgba(15, 20, 18, 0.95);
  padding: 40px 16px;
  display: flex;
  align-items: center;
  justify-content: center;
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

.wake-debug {
  position: fixed;
  right: 8px;
  bottom: 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 4px 8px;
  background: rgba(0, 0, 0, 0.55);
  color: #eee;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
  line-height: 1.2;
  border-radius: 4px;
  pointer-events: none;
  z-index: 9999;
}

.wake-debug-row.fire {
  color: #6ee7b7;
  font-weight: 700;
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
