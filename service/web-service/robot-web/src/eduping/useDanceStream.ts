/**
 * dance unified stream 클라이언트.
 *
 * - WS open → 받은 frame parse.
 * - Audio: 받은 PCM chunk 를 Web Audio API 로 t_ms 정각에 schedule.
 *   `audioContext.currentTime` 기준 `streamEpoch + tMs/1000` 시점에 start.
 *   stream 시작 시점에 epoch 를 currentTime + warmup 으로 잡아 첫 frame 도 미래 시점에 시작 → underrun 회피.
 * - Motion: 가장 최근 frame 의 positions 를 reactive `currentSnapshot` 에 노출. OpenarmViewer 가 prop 으로 받음.
 * - End: end frame 또는 WS close → stop() callback.
 */
import { ref, shallowRef, type Ref } from 'vue';
import {
  FRAME_TYPE_AUDIO,
  FRAME_TYPE_END,
  FRAME_TYPE_HEADER,
  FRAME_TYPE_MOTION,
  parseFrame,
  type StreamHeader,
} from './danceStreamFraming';

export interface JointSnapshot {
  jointNames: string[];
  positions: Float32Array;
  tMs: number;
}

const WARMUP_S = 0.25; // 첫 audio chunk 까지 buffer 시간

export interface UseDanceStream {
  open: (slug: string) => void;
  close: () => void;
  currentSnapshot: Ref<JointSnapshot | null>;
  isPlaying: Ref<boolean>;
  durationMs: Ref<number>;
  elapsedMs: Ref<number>;
  error: Ref<string | null>;
  onEnd: (cb: () => void) => void;
}

export function useDanceStream(): UseDanceStream {
  const currentSnapshot = shallowRef<JointSnapshot | null>(null);
  const isPlaying = ref(false);
  const durationMs = ref(0);
  const elapsedMs = ref(0);
  const error = ref<string | null>(null);

  let ws: WebSocket | null = null;
  let audioCtx: AudioContext | null = null;
  let streamEpoch = 0;
  let header: StreamHeader | null = null;
  let elapsedTimer: number | null = null;
  let endCallback: (() => void) | null = null;
  let endingScheduled = false;

  function teardown(): void {
    if (ws) {
      ws.onmessage = ws.onclose = ws.onerror = null;
      try {
        ws.close();
      } catch {
        /* already closed */
      }
      ws = null;
    }
    if (elapsedTimer !== null) {
      window.clearInterval(elapsedTimer);
      elapsedTimer = null;
    }
    if (audioCtx) {
      void audioCtx.close().catch(() => {});
      audioCtx = null;
    }
    streamEpoch = 0;
    header = null;
    endingScheduled = false;
  }

  function close(): void {
    teardown();
    isPlaying.value = false;
  }

  function onEnd(cb: () => void): void {
    endCallback = cb;
  }

  function fireEnd(): void {
    if (endCallback) {
      const cb = endCallback;
      // teardown 이후 cb — cb 내부에서 다시 open() 불러도 안전
      teardown();
      isPlaying.value = false;
      cb();
    } else {
      close();
    }
  }

  function scheduleAudio(pcm: Uint8Array, tMs: number): void {
    if (!audioCtx || !header) return;
    // s16le → Float32 [-1, 1]
    const samples = pcm.byteLength / 2;
    const view = new DataView(pcm.buffer, pcm.byteOffset, pcm.byteLength);
    const f32 = new Float32Array(samples);
    for (let i = 0; i < samples; i++) {
      f32[i] = view.getInt16(i * 2, true) / 0x8000;
    }
    const audioBuf = audioCtx.createBuffer(1, samples, header.sample_rate);
    audioBuf.copyToChannel(f32, 0);
    const src = audioCtx.createBufferSource();
    src.buffer = audioBuf;
    src.connect(audioCtx.destination);
    const startAt = streamEpoch + tMs / 1000;
    // 이미 지나간 chunk 면 즉시 (드물게 backpressure 로 늦게 도착)
    src.start(Math.max(audioCtx.currentTime, startAt));
  }

  function handleFrame(ev: MessageEvent): void {
    if (!(ev.data instanceof ArrayBuffer)) return;
    const frame = parseFrame(ev.data);
    switch (frame.type) {
      case FRAME_TYPE_HEADER: {
        header = frame.header;
        durationMs.value =
          Math.max(frame.header.motion_duration_s, frame.header.audio_duration_s) * 1000;
        audioCtx = new (window.AudioContext ||
          (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext)();
        streamEpoch = audioCtx.currentTime + WARMUP_S;
        isPlaying.value = true;
        elapsedMs.value = 0;
        if (elapsedTimer !== null) window.clearInterval(elapsedTimer);
        const startedAt = performance.now() + WARMUP_S * 1000;
        elapsedTimer = window.setInterval(() => {
          const e = performance.now() - startedAt;
          elapsedMs.value = Math.max(0, Math.min(durationMs.value, e));
        }, 80);
        break;
      }

      case FRAME_TYPE_MOTION:
        if (header) {
          currentSnapshot.value = {
            jointNames: header.joint_names,
            positions: frame.positions,
            tMs: frame.tMs,
          };
        }
        break;

      case FRAME_TYPE_AUDIO:
        scheduleAudio(frame.pcm, frame.tMs);
        break;

      case FRAME_TYPE_END: {
        if (endingScheduled) return;
        endingScheduled = true;
        // 마지막 frame 의 tMs 만큼 기다린 뒤 종료 — audio 가 다 흐르도록
        const tailMs = Math.max(0, frame.tMs - elapsedMs.value);
        // +200ms: 마지막 audio chunk 의 재생 길이 만큼 여유 — t_ms 는 chunk 시작 시각이라 끝까지 들리려면 약간의 grace.
        window.setTimeout(fireEnd, tailMs + 200);
        break;
      }
    }
  }

  function open(slug: string): void {
    teardown();
    error.value = null;
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${proto}//${window.location.host}/api/eduping/dance/${encodeURIComponent(slug)}/stream`;
    ws = new WebSocket(url);
    ws.binaryType = 'arraybuffer';
    ws.onmessage = handleFrame;
    ws.onerror = () => {
      error.value = '스트림 연결 오류';
    };
    ws.onclose = (ev) => {
      // end frame 으로 정상 종료된 경우는 이미 fireEnd 가 처리
      if (!endingScheduled) {
        if (!ev.wasClean) {
          error.value = error.value ?? `스트림 끊김 (${ev.code})`;
        }
        fireEnd();
      }
    };
  }

  return {
    open,
    close,
    currentSnapshot,
    isPlaying,
    durationMs,
    elapsedMs,
    error,
    onEnd,
  };
}
