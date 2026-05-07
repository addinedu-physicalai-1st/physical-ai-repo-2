import { onBeforeUnmount, ref } from 'vue';

interface SpeechRecognitionEventLike extends Event {
  resultIndex: number;
  results: ArrayLike<{
    isFinal: boolean;
    0: { transcript: string };
  }>;
}

interface SpeechRecognitionLike extends EventTarget {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((ev: SpeechRecognitionEventLike) => void) | null;
  onerror: ((ev: Event) => void) | null;
  onend: (() => void) | null;
}

type SpeechRecognitionCtor = new () => SpeechRecognitionLike;

declare global {
  interface Window {
    webkitSpeechRecognition?: SpeechRecognitionCtor;
    SpeechRecognition?: SpeechRecognitionCtor;
  }
}

export interface STTResult {
  text: string;
  isFinal: boolean;
}

export interface UseSTTOptions {
  lang?: string;
  onResult: (result: STTResult) => void;
  onError?: (message: string) => void;
}

export function useSTT(options: UseSTTOptions): {
  start: () => void;
  stop: () => void;
  refresh: () => void;
  isRunning: ReturnType<typeof ref<boolean>>;
} {
  const isRunning = ref(false);
  let recognition: SpeechRecognitionLike | null = null;
  let shouldRestart = false;

  function build(): SpeechRecognitionLike | null {
    const Ctor = window.SpeechRecognition ?? window.webkitSpeechRecognition;
    if (!Ctor) {
      options.onError?.('이 브라우저는 Web Speech API 를 지원하지 않습니다 (Chrome 사용 권장).');
      return null;
    }
    const r = new Ctor();
    r.continuous = true;
    r.interimResults = true;
    r.lang = options.lang ?? 'ko-KR';
    r.onresult = (event) => {
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        if (!result) continue;
        options.onResult({
          text: result[0].transcript,
          isFinal: result.isFinal,
        });
      }
    };
    r.onerror = (event) => {
      const message = (event as unknown as { error?: string }).error ?? 'unknown';
      console.warn('[STT] Error event:', message);
      
      // If we get a network error, it's usually a browser/API key issue on Linux.
      // Stop the loop to prevent flickering.
      if (message === 'network') {
        console.error('[STT] Fatal network error. Stopping auto-restart. Are you using Chromium? Try Google Chrome.');
        shouldRestart = false;
      }

      if (message === 'no-speech' || message === 'aborted') return;
      options.onError?.(`STT 오류: ${message}`);
    };
    r.onend = () => {
      console.log('[STT] Session ended. shouldRestart:', shouldRestart);
      isRunning.value = false;
      if (shouldRestart) {
        window.setTimeout(() => {
          if (shouldRestart) {
            console.log('[STT] Attempting restart...');
            try {
              r.start();
              isRunning.value = true;
            } catch (e) {
              console.warn('[STT] Restart failed:', e);
            }
          }
        }, 50); // Reduced to 50ms to prevent flickering while clearing buffer
      }
    };
    return r;
  }

  function start(): void {
    shouldRestart = true;
    if (!recognition) recognition = build();
    if (!recognition) return;
    try {
      recognition.start();
      isRunning.value = true;
    } catch {
      // start() throws if already started — safe to ignore
    }
  }

  function stop(): void {
    shouldRestart = false;
    recognition?.stop();
    isRunning.value = false;
  }

  /**
   * 현재 recognition session 을 abort 후 (shouldRestart 유지로) 자동 재시작.
   * TTS echo·이전 발화 잔재 등 누적된 버퍼/상태를 비울 때 사용.
   */
  function refresh(): void {
    if (!recognition) return;
    if (!shouldRestart) return;
    try {
      recognition.abort();
    } catch {
      // already stopped 등 — onend 가 이미 도착했거나 transient
    }
  }

  onBeforeUnmount(() => {
    shouldRestart = false;
    recognition?.abort();
  });

  return { start, stop, refresh, isRunning };
}
