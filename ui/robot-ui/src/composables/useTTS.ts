import { onBeforeUnmount, ref } from 'vue';

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
  '여성',
];

let voicesCache: SpeechSynthesisVoice[] = [];

function loadVoices(): SpeechSynthesisVoice[] {
  if (typeof window === 'undefined' || !('speechSynthesis' in window)) return [];
  const voices = window.speechSynthesis.getVoices();
  if (voices.length > 0) voicesCache = voices;
  return voicesCache;
}

function pickVoice(lang: string, tokens: string[]): SpeechSynthesisVoice | null {
  const all = loadVoices();
  if (all.length === 0) return null;
  const langPrefix = lang.split('-')[0];
  const matchingLang = all.filter((v) => v.lang.startsWith(langPrefix));
  if (matchingLang.length === 0) return null;

  for (const token of tokens) {
    const lower = token.toLowerCase();
    const found = matchingLang.find((v) => v.name.toLowerCase().includes(lower));
    if (found) return found;
  }
  return matchingLang[0] ?? null;
}

if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
  // 음성 목록은 비동기 로딩 — 이벤트로 캐시 업데이트
  loadVoices();
  window.speechSynthesis.addEventListener('voiceschanged', () => {
    loadVoices();
  });

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
  const isSpeaking = ref(false);
  const lang = options.lang ?? 'ko-KR';
  const tokens = options.preferredVoiceTokens ?? DEFAULT_KO_FEMALE_TOKENS;

  function speak(text: string): Promise<void> {
    return new Promise((resolve) => {
      if (typeof window === 'undefined' || !('speechSynthesis' in window)) {
        resolve();
        return;
      }

      const synth = window.speechSynthesis;

      // Chrome known issue — paused/stuck 상태에서 회복
      if (synth.paused) synth.resume();
      // 이전 stale utterance 큐 비우기
      if (synth.speaking || synth.pending) synth.cancel();

      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = lang;
      utterance.pitch = options.pitch ?? 1.1;
      utterance.rate = options.rate ?? 1.0;
      utterance.volume = 1.0;
      const voice = pickVoice(lang, tokens);
      if (voice) utterance.voice = voice;

      let resolved = false;
      const finish = (): void => {
        if (resolved) return;
        resolved = true;
        isSpeaking.value = false;
        options.onEnd?.();
        resolve();
      };

      utterance.onstart = () => {
        isSpeaking.value = true;
        options.onStart?.();
      };
      utterance.onend = finish;
      utterance.onerror = finish;

      // 안전 타임아웃 — 10초 안에 onend/onerror 안 오면 강제 resolve (state machine 멈춤 방지)
      window.setTimeout(finish, 10000);

      synth.speak(utterance);
    });
  }

  function cancel(): void {
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      window.speechSynthesis.cancel();
    }
    isSpeaking.value = false;
  }

  onBeforeUnmount(() => {
    cancel();
  });

  return { speak, cancel, isSpeaking };
}
