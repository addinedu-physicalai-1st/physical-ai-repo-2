import { onBeforeUnmount, ref } from 'vue';
import type { STTResult, UseSTTOptions } from './useSTT';

/**
 * 휴대전화·iOS Safari 폴백용 STT.
 *
 * 핵심: 단일 `getUserMedia` 스트림을 켜둔 채로, AudioContext 의 RMS 로 voice activity 감지(VAD) 해서
 * 사용자가 말하는 구간만 `MediaRecorder` chunk 로 묶고 침묵이 잠시 이어지면 `POST /api/stt` 로
 * 보내 텍스트를 받는다. webkitSpeechRecognition 처럼 매 utterance 마다 mic 를 다시 잡지 않으므로
 * OS 마이크 인디케이터가 깜빡이지 않는다.
 *
 * useSTT 와 같은 `{ start, stop, refresh, isRunning }` shape 으로 useVoiceController 가
 * 분기 없이 사용한다. 결과는 항상 `{ isFinal: true }` 한 번 — interim 없음.
 */

const VAD_RMS_START = 0.015;
const VAD_RMS_STOP = 0.008;
// 침묵 hangover — utterance 종료를 결정하는 가장 큰 고정 지연. 너무 짧으면 단어 중간에 끊기고,
// 너무 길면 응답이 그만큼 늦어진다. 호출어 "에듀핑" 같은 짧은 발화 응답성 우선.
// wake_detected 이후 follow-up 명령은 useVoiceController.WAKE_SETTLE_MS 가 별도 윈도우를
// 제공하므로 hangover 를 더 짧게 잡아도 명령이 잘리지 않는다.
const VAD_HANGOVER_MS = 180;
const VAD_MIN_UTTERANCE_MS = 200;
const VAD_MAX_UTTERANCE_MS = 12000;

