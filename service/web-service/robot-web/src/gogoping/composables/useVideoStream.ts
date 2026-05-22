import { ref, type Ref } from 'vue';

export type StreamStatus = 'connecting' | 'open' | 'streaming' | 'closed';
export interface UseVideoStream {
  frameUrl: Ref<string | null>;
  currentBlob: Ref<Blob | null>;
  status: Ref<StreamStatus>;
  stop(): void;
}
export interface VideoStreamDeps {
  WS?: typeof WebSocket;
  createObjectURL?: (b: Blob) => string;
  revokeObjectURL?: (u: string) => void;
  uuid?: () => string;
}

const PATH = '/ws/video-stream';
// WS binary frame header: "!BBBBIQI" = 1+1+1+1+4+8+4 = 20 bytes
// (protocol.py WS_FRAME_HEADER_SIZE — distinct from UDP 28B VIDEO_HEADER_SIZE)
const HEADER_BYTES = 20;

export function useVideoStream(
  robot: 'gogoping' | 'eduping' | 'noriarm',
  deps: VideoStreamDeps = {},
  stream = 0,
): UseVideoStream {
  const WSImpl = deps.WS ?? globalThis.WebSocket;
  const createURL = deps.createObjectURL
    ?? ((b: Blob) => URL.createObjectURL(b));
  const revokeURL = deps.revokeObjectURL
    ?? ((u: string) => URL.revokeObjectURL(u));
  const uuid = deps.uuid ?? (() =>
    (globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2))
  );

  const frameUrl = ref<string | null>(null);
  const currentBlob = ref<Blob | null>(null);
  const status = ref<StreamStatus>('connecting');
  let prevUrl: string | null = null;
  const clientId = `robot-web-${uuid()}`;

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
    if (stopped) return;
    if (reconnectTimer) return;
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
    ws.onerror = () => { /* keep status; rely on onclose */ };

    ws.onmessage = (ev: MessageEvent) => {
      const data = ev.data;
      if (typeof data === 'string') {
        let m: { type?: string; ts_ms?: number };
        try { m = JSON.parse(data); } catch { return; }
        if (m.type === 'welcome') {
          ws.send(JSON.stringify({
            type: 'hello',
            client_id: clientId,
            client_kind: 'viewer',
            ts_ms: Date.now(),
          }));
        } else if (m.type === 'hello_ack') {
          ws.send(JSON.stringify({
            type: 'subscribe',
            robot,
            stream,
            ts_ms: Date.now(),
          }));
          backoffMs = 1000;
        } else if (m.type === 'ping') {
          ws.send(JSON.stringify({ type: 'pong', ts_ms: Date.now() }));
        }
        return;
      }
      const buf = data instanceof ArrayBuffer ? data : null;
      if (!buf || buf.byteLength <= HEADER_BYTES) return;
      const jpeg = new Uint8Array(buf, HEADER_BYTES);
      const blob = new Blob([jpeg], { type: 'image/jpeg' });
      currentBlob.value = blob;
      const url = createURL(blob);
      if (prevUrl) revokeURL(prevUrl);
      prevUrl = url;
      frameUrl.value = url;
      status.value = 'streaming';
    };
  }

  connect();

  function stop(): void {
    stopped = true;
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    try { currentWs?.close(); } catch { /* ignore */ }
    if (prevUrl) { revokeURL(prevUrl); prevUrl = null; }
    frameUrl.value = null;
  }

  return { frameUrl, currentBlob, status, stop };
}
