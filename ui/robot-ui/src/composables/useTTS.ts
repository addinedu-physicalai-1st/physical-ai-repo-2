import { onBeforeUnmount, ref } from 'vue';
import { useVoiceStore } from '@/stores/voice';

export interface UseTTSOptions {
  lang?: string;
  pitch?: number;
  rate?: number;
  /** 우선순위 높은 음성 이름 토큰. 첫 매칭 음성을 사용한다 */
  preferredVoiceTokens?: string[];
  onStart?: () => void;
  onEnd?: () => void;
}

// 한국어 여성 음성 후보 (OS·브라우저별 이름 차이)
//   macOS: Yuna, Sora — 기본 시스템 음성
//   Windows: Heami — Microsoft Heami
//   Chrome (Google 음성): "Google 한국의" / "Google Korean"
//   Android: Korean female 표기
const DEFAULT_KO_FEMALE_TOKENS = [
  'Yuna',
  'Sora',
  'Heami',
  'Seoyeon',
  'Google 한국의',
  'Google Korean',
  'Korean Female',
  'ko-KR',
  'ko_KR',
  'korean',
  '여성',
  'ko',
];

let voicesCache: SpeechSynthesisVoice[] = [];

function loadVoices(): SpeechSynthesisVoice[] {
  if (typeof window === 'undefined' || !('speechSynthesis' in window)) return [];
  const voices = window.speechSynthesis.getVoices();
  if (voices.length > 0) {
    if (voicesCache.length === 0) {
      console.log(`[TTS] Available voices: ${voices.length}`);
      console.table(voices.map(v => ({ name: v.name, lang: v.lang, local: v.localService })));
    }
    voicesCache = voices;
  }
  return voicesCache;
}

function pickVoice(lang: string, tokens: string[]): SpeechSynthesisVoice | null {
  const all = loadVoices();
  if (all.length === 0) return null;
  const langPrefix = lang.split('-')[0].toLowerCase();
  const matchingLang = all.filter((v) => v.lang.toLowerCase().startsWith(langPrefix));

  let picked: SpeechSynthesisVoice | null = null;
  if (matchingLang.length > 0) {
    for (const token of tokens) {
      const lower = token.toLowerCase();
      const found = matchingLang.find((v) => v.name.toLowerCase().includes(lower));
      if (found) {
        picked = found;
        break;
      }
    }
    if (!picked) picked = matchingLang[0];
  }

  // 한국어 음성이 전혀 없을 경우, 시스템 기본값이라도 사용하도록 null 반환 (Browser default fallback)
  console.log(`[TTS] Picked voice: ${picked ? `${picked.name} (${picked.lang})` : 'System Default'}`);
  return picked;
}

if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
  // 음성 목록은 비동기 로딩 — 이벤트로 캐시 업데이트
  loadVoices();
  window.speechSynthesis.onvoiceschanged = () => {
    console.log('[TTS] Voices changed event fired');
    loadVoices();
  };

  // 일부 브라우저는 이벤트가 안 올 수 있으므로 폴링 (최초 3초간)
  let retryCount = 0;
  const pollVoices = setInterval(() => {
    const v = loadVoices();
    if (v.length > 0 || retryCount++ > 10) {
      clearInterval(pollVoices);
      if (v.length === 0) {
        console.warn('[TTS] No voices found even after retry. Linux user? Try: sudo apt install language-pack-ko speech-dispatcher-espeak-ng');
      }
    }
  }, 300);

  // Chrome autoplay policy — 첫 user gesture 전에 speak 하면 'not-allowed' 에러.
  // 첫 pointerdown 에 silent utterance 로 engine 을 unlock.
  const unlock = (): void => {
    try {
      const u = new SpeechSynthesisUtterance(' ');
      u.volume = 0;
      window.speechSynthesis.speak(u);
    } catch {
      // ignore
    }
    window.removeEventListener('pointerdown', unlock);
    window.removeEventListener('keydown', unlock);
  };
  window.addEventListener('pointerdown', unlock, { once: true });
  window.addEventListener('keydown', unlock, { once: true });
}

