import { onBeforeUnmount, ref, type Ref } from 'vue';
import { useServerSTT } from './useServerSTT';

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

export interface UseSTTReturn {
  start: () => void;
  stop: () => void;
  refresh: () => void;
  isRunning: Ref<boolean>;
  /** 0~1 RMS — phone (서버 STT) 백엔드에서만 의미 있음. 데스크톱은 0 고정. */
  level: Ref<number>;
}

/** 환경 감지 — phone/touch 이거나 Web Speech API 가 없으면 서버 STT 사용. */
function shouldUseServerSTT(): boolean {
  if (typeof window === 'undefined') return false;
  const hasWebSpeech = !!(window.SpeechRecognition || window.webkitSpeechRecognition);
  const coarse =
    typeof window.matchMedia === 'function' && window.matchMedia('(pointer: coarse)').matches;
  return !hasWebSpeech || coarse;
}

export function useSTT(options: UseSTTOptions): UseSTTReturn {
  if (shouldUseServerSTT()) {
    const server = useServerSTT(options);
    return {
      start: server.start,
      stop: server.stop,
      refresh: server.refresh,
      isRunning: server.isRunning as Ref<boolean>,
      level: server.level as Ref<number>,
    };
  }
  return useWebSpeechSTT(options);
}

function useWebSpeechSTT(options: UseSTTOptions): UseSTTReturn {
  const isRunning = ref(false);
  const level = ref(0); // 데스크톱은 useAudioLevel 가 별도로 관리
  let recognition: SpeechRecognitionLike | null = null;
  let shouldRestart = false;
  /** Chrome ends the session on silence (`no-speech`); short restarts spin and flood the console. */
  let nextRestartDelayMs = 200;
  /** 마지막으로 시도한 start() 가 throw 한 경우 watchdog 이 다시 시도하도록 표시. */
  let pendingRetry = false;
  let watchdogId: number | null = null;
  let visibilityHandler: (() => void) | null = null;
  let focusHandler: (() => void) | null = null;

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

      // 네트워크 오류는 transient 일 수도 있다 (모바일 Wi-Fi 일시 단절 등).
      // shouldRestart 를 끄지 않고 긴 백오프로 재시도 — "마이크 항상 켜짐" 요구사항 우선.
      if (message === 'network') {
        nextRestartDelayMs = 5000;
        console.warn('[STT] Network error — retrying in 5s.');
        return;
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
      scheduleRestart(nextRestartDelayMs);
      nextRestartDelayMs = 200;
    };
    return r;
  }

  function scheduleRestart(delay: number): void {
    window.setTimeout(() => {
      if (!shouldRestart) return;
      attemptStart();
    }, delay);
  }

  function attemptStart(): void {
    if (!shouldRestart) return;
    if (!recognition) recognition = build();
    if (!recognition) return;
    if (isRunning.value) return;
    try {
      recognition.start();
      isRunning.value = true;
      pendingRetry = false;
    } catch (e) {
      // 보통 "InvalidStateError: already started" — onend 가 곧 발화하니 무시.
      // 그 외엔 watchdog 이 다시 시도하도록 표시.
      pendingRetry = true;
      console.warn('[STT] start() failed (will retry):', e);
    }
  }

  /** 3초마다 안전망 — shouldRestart 인데 stopped 상태면 강제 재시동. */
  function startWatchdog(): void {
    if (watchdogId !== null) return;
    watchdogId = window.setInterval(() => {
      if (!shouldRestart) return;
      if (isRunning.value && !pendingRetry) return;
      attemptStart();
    }, 3000);
  }

  function stopWatchdog(): void {
    if (watchdogId !== null) {
      window.clearInterval(watchdogId);
      watchdogId = null;
    }
  }

  /** Foreground 로 돌아왔을 때 mic 가 살아있는지 확인 — 백그라운드 동안 Chrome 이 죽였을 수 있음. */
  function installVisibilityRecovery(): void {
    if (visibilityHandler || typeof document === 'undefined') return;
    visibilityHandler = (): void => {
      if (document.visibilityState !== 'visible') return;
      if (!shouldRestart) return;
      if (!isRunning.value) attemptStart();
    };
    focusHandler = (): void => {
      if (!shouldRestart) return;
      if (!isRunning.value) attemptStart();
    };
    document.addEventListener('visibilitychange', visibilityHandler);
    window.addEventListener('focus', focusHandler);
  }

  function removeVisibilityRecovery(): void {
    if (visibilityHandler) {
      document.removeEventListener('visibilitychange', visibilityHandler);
      visibilityHandler = null;
    }
    if (focusHandler) {
      window.removeEventListener('focus', focusHandler);
      focusHandler = null;
    }
  }

  function start(): void {
    shouldRestart = true;
    attemptStart();
    startWatchdog();
    installVisibilityRecovery();
  }

  function stop(): void {
    shouldRestart = false;
    recognition?.stop();
    isRunning.value = false;
    stopWatchdog();
    removeVisibilityRecovery();
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
    stopWatchdog();
    removeVisibilityRecovery();
  });

  return { start, stop, refresh, isRunning, level };
}
