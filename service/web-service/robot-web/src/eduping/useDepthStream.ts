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
import { decompress as zstdDecompress } from 'fzstd';

const PATH = '/ws/depth-stream';
const HEADER_SIZE = 60;
const MAGIC = 0x44505448; // "DPTH" big-endian as uint32

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
  let frameCb: ((frame: DecodedDepthFrame) => void) | null = null;

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
      const frame = decodeFrame(data);
      if (frame === null) return;
      status.value = 'streaming';
      lastFrameAtMs.value = Date.now();
      if (frameCb) {
        try { frameCb(frame); } catch (e) { console.error('depth onFrame cb:', e); }
      }
    };
  }

  connect();

  function stop(): void {
    stopped = true;
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    try { currentWs?.close(); } catch { /* ignore */ }
    frameCb = null;
  }

  function onFrame(cb: (frame: DecodedDepthFrame) => void): void {
    frameCb = cb;
  }

  return { status, lastFrameAtMs, onFrame, stop };
}

function decodeFrame(buf: ArrayBuffer): DecodedDepthFrame | null {
  if (buf.byteLength < HEADER_SIZE) return null;
  const dv = new DataView(buf);
  const magic = dv.getUint32(0, false);
  if (magic !== MAGIC) return null;
  const version = dv.getUint8(4);
  if (version !== 1) return null;
  // robotId at offset 5 — 클라이언트가 subscribe 한 robot 만 흘러오므로 검증 생략.
  const frameSeq = dv.getUint32(8, false);
  // ts_ms uint64 BE — JS Number 안전 범위는 2^53 까지, unix ms 는 2^53 안 ok.
  const tsHi = dv.getUint32(12, false);
  const tsLo = dv.getUint32(16, false);
  const tsMs = tsHi * 0x1_0000_0000 + tsLo;
  const depthW = dv.getUint16(20, false);
  const depthH = dv.getUint16(22, false);
  const colorW = dv.getUint16(24, false);
  const colorH = dv.getUint16(26, false);
  const fx = dv.getFloat32(28, false);
  const fy = dv.getFloat32(32, false);
  const cx = dv.getFloat32(36, false);
  const cy = dv.getFloat32(40, false);
  const depthScale = dv.getFloat32(44, false);
  const depthMinMm = dv.getUint16(48, false);
  const depthMaxMm = dv.getUint16(50, false);
  const depthSize = dv.getUint32(52, false);
  const colorSize = dv.getUint32(56, false);

  if (HEADER_SIZE + depthSize + colorSize !== buf.byteLength) return null;

  const depthZstd = new Uint8Array(buf, HEADER_SIZE, depthSize);
  const colorBytes = new Uint8Array(buf, HEADER_SIZE + depthSize, colorSize);

  let depthRaw: Uint8Array;
  try {
    depthRaw = zstdDecompress(depthZstd);
  } catch (e) {
    console.warn('zstd decompress failed:', e);
    return null;
  }
  if (depthRaw.byteLength !== depthW * depthH * 2) {
    console.warn(
      `depth size mismatch: got ${depthRaw.byteLength}, expected ${depthW * depthH * 2}`,
    );
    return null;
  }
  // wire format = uint16 LE (Python np.uint16 default)
  const depth = new Uint16Array(
    depthRaw.buffer, depthRaw.byteOffset, depthW * depthH,
  );

  const colorBlob = new Blob([colorBytes], { type: 'image/jpeg' });

  return {
    frameSeq, tsMs,
    depthW, depthH, colorW, colorH,
    fx, fy, cx, cy, depthScale,
    depthMinMm, depthMaxMm,
    depth, colorBlob,
  };
}
