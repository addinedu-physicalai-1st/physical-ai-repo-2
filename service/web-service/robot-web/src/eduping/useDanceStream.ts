/**
 * 율동 모드 단일 양방향 WS 채널.
 *
 * - connect() : 팝업 mount 시 1회. 이후 unmount 까지 유지.
 * - play(slug): 곡 시작 — `{type:"play", slug}` 송신.
 * - stop()    : `{type:"stop"}` 송신. 백엔드가 home ramp motion frame 을 같은 채널로 push.
 * - close()   : 팝업 unmount 시. WS close + AudioContext close.
 *
 * 서버로부터 받은 frame:
 *  - HEADER : 새 segment 시작 (dance 또는 home ramp). audio 스케줄링 epoch 리셋.
 *  - MOTION : currentSnapshot 갱신.
 *  - AUDIO  : Web Audio API 로 t_ms 정각 schedule.
 *  - END    : segment 종료 → isPlaying=false, onEnd callback.
 *
 * Audio: AudioContext 는 처음 HEADER 받을 때 lazy 생성, close() 까지 재사용.
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

const WARMUP_S = 0.25;

export interface UseDanceStream {
  connect: () => void;
  play: (slug: string) => void;
  stop: () => void;
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

  // 모션 프레임을 오디오와 동일한 streamEpoch 기준으로 적용하기 위한 버퍼.
  // 수신 즉시 적용하면 오디오보다 WARMUP_S 만큼 앞서 움직임 → 버퍼에 넣고 rAF 루프가 꺼냄.
  interface MotionEntry { tMs: number; positions: Float32Array }
  const motionQueue: MotionEntry[] = [];
  let motionRafId: number | null = null;

  function driveMotion(): void {
    if (audioCtx && streamEpoch > 0 && header) {
      const now = audioCtx.currentTime;
      while (motionQueue.length > 0 && streamEpoch + motionQueue[0].tMs / 1000 <= now) {
        const entry = motionQueue.shift()!;
        currentSnapshot.value = {
          jointNames: header.joint_names,
          positions: entry.positions,
          tMs: entry.tMs,
        };
      }
    }
    if (isPlaying.value || motionQueue.length > 0) {
      motionRafId = requestAnimationFrame(driveMotion);
    } else {
      motionRafId = null;
    }
  }

  function url(): string {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${proto}//${window.location.host}/api/eduping/dance/stream`;
  }

  function resetSegment(): void {
    if (elapsedTimer !== null) {
      window.clearInterval(elapsedTimer);
      elapsedTimer = null;
    }
    if (motionRafId !== null) {
      cancelAnimationFrame(motionRafId);
      motionRafId = null;
    }
    motionQueue.length = 0;
    streamEpoch = 0;
    header = null;
  }

  function fireEnd(): void {
    isPlaying.value = false;
    resetSegment();
    if (endCallback) endCallback();
  }

  function scheduleAudio(pcm: Uint8Array, tMs: number): void {
    if (!audioCtx || !header) return;
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
    src.start(Math.max(audioCtx.currentTime, streamEpoch + tMs / 1000));
  }

  function handleBinary(buf: ArrayBuffer): void {
    const frame = parseFrame(buf);
    switch (frame.type) {
      case FRAME_TYPE_HEADER: {
        header = frame.header;
        durationMs.value =
          Math.max(frame.header.motion_duration_s, frame.header.audio_duration_s) * 1000;
        if (!audioCtx) {
          audioCtx = new (window.AudioContext ||
            (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext)();
        }
        streamEpoch = audioCtx.currentTime + WARMUP_S;
        isPlaying.value = true;
        elapsedMs.value = 0;
        motionQueue.length = 0;
        if (elapsedTimer !== null) window.clearInterval(elapsedTimer);
        const startedAt = performance.now() + WARMUP_S * 1000;
        elapsedTimer = window.setInterval(() => {
          const e = performance.now() - startedAt;
          elapsedMs.value = Math.max(0, Math.min(durationMs.value, e));
        }, 80);
        // 모션 드라이버 시작 — 버퍼에 쌓인 프레임을 오디오 타임라인에 맞춰 소비.
        if (motionRafId !== null) cancelAnimationFrame(motionRafId);
        motionRafId = requestAnimationFrame(driveMotion);
        break;
      }
      case FRAME_TYPE_MOTION:
        if (header) {
          motionQueue.push({ tMs: frame.tMs, positions: frame.positions });
        }
        break;
      case FRAME_TYPE_AUDIO:
        scheduleAudio(frame.pcm, frame.tMs);
        break;
      case FRAME_TYPE_END: {
        // 마지막 audio chunk 가 끝까지 들리도록 약간의 grace 후 종료.
        const tailMs = Math.max(0, frame.tMs - elapsedMs.value) + 200;
        window.setTimeout(fireEnd, tailMs);
        break;
      }
    }
  }

  function handleText(text: string): void {
    try {
      const ev = JSON.parse(text);
      if (ev?.type === 'error') {
        error.value = String(ev.msg ?? 'stream error');
      }
    } catch {
      /* ignore non-json */
    }
  }

  function connect(): void {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
    error.value = null;
    ws = new WebSocket(url());
    ws.binaryType = 'arraybuffer';
    ws.onmessage = (ev) => {
      if (ev.data instanceof ArrayBuffer) handleBinary(ev.data);
      else if (typeof ev.data === 'string') handleText(ev.data);
    };
    ws.onerror = () => {
      error.value = '스트림 연결 오류';
    };
    ws.onclose = (ev) => {
      ws = null;
      if (!ev.wasClean && !error.value) error.value = `스트림 끊김 (${ev.code})`;
      isPlaying.value = false;
      resetSegment();
    };
  }

  function send(obj: object): void {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify(obj));
  }

  function play(slug: string): void {
    error.value = null;
    send({ type: 'play', slug });
  }

  function stop(): void {
    send({ type: 'stop' });
  }

  function close(): void {
    if (ws) {
      ws.onmessage = ws.onclose = ws.onerror = null;
      try {
        ws.close();
      } catch {
        /* already closed */
      }
      ws = null;
    }
    if (audioCtx) {
      void audioCtx.close().catch(() => {});
      audioCtx = null;
    }
    resetSegment();
    isPlaying.value = false;
    currentSnapshot.value = null;
    elapsedMs.value = 0;
    durationMs.value = 0;
  }

  function onEnd(cb: () => void): void {
    endCallback = cb;
  }

  return {
    connect,
    play,
    stop,
    close,
    currentSnapshot,
    isPlaying,
    durationMs,
    elapsedMs,
    error,
    onEnd,
  };
}
