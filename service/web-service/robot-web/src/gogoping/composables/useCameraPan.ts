import { ref, type Ref } from 'vue';

export interface PanTilt { pan: number; tilt: number }
export interface CameraPanDeps {
  fetch?: typeof fetch;
  WS?: typeof WebSocket;
  now?: () => number;
}
export interface UseCameraPan {
  setpoint: Ref<PanTilt>;
  updateSetpoint(dpan: number, dtilt: number): void;
  center(): void;
  connState: Ref<'closed' | 'connecting' | 'open'>;
  lastError: Ref<string | null>;
  stop(): void;
}

const PAN_MIN = 5, PAN_MAX = 175, PAN_CENTER = 90;
const TILT_MIN = 30, TILT_MAX = 150, TILT_CENTER = 90;
const THROTTLE_MS = 50;
const CMD_URL = '/camera_pan/cmd';
const STATE_PATH = '/camera_pan/state';

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

export function useCameraPan(deps: CameraPanDeps = {}): UseCameraPan {
  const fetchFn = deps.fetch ?? globalThis.fetch.bind(globalThis);
  const WSImpl  = deps.WS    ?? globalThis.WebSocket;
  const now     = deps.now   ?? Date.now;

  const setpoint = ref<PanTilt>({ pan: PAN_CENTER, tilt: TILT_CENTER });
  const connState = ref<'closed' | 'connecting' | 'open'>('closed');
  const lastError = ref<string | null>(null);

  let lastPostAt = 0;
  let pendingTimer: ReturnType<typeof setTimeout> | null = null;

  async function postNow(): Promise<void> {
    lastPostAt = now();
    try {
      const r = await fetchFn(CMD_URL, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ pan: setpoint.value.pan, tilt: setpoint.value.tilt }),
      });
      if (!r.ok) {
        lastError.value = `POST ${CMD_URL} failed: ${r.status}`;
      } else {
        lastError.value = null;
      }
    } catch (err) {
      lastError.value = `POST ${CMD_URL} failed: ${String(err)}`;
    }
  }

  function schedulePost(): void {
    const elapsed = now() - lastPostAt;
    if (elapsed >= THROTTLE_MS) {
      void postNow();
      return;
    }
    if (pendingTimer) return;
    pendingTimer = setTimeout(() => {
      pendingTimer = null;
      void postNow();
    }, THROTTLE_MS - elapsed);
  }

  function updateSetpoint(dpan: number, dtilt: number): void {
    setpoint.value = {
      pan:  clamp(setpoint.value.pan  + dpan,  PAN_MIN,  PAN_MAX),
      tilt: clamp(setpoint.value.tilt + dtilt, TILT_MIN, TILT_MAX),
    };
    schedulePost();
  }

  function center(): void {
    setpoint.value = { pan: PAN_CENTER, tilt: TILT_CENTER };
    if (pendingTimer) { clearTimeout(pendingTimer); pendingTimer = null; }
    void postNow();
  }

  const wsUrl = (() => {
    const loc = (globalThis as { location?: Location }).location;
    if (!loc) return STATE_PATH;
    const proto = loc.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${proto}//${loc.host}${STATE_PATH}`;
  })();

  connState.value = 'connecting';
  const ws = new WSImpl(wsUrl);
  ws.onopen = () => { connState.value = 'open'; };
  ws.onclose = () => { connState.value = 'closed'; };
  ws.onerror = () => { connState.value = 'closed'; };
  ws.onmessage = (ev: MessageEvent) => {
    try {
      const m = JSON.parse(String(ev.data));
      const pan = typeof m.pan_deg === 'number' ? m.pan_deg : null;
      const tilt = typeof m.tilt_deg === 'number' ? m.tilt_deg : null;
      if (pan !== null || tilt !== null) {
        setpoint.value = {
          pan:  pan  !== null ? clamp(pan,  PAN_MIN,  PAN_MAX)  : setpoint.value.pan,
          tilt: tilt !== null ? clamp(tilt, TILT_MIN, TILT_MAX) : setpoint.value.tilt,
        };
      }
    } catch { /* ignore */ }
  };

  function stop(): void {
    if (pendingTimer) { clearTimeout(pendingTimer); pendingTimer = null; }
    try { ws.close(); } catch { /* ignore */ }
  }

  return { setpoint, updateSetpoint, center, connState, lastError, stop };
}
