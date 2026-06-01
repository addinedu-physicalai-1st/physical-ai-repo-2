/**
 * /ws/depth-stream WebSocket consumer + binary decoder.
 *
 * 와이어 포맷은 service/control-service/control_service/streaming/depth_protocol.py 의
 * encode_depth_frame() 와 1:1 — 60B 헤더 + zstd-compressed uint16 depth + JPEG color.
 *
 * 매 frame 마다 Vue reactivity 를 트리거하지 않기 위해 callback-only API.
 * three.js 렌더 루프가 가장 최근에 받은 frame 을 매 RAF 마다 텍스처 업로드.
 */
import { ref, type Ref } from 'vue';

const PATH = '/ws/depth-stream';

export type DepthStreamStatus = 'connecting' | 'open' | 'streaming' | 'closed';

export interface DecodedDepthFrame {
  frameSeq: number;
  tsMs: number;
  depthW: number;
  depthH: number;
  colorW: number;
  colorH: number;
  fx: number;
  fy: number;
  cx: number;
  cy: number;
  depthScale: number; // meters per uint16 unit
  depthMinMm: number;
  depthMaxMm: number;
  depth: Uint16Array; // decompressed, length = depthW * depthH
  colorBlob: Blob; // JPEG (image/jpeg)
}

export interface UseDepthStream {
  status: Ref<DepthStreamStatus>;
  /** Last decoded frame time (ms). 0 until first binary frame. */
  lastFrameAtMs: Ref<number>;
  onFrame(cb: (frame: DecodedDepthFrame) => void): void;
  stop(): void;
}

export interface DepthStreamDeps {
  WS?: typeof WebSocket;
  uuid?: () => string;
}

export function useDepthStream(
  robot: 'gogoping' | 'eduping' | 'noriarm',
  deps: DepthStreamDeps = {},
): UseDepthStream {
  const WSImpl = deps.WS ?? globalThis.WebSocket;
  const uuid = deps.uuid ?? (() =>
    (globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2))
  );

  const status = ref<DepthStreamStatus>('connecting');
  const lastFrameAtMs = ref(0);
  const clientId = `depth-${uuid()}`;
  // Multiple subscribers (DepthViewer.handleFrame + useDepthCloudInScene + useDepthVoxelInScene
  // 등) 가 같은 stream 을 공유하므로 listener 배열로 fan-out. 이전 single-callback
  // 구조는 새 onFrame 호출이 기존 callback 을 덮어써서 hand 추적 + cloud 가 동시에
  // 살아있지 못했음 (마지막 mount 만 frame 수신).
  const frameListeners: Array<(frame: DecodedDepthFrame) => void> = [];

  // zstd decode runs in a worker (off the main thread) — see depthDecode.worker.ts.
  // The raw WS ArrayBuffer is transferred in; the decoded frame (depth buffer
  // transferred back) is fanned out to the render listeners here on the main thread.
  const decodeWorker = new Worker(
    new URL('./depthDecode.worker.ts', import.meta.url),
    { type: 'module' },
  );
  decodeWorker.onmessage = (e: MessageEvent<{ ok: boolean; frame?: DecodedDepthFrame }>) => {
    if (!e.data.ok || !e.data.frame) return;
    status.value = 'streaming';
    lastFrameAtMs.value = Date.now();
    for (const cb of frameListeners) {
      try { cb(e.data.frame); } catch (err) { console.error('depth onFrame cb:', err); }
    }
  };

  const wsUrl = (() => {
    const loc = (globalThis as { location?: Location }).location;
    if (!loc) return PATH;
    const proto = loc.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${proto}//${loc.host}${PATH}`;
  })();

  let currentWs: WebSocket | null = null;
  let stopped = false;
  let backoffMs = 1000;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  function scheduleReconnect(): void {
    if (stopped || reconnectTimer) return;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      backoffMs = Math.min(backoffMs * 2, 30000);
      connect();
    }, backoffMs);
  }

  function connect(): void {
    status.value = 'connecting';
    const ws = new WSImpl(wsUrl);
    currentWs = ws;
    ws.binaryType = 'arraybuffer';

    ws.onopen = () => { status.value = 'open'; };
    ws.onclose = () => { status.value = 'closed'; scheduleReconnect(); };
    ws.onerror = () => { /* rely on onclose */ };

    ws.onmessage = (ev: MessageEvent) => {
      const data = ev.data;
      if (typeof data === 'string') {
        let m: { type?: string };
        try { m = JSON.parse(data); } catch { return; }
        if (m.type === 'welcome') {
          ws.send(JSON.stringify({
            type: 'hello', client_id: clientId, client_kind: 'depth-viewer',
            ts_ms: Date.now(),
          }));
        } else if (m.type === 'hello_ack') {
          ws.send(JSON.stringify({
            type: 'subscribe', robot, stream: 0, ts_ms: Date.now(),
          }));
          backoffMs = 1000;
        } else if (m.type === 'ping') {
          ws.send(JSON.stringify({ type: 'pong', ts_ms: Date.now() }));
        }
        return;
      }
      if (!(data instanceof ArrayBuffer)) return;
      // Hand the raw frame to the decode worker (transfer → zero-copy). The decoded
      // frame comes back via decodeWorker.onmessage and is fanned out there.
      decodeWorker.postMessage(data, [data]);
    };
  }

  connect();

  function stop(): void {
    stopped = true;
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    try { currentWs?.close(); } catch { /* ignore */ }
    try { decodeWorker.terminate(); } catch { /* ignore */ }
    frameListeners.length = 0;
  }

  function onFrame(cb: (frame: DecodedDepthFrame) => void): void {
    if (!frameListeners.includes(cb)) frameListeners.push(cb);
  }

  return { status, lastFrameAtMs, onFrame, stop };
}

