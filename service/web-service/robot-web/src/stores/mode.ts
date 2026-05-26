import { defineStore } from 'pinia';
import { ref, shallowRef } from 'vue';
import type { EmotionId, RobotConfig } from '@/config/robots';
import { getCurrentRobot } from '@/config/robots';
import { postModeClick, type IntentResponse } from '@/composables/useIntentDispatch';

export const useModeStore = defineStore('mode', () => {
  const robot = shallowRef<RobotConfig>(getCurrentRobot());
  const currentMode = ref<string>(robot.value.modes[0] ?? '대기');
  const currentEmotion = ref<EmotionId>('basic');
  const proximityHalt = ref<boolean>(false);
  // 가게놀이 음성 요청 — store_item intent 가 채움. ts 로 같은 item 연속 발화도 watch 트리거.
  // StorePlay.vue 가 watch 해서 (가게놀이 모드 + ready 일 때) serve 호출.
  const requestedStoreItem = ref<{ item: string; ts: number } | null>(null);

  function setMode(mode: string): void {
    if (!robot.value.modes.includes(mode)) return;
    currentMode.value = mode;
    currentEmotion.value = robot.value.defaultEmotionByMode[mode] ?? 'basic';
  }

  function setEmotionTransient(emotion: EmotionId, durationMs: number): void {
    const previous = currentEmotion.value;
    currentEmotion.value = emotion;
    window.setTimeout(() => {
      if (currentEmotion.value === emotion) {
        currentEmotion.value = previous;
      }
    }, durationMs);
  }

  /**
   * 비동기 작업이 끝날 때까지 emotion 을 유지했다가 이전 값으로 복귀.
   * chat 응답을 TTS 로 읽어주는 동안 발화 감정을 띄우는 용도.
   */
  async function holdEmotionDuring<T>(
    emotion: EmotionId,
    fn: () => Promise<T>
  ): Promise<T> {
    const previous = currentEmotion.value;
    currentEmotion.value = emotion;
    try {
      return await fn();
    } finally {
      if (currentEmotion.value === emotion) {
        currentEmotion.value = previous;
      }
    }
  }

  function setProximityHalt(value: boolean): void {
    proximityHalt.value = value;
  }

  function applyIntent(response: IntentResponse): void {
    switch (response.kind) {
      case 'mode_change':
        setMode(response.mode);
        // gogoping '추종' 은 얼굴 인증 게이트가 책임 — 음성 진입도 동일하게 차단.
        if (robot.value.id === 'gogoping' && response.mode === '추종') break;
        // BT 측에도 전달 — robot-web 의 mode 변경이 voice intent 일 때도
        // ModeSelectorFab 클릭 경로와 동일하게 control-service → BT 까지 도달해야
        // admin UI 의 BT state 도 동기화됨. fetch 실패는 무시 (UI 영향 없음).
        void postModeClick(response.mode, robot.value.id).catch(() => {});
        break;
      case 'sub_command':
        if (response.action === 'stop') proximityHalt.value = true;
        // 'return' (RETURNING trigger) 은 ROS 측에서 처리. mode store 는 변경 없음.
        break;
      case 'goto_vertex':
        // graph routing 은 useVoiceController 가 별도 fetch 로 처리. mode 변경 없음.
        break;
      case 'rhythm_play':
      case 'rhythm_stop':
      case 'confirm_yes':
      case 'confirm_no':
        // useVoiceController 가 등록된 mode handler / confirm callback 으로 위임. mode 자체 변경 없음.
        break;
      case 'store_item':
        // 가게놀이 음식 요청 — StorePlay.vue 가 watch 해서 serve. 모드 가드는 거기서.
        requestedStoreItem.value = { item: response.item, ts: Date.now() };
        break;
      case 'chat':
      case 'ignored':
        break;
    }
  }

  return {
    robot,
    currentMode,
    currentEmotion,
    proximityHalt,
    requestedStoreItem,
    setMode,
    setEmotionTransient,
    holdEmotionDuring,
    setProximityHalt,
    applyIntent,
  };
});
