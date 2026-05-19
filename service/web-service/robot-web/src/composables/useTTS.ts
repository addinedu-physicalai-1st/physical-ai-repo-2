import { onBeforeUnmount, ref } from 'vue';
import { useVoiceStore } from '@/stores/voice';

export interface UseTTSOptions {
  onStart?: (text: string) => void;
  onEnd?: () => void;
}

// Robot UI 는 서버 TTS 만 사용한다 (Edge MP3, 브라우저 speechSynthesis 비활성).
/** 1.0 = 원속. Edge rate 와 별도로 살짝만 올려 체감 속도 보정 (립싱크는 currentTime 기준이라 동기 유지). */
const TTS_PLAYBACK_RATE = 1.1;
const WAKE_ACK_LIPSYNC_TEXT = '네!';

function resolvePublicAssetPath(relativePath: string): string {
  const trimmed = relativePath.replace(/^\/+/, '');
  const base = import.meta.env.BASE_URL || '/';
  return `${base.replace(/\/+$/, '/')}${trimmed}`;
}

const WAKE_ACK_AUDIO_PATH = resolvePublicAssetPath('sounds/ne.mp3');

let lipSyncAudioContext: AudioContext | null = null;

function getLipSyncAudioContext(): AudioContext {
  if (!lipSyncAudioContext || lipSyncAudioContext.state === 'closed') {
    lipSyncAudioContext = new AudioContext();
  }
  return lipSyncAudioContext;
}

type LipSyncGraph = { source: MediaElementAudioSourceNode; analyser: AnalyserNode };

/** `createMediaElementSource` 는 첫 `play()` 전에 연결하는 것이 브라우저 호환에 유리 */
async function tryCreateLipSyncGraph(audio: HTMLAudioElement): Promise<LipSyncGraph | null> {
  try {
    const ctx = getLipSyncAudioContext();
    if (ctx.state === 'suspended') await ctx.resume();
    const source = ctx.createMediaElementSource(audio);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 512;
    analyser.smoothingTimeConstant = 0.62;
    source.connect(analyser);
    analyser.connect(ctx.destination);
    return { source, analyser };
  } catch (e) {
    console.warn('[TTS] Web Audio graph unavailable, lip envelope fallback:', e);
    return null;
  }
}

/** 쉼표·공백 등은 길이만 잡아먹고 입 모양이 안 나옴 → 한글 음절 + 숫자만으로 진행률 매핑 */
function hangulAndDigitsForLipsync(text: string): string {
  const out: string[] = [];
  for (const ch of text) {
    const c = ch.charCodeAt(0);
    if (c >= 0xac00 && c <= 0xd7a3) out.push(ch);
    else if (ch >= '0' && ch <= '9') out.push(ch);
  }
  if (out.length > 0) return out.join('');
  const compact = text.replace(/\s+/g, '').trim();
  return compact.length > 0 ? compact : ' ';
}

function lipsyncCharIndex(currentTime: number, duration: number, len: number): number {
  if (len <= 0) return 0;
  if (!Number.isFinite(duration) || duration <= 0) return 0;
  const p = Math.min(1, Math.max(0, currentTime / duration));
  return Math.min(len - 1, Math.floor(p * len));
}

/**
 * RAF + Web Audio RMS(가능 시) → speechEnvelope + 음절 동기 currentChar.
 */
