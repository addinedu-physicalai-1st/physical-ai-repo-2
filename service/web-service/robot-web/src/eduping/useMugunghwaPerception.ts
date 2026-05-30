/**
 * 무궁화 device-local perception 연동.
 *
 *   /ws/eduping/mugunghwa?role=ui          JSON 이벤트 구독 + 명령 송신
 *   /ws/eduping/mugunghwa/video?role=consumer  JPEG 프레임 → canvas PIP
 *
 * 노드(EduPing)가 사람 추적/움직임을 device-local 판정. 브라우저는 표시 + 진행만.
 */
import { onUnmounted, ref, type Ref } from 'vue';

export type PerceptionEvent =
  | { type: 'registered'; childId: number }
  | { type: 'eliminated'; childIds: number[] }
  | { type: 'motion' }
  | { type: 'reached'; childId: number | null };

/** WS text 한 줄을 PerceptionEvent 로. peer/presence·미지원 타입·오류는 null. */
export function parsePerceptionEvent(raw: string): PerceptionEvent | null {
  let msg: Record<string, unknown>;
  try {
    msg = JSON.parse(raw) as Record<string, unknown>;
  } catch {
    return null;
  }
  switch (msg.type) {
    case 'registered':
      return typeof msg.child_id === 'number'
        ? { type: 'registered', childId: msg.child_id }
        : null;
    case 'eliminated':
      return Array.isArray(msg.child_ids)
        ? { type: 'eliminated', childIds: (msg.child_ids as number[]) }
        : null;
    case 'motion':
      return { type: 'motion' };
    case 'reached':
      return {
        type: 'reached',
        childId: typeof msg.child_id === 'number' ? msg.child_id : null,
      };
    default:
      return null;
  }
}

export interface PerceptionHandlers {
  onRegistered?: (childId: number) => void;
  onEliminated?: (childIds: number[]) => void;
  onMotion?: () => void;
  onReached?: (childId: number | null) => void;
}

const EVENT_PATH = '/ws/eduping/mugunghwa?role=ui';
const VIDEO_PATH = '/ws/eduping/mugunghwa/video?role=consumer';

function wsUrl(path: string): string {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${location.host}${path}`;
}

export function useMugunghwaPerception(handlers: PerceptionHandlers) {
  const pipCanvas: Ref<HTMLCanvasElement | null> = ref(null);
  let eventWs: WebSocket | null = null;
  let videoWs: WebSocket | null = null;

  function send(obj: Record<string, unknown>): void {
    if (eventWs && eventWs.readyState === WebSocket.OPEN) {
      eventWs.send(JSON.stringify(obj));
    }
  }

  async function drawJpeg(blob: Blob): Promise<void> {
    const c = pipCanvas.value;
    if (!c) return;
    let bm: ImageBitmap;
    try {
      bm = await createImageBitmap(blob);
    } catch {
      return;
    }
    if (c.width !== bm.width || c.height !== bm.height) {
      c.width = bm.width;
      c.height = bm.height;
    }
    c.getContext('2d')?.drawImage(bm, 0, 0);
    bm.close();
  }

  function connect(): void {
    eventWs = new WebSocket(wsUrl(EVENT_PATH));
    eventWs.onmessage = (ev: MessageEvent): void => {
      if (typeof ev.data !== 'string') return;
      const e = parsePerceptionEvent(ev.data);
      if (!e) return;
      if (e.type === 'registered') handlers.onRegistered?.(e.childId);
      else if (e.type === 'eliminated') handlers.onEliminated?.(e.childIds);
      else if (e.type === 'motion') handlers.onMotion?.();
      else if (e.type === 'reached') handlers.onReached?.(e.childId);
    };

    videoWs = new WebSocket(wsUrl(VIDEO_PATH));
    videoWs.binaryType = 'blob';
    videoWs.onmessage = (ev: MessageEvent): void => {
      if (ev.data instanceof Blob) void drawJpeg(ev.data);
    };
  }

  function disconnect(): void {
    eventWs?.close();
    videoWs?.close();
    eventWs = null;
    videoWs = null;
  }

  /** PIP canvas → 감정 캡처용 MediaStream (HealthCheckCamera 패턴). */
  function captureStream(fps = 5): MediaStream | null {
    const c = pipCanvas.value;
    return c ? c.captureStream(fps) : null;
  }

  onUnmounted(disconnect);

  return {
    pipCanvas,
    connect,
    disconnect,
    captureStream,
    registerStart: () => send({ type: 'register_start' }),
    registerStop: () => send({ type: 'register_stop' }),
    observeStart: () => send({ type: 'observe_start' }),
    observeStop: () => send({ type: 'observe_stop' }),
    reset: () => send({ type: 'reset' }),
    idle: () => send({ type: 'idle' }),
  };
}
