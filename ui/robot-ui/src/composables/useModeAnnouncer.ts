import { onBeforeUnmount, watch } from 'vue';
import { storeToRefs } from 'pinia';
import { useModeStore } from '@/stores/mode';
import { useVoiceStore } from '@/stores/voice';
import { useTTS } from '@/composables/useTTS';

interface ModeAudioConfig {
  src: string;
  loop?: boolean;
  volume?: number;
}

/**
 * 모드 전환 시 "{모드} 모드" TTS 발화 후, 모드별 mp3 재생.
 * 첫 진입(default 모드 셋업)은 발화 생략 — `immediate: false` 로 처리.
 */
export function useModeAnnouncer(audioByMode: Record<string, ModeAudioConfig> = {}): void {
  const { speak, cancel: cancelTTS } = useTTS();
  const mode = useModeStore();
  const voice = useVoiceStore();
  const { currentMode } = storeToRefs(mode);
  const { isSpeaking } = storeToRefs(voice);

  const elements = new Map<string, HTMLAudioElement>();
  // 발화 도중 다른 모드로 전환되면 stale mp3 재생을 막기 위한 토큰
  let transitionToken = 0;

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
    async (next, prev) => {
      if (prev && prev !== next) {
        const prevEl = elements.get(prev);
        if (prevEl) {
          prevEl.pause();
          prevEl.currentTime = 0;
        }
      }
      cancelTTS();

      const myToken = ++transitionToken;
      await speak(next);
      if (myToken !== transitionToken) return;

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
    cancelTTS();
    stopAllAudio();
    elements.clear();
  });
}