function attachSpeechLipsync(
  audio: HTMLAudioElement,
  fullText: string,
  voiceStore: ReturnType<typeof useVoiceStore>,
  graph: LipSyncGraph | null,
): () => void {
  const syncText = hangulAndDigitsForLipsync(fullText);
  let rafId = 0;
  let lastIdx = -1;
  const analyser = graph?.analyser ?? null;
  const timeDomain = analyser ? new Uint8Array(analyser.fftSize) : null;

  const tickChar = () => {
    const len = syncText.length;
    if (len <= 0) {
      voiceStore.setCurrentChar('');
      return;
    }
    const idx = lipsyncCharIndex(audio.currentTime, audio.duration, len);
    if (idx !== lastIdx) {
      lastIdx = idx;
      voiceStore.setCurrentChar(syncText.charAt(idx));
    }
  };

  const sampleEnvelope = () => {
    if (analyser && timeDomain) {
      analyser.getByteTimeDomainData(timeDomain);
      let sum = 0;
      for (let i = 0; i < timeDomain.length; i++) {
        const v = (timeDomain[i]! - 128) / 128;
        sum += v * v;
      }
      const rms = Math.sqrt(sum / timeDomain.length);
      voiceStore.setSpeechEnvelope(Math.min(1, rms * 4.5));
      return;
    }
    const t = audio.currentTime;
    const wobble = Math.sin(t * 38) * 0.5 + Math.sin(t * 21) * 0.35;
    voiceStore.setSpeechEnvelope(0.08 + Math.abs(wobble) * 0.22);
  };

  const loop = () => {
    if (audio.paused || audio.ended) {
      voiceStore.setSpeechEnvelope(0);
      return;
    }
    tickChar();
    sampleEnvelope();
    rafId = requestAnimationFrame(loop);
  };

  const onPlaying = () => {
    cancelAnimationFrame(rafId);
    tickChar();
    rafId = requestAnimationFrame(loop);
  };

  const onPauseOrEnd = () => {
    cancelAnimationFrame(rafId);
    rafId = 0;
    voiceStore.setSpeechEnvelope(0);
  };

  audio.addEventListener('playing', onPlaying);
  audio.addEventListener('pause', onPauseOrEnd);
  audio.addEventListener('ended', onPauseOrEnd);
  audio.addEventListener('loadedmetadata', tickChar);

  return () => {
    cancelAnimationFrame(rafId);
    rafId = 0;
    audio.removeEventListener('playing', onPlaying);
    audio.removeEventListener('pause', onPauseOrEnd);
    audio.removeEventListener('ended', onPauseOrEnd);
    audio.removeEventListener('loadedmetadata', tickChar);
    if (graph) {
      try {
        graph.source.disconnect();
        graph.analyser.disconnect();
      } catch {
        /* already disconnected */
      }
    }
    lastIdx = -1;
    voiceStore.setSpeechEnvelope(0);
  };
}

