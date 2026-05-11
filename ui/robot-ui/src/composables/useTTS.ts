import { onBeforeUnmount, ref } from 'vue';
import { useVoiceStore } from '@/stores/voice';

export interface UseTTSOptions {
  onStart?: (text: string) => void;
  onEnd?: () => void;
}

// Robot UI 는 서버 TTS 만 사용한다 (Edge MP3, 브라우저 speechSynthesis 비활성).
const USE_SERVER_TTS = true;
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
  let wakeAckAudio: HTMLAudioElement | null = null;
  let ttsFetchAbort: AbortController | null = null;

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
        const done = () => {
          finish();
          resolve();
        };
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

  function primeWakeAck(): void {
    if (typeof window === 'undefined') return;
    if (wakeAckAudio) return;
    wakeAckAudio = new Audio(WAKE_ACK_AUDIO_PATH);
    wakeAckAudio.preload = 'auto';
    wakeAckAudio.load();
  }

  function playWakeAck(): Promise<void> {
    return new Promise((resolve) => {
      if (typeof window === 'undefined') {
        resolve();
        return;
      }
      cancel();
      primeWakeAck();

      void (async () => {
        const audio = wakeAckAudio
          ? (wakeAckAudio.cloneNode(true) as HTMLAudioElement)
          : new Audio(WAKE_ACK_AUDIO_PATH);
        audio.playbackRate = TTS_PLAYBACK_RATE;
        currentAudio = audio;
        const graph = await tryCreateLipSyncGraph(audio);
        lipsyncDetach = attachSpeechLipsync(audio, WAKE_ACK_LIPSYNC_TEXT, voiceStore, graph);
        let settled = false;

        const finish = () => {
          if (settled) return;
          settled = true;
          clearLipsync();
          isSpeaking.value = false;
          voiceStore.setSpeaking(false);
          if (currentAudio === audio) currentAudio = null;
          options.onEnd?.();
          resolve();
        };

        audio.onplaying = () => {
          isSpeaking.value = true;
          voiceStore.setSpeaking(true);
          options.onStart?.('네!');
        };
        audio.onended = finish;
        audio.onerror = async () => {
          // static mp3 서빙/디코딩 실패 시 허브 TTS 로 degrade
          try {
            await speakFromHub(WAKE_ACK_LIPSYNC_TEXT);
          } finally {
            finish();
          }
        };
        audio.play().catch(async () => {
          try {
            await speakFromHub(WAKE_ACK_LIPSYNC_TEXT);
          } finally {
            finish();
          }
        });
      })();
    });
  }

  async function speak(text: string): Promise<void> {
    if (typeof window === 'undefined') return;

    cancel();
    if (!USE_SERVER_TTS) {
      throw new Error('Server TTS is required.');
    }
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
  }

  onBeforeUnmount(() => {
    cancel();
  });

  primeWakeAck();
  return { speak, playWakeAck, cancel, isSpeaking };
}
