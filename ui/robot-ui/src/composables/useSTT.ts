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
  /** Chrome ends the session on silence (`no-speech`); short restarts spin and flood the console. */
  let nextRestartDelayMs = 200;

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
      nextRestartDelayMs = 200;
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

      // If we get a network error, it's usually a browser/API key issue on Linux.
      // Stop the loop to prevent flickering.
      if (message === 'network') {
        console.error('[STT] Fatal network error. Stopping auto-restart. Are you using Chromium? Try Google Chrome.');
        shouldRestart = false;
      }

      // Silence / user stop — session will end; avoid warn spam and tight restart loops.
      if (message === 'no-speech') {
        nextRestartDelayMs = 750;
        return;
      }
      if (message === 'aborted') {
        return;
      }

      console.warn('[STT] Error event:', message);
      options.onError?.(`STT 오류: ${message}`);
    };
    r.onend = () => {
      isRunning.value = false;
      if (!shouldRestart) return;

      const delay = nextRestartDelayMs;
      nextRestartDelayMs = 200;

      window.setTimeout(() => {
        if (!shouldRestart) return;
        try {
          r.start();
          isRunning.value = true;
        } catch (e) {
          console.warn('[STT] Restart failed:', e);
        }
      }, delay);
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