export function useTTS(options: UseTTSOptions = {}): {
  speak: (text: string) => Promise<void>;
  cancel: () => void;
  isSpeaking: ReturnType<typeof ref<boolean>>;
} {
  const voiceStore = useVoiceStore();
  const isSpeaking = ref(false);
  const lang = options.lang ?? 'ko-KR';
  const tokens = options.preferredVoiceTokens ?? DEFAULT_KO_FEMALE_TOKENS;
  let currentAudio: HTMLAudioElement | null = null;

  async function speakServerSide(text: string): Promise<void> {
    console.log(`[TTS] Using Server-Side Fallback: ${text.slice(0, 20)}...`);
    return new Promise((resolve) => {
      if (currentAudio) {
        currentAudio.pause();
        currentAudio = null;
      }

      const audio = new Audio(`/api/voice/tts?text=${encodeURIComponent(text)}`);
      currentAudio = audio;

      audio.onplay = () => {
        isSpeaking.value = true;
        options.onStart?.();
      };
      audio.onended = () => {
        isSpeaking.value = false;
        options.onEnd?.();
        currentAudio = null;
        resolve();
      };
      audio.onerror = (e) => {
        console.error('[TTS] Server side audio error:', e);
        isSpeaking.value = false;
        currentAudio = null;
        resolve(); // 에러나도 흐름은 끊기지 않게
      };

      audio.play().catch((err) => {
        console.error('[TTS] Audio play failed:', err);
        resolve();
      });
    });
  }

  async function speak(text: string): Promise<void> {
    if (typeof window === 'undefined') return;

    // 1. 네이티브 음성이 하나도 없으면 즉시 서버 사이드 사용
    const voice = pickVoice(lang, tokens);
    if (!voice && voicesCache.length === 0) {
      return speakServerSide(text);
    }

    if (!('speechSynthesis' in window)) {
      return speakServerSide(text);
    }

    const synth = window.speechSynthesis;

    // Chrome known issue — paused/stuck 상태에서 회복
    synth.resume();
    // 이전 stale utterance 큐 비우기
    if (synth.speaking || synth.pending) {
      synth.cancel();
      // cancel 후 큐가 완전히 비워지기까지 아주 짧은 대기 (브라우저 안정성)
      await new Promise((r) => setTimeout(r, 50));
      synth.resume();
    }

    return new Promise((resolve) => {
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = lang;
      utterance.pitch = options.pitch ?? 1.1;
      utterance.rate = options.rate ?? 1.0;
      utterance.volume = 1.0;
      const voice = pickVoice(lang, tokens);
      if (voice) utterance.voice = voice;

      let resolved = false;
      let wordInterval: number | null = null;
      
      const finish = (reason?: string): void => {
        if (resolved) return;
        resolved = true;
        if (wordInterval) window.clearInterval(wordInterval);
        isSpeaking.value = false;
        if (reason) console.log(`[TTS] Finished: ${reason} (text: ${text.slice(0, 20)}...)`);
        options.onEnd?.();
        resolve();
      };

      utterance.onstart = () => {
        isSpeaking.value = true;
        voiceStore.setCurrentChar(''); // Reset
        console.log(`[TTS] Start: ${text.slice(0, 20)}...`);
        options.onStart?.();
      };

      utterance.onboundary = (event) => {
        if (event.name !== 'word') return;
        
        if (wordInterval) window.clearInterval(wordInterval);
        
        // 브라우저에 따라 charLength를 안 주는 경우가 있으므로 fallback 처리
        let length = event.charLength;
        if (!length) {
          const nextSpace = text.indexOf(' ', event.charIndex);
          length = nextSpace === -1 ? text.length - event.charIndex : nextSpace - event.charIndex;
        }
        
        const word = text.slice(event.charIndex, event.charIndex + length).trim();
        if (!word) return;

        let charIdx = 0;
        // 첫 글자 즉시 세팅
        voiceStore.setCurrentChar(word[charIdx]);
        
        // 220ms 마다 다음 글자로 넘김 (조금 더 자연스럽고 부드러운 발음 속도에 맞춤)
        wordInterval = window.setInterval(() => {
          charIdx++;
          if (charIdx >= word.length) {
            if (wordInterval) window.clearInterval(wordInterval);
            // 단어가 끝나면 입을 살짝 닫아주기 위해 빈 문자 처리
            voiceStore.setCurrentChar('');
            return;
          }
          voiceStore.setCurrentChar(word[charIdx]);
        }, 220);
      };

      utterance.onend = () => {
        voiceStore.setCurrentChar('');
        finish('end');
      };

      utterance.onerror = (e) => {
        voiceStore.setCurrentChar('');
        console.error('[TTS] Native Error, falling back to server:', e);
        finish('error');
        // 네이티브 에러 시 서버 사이드로 재시도
        speakServerSide(text).then(resolve);
      };

      // 안전 타임아웃 — 10초 안에 onend/onerror 안 오면 서버 사이드로 전환 시도
      window.setTimeout(() => {
        if (!resolved) {
          console.warn('[TTS] Native timeout, falling back to server');
          synth.cancel();
          finish('timeout');
          speakServerSide(text).then(resolve);
        }
      }, 10000);

      synth.speak(utterance);
    });
  }

  function cancel(): void {
    if (typeof window !== 'undefined') {
      if ('speechSynthesis' in window) {
        window.speechSynthesis.cancel();
      }
      if (currentAudio) {
        currentAudio.pause();
        currentAudio = null;
      }
    }
    isSpeaking.value = false;
  }

  onBeforeUnmount(() => {
    cancel();
  });

  return { speak, cancel, isSpeaking };
}
