import { onBeforeUnmount, ref } from 'vue';
import { useVoiceStore } from '@/stores/voice';

export interface UseTTSOptions {
  /** @deprecated Server-side TTS uses fixed language */
  lang?: string;
  /** @deprecated Server-side TTS uses fixed pitch */
  pitch?: number;
  /** @deprecated Server-side TTS uses fixed rate */
  rate?: number;
  /** @deprecated Server-side TTS uses fixed voice */
  preferredVoiceTokens?: string[];
  onStart?: () => void;
  onEnd?: () => void;
}

/**
 * 전용 서버 사이드 TTS (Edge-TTS)를 사용하는 컴포저블.
 * 브라우저 네이티브 speechSynthesis는 OS/브라우저별 음성 품질 및 지원 편차가 심해(특히 Linux) 제외함.
 */
export function useTTS(options: UseTTSOptions = {}): {
  speak: (text: string) => Promise<void>;
  cancel: () => void;
  isSpeaking: ReturnType<typeof ref<boolean>>;
} {
  const voiceStore = useVoiceStore();
  const isSpeaking = ref(false);
  let currentAudio: HTMLAudioElement | null = null;
  let charInterval: number | null = null;

  async function speak(text: string): Promise<void> {
    if (typeof window === 'undefined') return;

    // 기존 재생 중인 것이 있으면 정지
    cancel();

    console.log(`[TTS] Speaking via Server-Side (Edge-TTS): ${text.slice(0, 20)}...`);
    
    return new Promise((resolve) => {
      // 텍스트가 너무 길면 URL 파라미터 제한에 걸릴 수 있으나, 일반적인 대화형 응답(200자 내외)에서는 문제 없음
      const audio = new Audio(`/api/voice/tts?text=${encodeURIComponent(text)}`);
      currentAudio = audio;

      audio.onplay = () => {
        isSpeaking.value = true;
        options.onStart?.();
        
        // 입모양 애니메이션 시뮬레이션
        // 서버 사이드 오디오는 단어 경계(onboundary) 이벤트가 없으므로,
        // 텍스트의 글자들을 순차적으로 순환하며 립싱크를 흉내낸다.
        let charIdx = 0;
        const cleanText = text.replace(/[^가-힣a-zA-Z]/g, '').trim(); 
        if (cleanText.length > 0) {
            charInterval = window.setInterval(() => {
                voiceStore.setCurrentChar(cleanText[charIdx % cleanText.length]);
                charIdx++;
            }, 180); // 약 0.18초 간격으로 입모양 변경
        }
      };

      audio.onended = () => {
        finish();
        resolve();
      };

      audio.onerror = (e) => {
        console.error('[TTS] Server-side audio error:', e);
        finish();
        resolve();
      };

      const finish = () => {
        isSpeaking.value = false;
        voiceStore.setCurrentChar('');
        if (charInterval) {
            window.clearInterval(charInterval);
            charInterval = null;
        }
        currentAudio = null;
        options.onEnd?.();
      };

      audio.play().catch((err) => {
        // Autoplay policy 등에 의해 실패할 수 있음
        console.error('[TTS] Audio play failed:', err);
        finish();
        resolve();
      });
    });
  }

  function cancel(): void {
    if (currentAudio) {
      currentAudio.pause();
      currentAudio = null;
    }
    if (charInterval) {
      window.clearInterval(charInterval);
      charInterval = null;
    }
    voiceStore.setCurrentChar('');
    isSpeaking.value = false;
  }

  onBeforeUnmount(() => {
    cancel();
  });

  return { speak, cancel, isSpeaking };
}