export function useTTS(options: UseTTSOptions = {}): {
  speak: (text: string) => Promise<void>;
  playWakeAck: () => Promise<void>;
  cancel: () => void;
  isSpeaking: ReturnType<typeof ref<boolean>>;
} {
  const voiceStore = useVoiceStore();
  const isSpeaking = ref(false);
  let lipsyncDetach: (() => void) | null = null;
  let currentAudio: HTMLAudioElement | null = null;
  let currentObjectUrl: string | null = null;
  let ttsFetchAbort: AbortController | null = null;
  // cancel() 이 in-flight speak/playWakeAck 의 outer Promise 를 해소할 수 있게
  // 현재 재생 단계의 finish 콜백을 보관. pause() 는 ended/error 를 발생시키지
  // 않아 await 가 영영 끝나지 않는 문제를 막는다.
  let pendingDone: (() => void) | null = null;

  function clearLipsync(): void {
    lipsyncDetach?.();
    lipsyncDetach = null;
    voiceStore.setCurrentChar('');
    voiceStore.setSpeechEnvelope(0);
  }

  function audioBlobMime(buf: ArrayBuffer, contentTypeHeader: string | null): string {
    const ct = (contentTypeHeader || '').split(';')[0].trim().toLowerCase();
    if (ct === 'audio/mpeg' || ct === 'audio/mp3') return 'audio/mpeg';
    if (ct === 'audio/wav') return 'audio/wav';
    const u8 = new Uint8Array(buf, 0, 4);
    if (u8[0] === 0x52 && u8[1] === 0x49 && u8[2] === 0x46 && u8[3] === 0x46) return 'audio/wav';
    if (u8[0] === 0x49 && u8[1] === 0x44 && u8[2] === 0x33) return 'audio/mpeg';
    if (u8[0] === 0xff && (u8[1] & 0xe0) === 0xe0) return 'audio/mpeg';
    if (ct.startsWith('audio/')) return ct;
    return 'audio/mpeg';
  }

  async function speakFromHub(text: string): Promise<void> {
    ttsFetchAbort?.abort();
    const ac = new AbortController();
    ttsFetchAbort = ac;
    const audioUrl = `/api/voice/tts?text=${encodeURIComponent(text)}`;

    const finish = () => {
      clearLipsync();
      isSpeaking.value = false;
      voiceStore.setSpeaking(false);
      if (currentObjectUrl) {
        URL.revokeObjectURL(currentObjectUrl);
        currentObjectUrl = null;
      }
      currentAudio = null;
      if (ttsFetchAbort === ac) ttsFetchAbort = null;
      options.onEnd?.();
    };

    try {
      const res = await fetch(audioUrl, { signal: ac.signal });
      if (!res.ok) {
        console.error('[TTS] HTTP', res.status);
        finish();
        return;
      }
      const buf = await res.arrayBuffer();
      if (ac.signal.aborted) return;
      if (buf.byteLength < 64) {
        console.error('[TTS] Response too small');
        finish();
        return;
      }
      const mime = audioBlobMime(buf, res.headers.get('content-type'));
      const blob = new Blob([buf], { type: mime });
      currentObjectUrl = URL.createObjectURL(blob);
      const audio = new Audio(currentObjectUrl);
      audio.playbackRate = TTS_PLAYBACK_RATE;
      currentAudio = audio;

      const graph = await tryCreateLipSyncGraph(audio);
      lipsyncDetach = attachSpeechLipsync(audio, text, voiceStore, graph);

      await new Promise<void>((resolve) => {
        let settled = false;
        const done = () => {
          if (settled) return;
          settled = true;
          if (pendingDone === done) pendingDone = null;
          finish();
          resolve();
        };
        pendingDone = done;
        audio.onplaying = () => {
          isSpeaking.value = true;
          voiceStore.setSpeaking(true);
          options.onStart?.(text);
        };
        audio.onended = done;
        audio.onerror = () => {
          console.error('[TTS] audio element error');
          done();
        };
        audio.play().catch((err) => {
          console.error('[TTS] play failed:', err);
          done();
        });
      });
    } catch (e) {
      if ((e as Error).name === 'AbortError') return;
      console.error('[TTS] fetch failed:', e);
      finish();
    }
  }

  // wakeAck 는 매 호출마다 fresh Audio element 생성. 재사용 시 발생하던
  // "playing 으로 표시되는데 무음" 증상 (createMediaElementSource 잔존 또는
  // element internal sink 손상) 회피. 9KB MP3 라 HTTP cache 히트가 거의 instant.
  // Web Audio graph 안 거치므로 ctx suspend 영향 없음.

  function playWakeAck(): Promise<void> {
    return new Promise((resolve) => {
      if (typeof window === 'undefined') { resolve(); return; }

      // 이전 wake_ack 의 finish 가 아직 살아있으면 마무리시키고 새로 시작
      const prevDone = pendingDone;
      pendingDone = null;
      prevDone?.();

      // 매 호출마다 새 element — 재사용 시 발생하던 무음 재생 (browser cache 가
      // src 를 알아도 element 내부 audio output sink 가 silent 한 상태) 회피.
      // 9KB MP3 라 fresh fetch 도 HTTP cache 에서 instant.
      const audio = new Audio(WAKE_ACK_AUDIO_PATH);
      audio.preload = 'auto';
      audio.playbackRate = TTS_PLAYBACK_RATE;
      audio.volume = 1.0;
      audio.muted = false;

      currentAudio = audio;

      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        if (pendingDone === finish) pendingDone = null;
        try { audio.pause(); } catch { /* ignore */ }
        voiceStore.setCurrentChar('');
        voiceStore.setSpeechEnvelope(0);
        isSpeaking.value = false;
        voiceStore.setSpeaking(false);
        if (currentAudio === audio) currentAudio = null;
        options.onEnd?.();
        resolve();
      };
      pendingDone = finish;

      // 안전망 — 어떤 이벤트도 안 와도 2s 뒤 강제 finish.
      const safety = window.setTimeout(() => finish(), 2000);
      const clearSafety = () => window.clearTimeout(safety);

      audio.onplaying = () => {
        if (settled) return;
        isSpeaking.value = true;
        voiceStore.setSpeaking(true);
        options.onStart?.('네!');
      };
      audio.onended = () => { clearSafety(); finish(); };
      audio.onerror = async () => {
        clearSafety();
        try { await speakFromHub(WAKE_ACK_LIPSYNC_TEXT); }
        finally { finish(); }
      };
      audio.play().catch(async () => {
        clearSafety();
        try { await speakFromHub(WAKE_ACK_LIPSYNC_TEXT); }
        finally { finish(); }
      });
    });
  }

  async function speak(text: string): Promise<void> {
    if (typeof window === 'undefined') return;

    cancel();
    await speakFromHub(text);
  }

  function cancel(): void {
    ttsFetchAbort?.abort();
    ttsFetchAbort = null;
    if (currentAudio) {
      currentAudio.pause();
      currentAudio = null;
    }
    if (currentObjectUrl) {
      URL.revokeObjectURL(currentObjectUrl);
      currentObjectUrl = null;
    }
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      window.speechSynthesis.cancel();
    }
    clearLipsync();
    isSpeaking.value = false;
    voiceStore.setSpeaking(false);
    // in-flight speak/playWakeAck 의 outer Promise 를 즉시 해소. 이전엔 pause()
    // 만 부르고 ended/error 가 안 떠 await 가 영구 hang 되며 onEnd 콜백·audio
    // listener·MediaElementSource 가 누수됐다.
    const done = pendingDone;
    pendingDone = null;
    done?.();
  }

  onBeforeUnmount(() => {
    cancel();
  });

  return { speak, playWakeAck, cancel, isSpeaking };
}