export function useServerSTT(options: UseSTTOptions): {
  start: () => void;
  stop: () => void;
  refresh: () => void;
  isRunning: ReturnType<typeof ref<boolean>>;
  /** 0~1 RMS — SiriBlob 등 시각화에 그대로 사용 가능 */
  level: ReturnType<typeof ref<number>>;
} {
  const isRunning = ref(false);
  const level = ref(0);

  let stream: MediaStream | null = null;
  let audioContext: AudioContext | null = null;
  let analyser: AnalyserNode | null = null;
  let dataArray: Uint8Array | null = null;
  let rafId: number | null = null;

  let recorder: MediaRecorder | null = null;
  let recorderMime = '';
  let chunks: Blob[] = [];
  let speaking = false;
  let speakStartedAt = 0;
  let silenceStartedAt = 0;
  let inflight: AbortController | null = null;
  let stopRequested = false;

  function pickMimeType(): string {
    // iOS Safari: 'audio/mp4' 만 지원. Android Chrome: 'audio/webm;codecs=opus' 우선.
    const ua = typeof navigator !== 'undefined' ? navigator.userAgent : '';
    const isIOS = /iPad|iPhone|iPod/.test(ua) || (/Mac/.test(ua) && 'ontouchend' in document);
    const candidates = isIOS
      ? ['audio/mp4', 'audio/mp4;codecs=mp4a.40.2', 'audio/aac', 'audio/webm;codecs=opus', 'audio/webm']
      : ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/mp4;codecs=mp4a.40.2', 'audio/ogg;codecs=opus'];
    for (const c of candidates) {
      if (typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported?.(c)) return c;
    }
    return '';
  }

  function startUtterance(): void {
    if (!stream || speaking) return;
    chunks = [];
    try {
      recorder = recorderMime
        ? new MediaRecorder(stream, { mimeType: recorderMime })
        : new MediaRecorder(stream);
    } catch (e) {
      options.onError?.(`녹음 시작 실패: ${(e as Error).message}`);
      return;
    }
    recorder.ondataavailable = (ev) => {
      if (ev.data && ev.data.size > 0) chunks.push(ev.data);
    };
    recorder.onstop = () => {
      const collected = chunks;
      chunks = [];
      const blob = new Blob(collected, { type: recorderMime || 'audio/webm' });
      const duration = Date.now() - speakStartedAt;
      console.debug('[ServerSTT] utterance stop, duration=', duration, 'ms bytes=', blob.size);
      if (blob.size === 0 || duration < VAD_MIN_UTTERANCE_MS) {
        console.debug('[ServerSTT] skipping (too short or empty)');
        return;
      }
      void upload(blob);
    };
    recorder.onerror = (ev) => {
      const err = (ev as unknown as { error?: { message?: string } }).error;
      options.onError?.(`녹음 오류: ${err?.message ?? 'unknown'}`);
    };
    // timeslice 250ms — iOS Safari 의 ondataavailable 미발화 회피, Android 도 안전.
    recorder.start(250);
    speaking = true;
    speakStartedAt = Date.now();
    console.debug('[ServerSTT] utterance start, mime=', recorderMime || '(default)');
  }

  function stopUtterance(): void {
    if (!recorder || !speaking) return;
    speaking = false;
    if (recorder.state !== 'inactive') {
      try { recorder.stop(); } catch { /* noop */ }
    }
  }

  function tick(): void {
    if (!analyser || !dataArray) return;
    analyser.getByteTimeDomainData(dataArray);
    let sumSquares = 0;
    for (let i = 0; i < dataArray.length; i++) {
      const v = (dataArray[i] - 128) / 128;
      sumSquares += v * v;
    }
    const rms = Math.sqrt(sumSquares / dataArray.length);
    // useAudioLevel 와 같은 4x amplify + smoothing
    const next = Math.min(1, rms * 4);
    level.value = level.value * 0.6 + next * 0.4;

    const now = Date.now();
    if (!speaking) {
      if (rms > VAD_RMS_START) {
        startUtterance();
        silenceStartedAt = 0;
      }
    } else {
      if (rms < VAD_RMS_STOP) {
        if (silenceStartedAt === 0) silenceStartedAt = now;
        else if (now - silenceStartedAt >= VAD_HANGOVER_MS) {
          stopUtterance();
        }
      } else {
        silenceStartedAt = 0;
      }
      // 안전망 — 너무 길면 강제 종료해서 chunk upload
      if (now - speakStartedAt >= VAD_MAX_UTTERANCE_MS) {
        stopUtterance();
      }
    }
    rafId = window.requestAnimationFrame(tick);
  }

  async function start(): Promise<void> {
    if (isRunning.value) return;
    stopRequested = false;
    if (typeof MediaRecorder === 'undefined') {
      options.onError?.('이 브라우저는 MediaRecorder 를 지원하지 않습니다.');
      return;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      options.onError?.(`마이크 권한이 필요합니다: ${(e as Error).message}`);
      return;
    }
    if (stopRequested) {
      // start() 진행 중 stop() 이 호출됨 — 스트림 즉시 해제.
      stream.getTracks().forEach((t) => t.stop());
      stream = null;
      return;
    }
    recorderMime = pickMimeType();

    const Ctor =
      window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctor) {
      options.onError?.('AudioContext 를 지원하지 않습니다.');
      teardownStream();
      return;
    }
    audioContext = new Ctor();
    // iOS Safari: AudioContext 가 suspended 상태로 생성될 수 있다 — user gesture (StartOverlay click) 이후라 resume 가능.
    if (audioContext.state === 'suspended') {
      try { await audioContext.resume(); } catch (e) { console.warn('[ServerSTT] AudioContext.resume failed:', e); }
    }
    const source = audioContext.createMediaStreamSource(stream);
    analyser = audioContext.createAnalyser();
    analyser.fftSize = 512;
    analyser.smoothingTimeConstant = 0.6;
    source.connect(analyser);
    dataArray = new Uint8Array(analyser.frequencyBinCount);
    isRunning.value = true;
    console.debug('[ServerSTT] started, ctx state=', audioContext.state);
    tick();
  }

  function stop(): void {
    stopRequested = true;
    if (rafId !== null) {
      window.cancelAnimationFrame(rafId);
      rafId = null;
    }
    stopUtterance();
    if (inflight) {
      inflight.abort();
      inflight = null;
    }
    teardownStream();
    isRunning.value = false;
    level.value = 0;
    speaking = false;
    silenceStartedAt = 0;
  }

  function teardownStream(): void {
    if (stream) {
      stream.getTracks().forEach((t) => t.stop());
      stream = null;
    }
    if (audioContext) {
      void audioContext.close();
      audioContext = null;
    }
    analyser = null;
    dataArray = null;
    recorder = null;
  }

  function refresh(): void {
    // 진행 중 utterance / 업로드 취소 — TTS echo 잔재 등 버퍼 비우는 용도 (useSTT.refresh 와 동일 의도).
    if (inflight) {
      inflight.abort();
      inflight = null;
    }
    if (speaking) {
      // 강제 중단해도 chunk 가 빈 채로 onstop → upload 스킵 됨 (MIN_UTTERANCE_MS 미만).
      speakStartedAt = Date.now();
      chunks = [];
      stopUtterance();
    }
  }

  async function upload(blob: Blob): Promise<void> {
    if (inflight) inflight.abort();
    const ctrl = new AbortController();
    inflight = ctrl;

    const fd = new FormData();
    const ext = blob.type.includes('mp4') ? 'm4a' : blob.type.includes('ogg') ? 'ogg' : 'webm';
    fd.append('audio', blob, `utterance.${ext}`);
    fd.append('language', 'ko');

    try {
      const res = await fetch('/api/stt', {
        method: 'POST',
        body: fd,
        signal: ctrl.signal,
        credentials: 'same-origin',
      });
      if (!res.ok) {
        options.onError?.(`음성 인식 실패 (${res.status})`);
        return;
      }
      const data = (await res.json()) as { text?: string };
      const text = (data.text ?? '').trim();
      console.debug('[ServerSTT] transcribed:', JSON.stringify(text));
      if (!text) return;
      const result: STTResult = { text, isFinal: true };
      options.onResult(result);
    } catch (e) {
      if ((e as Error).name === 'AbortError') return;
      options.onError?.(`음성 인식 네트워크 오류: ${(e as Error).message}`);
    } finally {
      if (inflight === ctrl) inflight = null;
    }
  }

  onBeforeUnmount(() => stop());

  return { start, stop, refresh, isRunning, level };
}
