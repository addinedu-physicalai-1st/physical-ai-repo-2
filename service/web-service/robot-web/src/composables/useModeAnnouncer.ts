import { onBeforeUnmount, watch } from 'vue';
import { storeToRefs } from 'pinia';
import { useModeStore } from '@/stores/mode';
import { useVoiceStore } from '@/stores/voice';
import type { VoiceController } from '@/composables/useVoiceController';

interface ModeAudioConfig {
  src: string;
  loop?: boolean;
  volume?: number;
}

/**
 * 모드 전환 시 "{모드} 모드" TTS 발화 후, 모드별 mp3 재생.
 * 첫 진입(default 모드 셋업)은 발화 생략 — `immediate: false` 로 처리.
 *
 * TTS 는 server 측 (WebRTC outbound) 를 사용 — voiceController.speak 로 위임.
 * 클라 측에서는 lip-sync 가 자동으로 attach/detach 됨.
 */
export function useModeAnnouncer(
  voiceController: VoiceController,
  audioByMode: Record<string, ModeAudioConfig> = {},
): void {
  const mode = useModeStore();
  const voice = useVoiceStore();
  const { currentMode } = storeToRefs(mode);
  const { isSpeaking } = storeToRefs(voice);

  const elements = new Map<string, HTMLAudioElement>();

  function getElement(modeName: string, config: ModeAudioConfig): HTMLAudioElement {
    let el = elements.get(modeName);
    if (!el) {
      el = new Audio(config.src);
      el.loop = config.loop ?? false;
      el.volume = config.volume ?? 1.0;
      el.preload = 'auto';
      elements.set(modeName, el);
    }
    return el;
  }

  function stopAllAudio(): void {
    for (const el of elements.values()) {
      el.pause();
      el.currentTime = 0;
    }
  }

  /** 자장가 등 루프 BGM 과 웨이크/서버 TTS 가 동시에 나오면 음성이 뭉개져 들린다 — TTS 중엔 일시 정지. */
  watch(isSpeaking, (speaking) => {
    if (speaking) {
      for (const el of elements.values()) {
        if (!el.paused) el.pause();
      }
      return;
    }
    const config = audioByMode[currentMode.value];
    if (!config?.loop) return;
    const el = elements.get(currentMode.value);
    if (el?.paused) {
      el.play().catch(() => {
        // autoplay / gesture
      });
    }
  });

  watch(
    currentMode,
    (next, prev) => {
      if (prev && prev !== next) {
        const prevEl = elements.get(prev);
        if (prevEl) {
          prevEl.pause();
          prevEl.currentTime = 0;
        }
      }
      // 진행 중 server TTS 가 있으면 비우고 새 모드 안내. WebRTC 가 즉시 buffer clear.
      voiceController.cancelSpeak();
      voiceController.speak(next);

      const config = audioByMode[next];
      if (!config) return;
      const el = getElement(next, config);
      el.currentTime = 0;
      el.play().catch(() => {
        // autoplay 정책 — StartOverlay 클릭 전이면 무시
      });
    },
    { immediate: false }
  );

  onBeforeUnmount(() => {
    voiceController.cancelSpeak();
    stopAllAudio();
    elements.clear();
  });
}
