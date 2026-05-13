/**
 * /api/eduping/state WS 구독.
 *
 * server/control/eduping/router.py 의 `/api/eduping/state` 가 100ms 주기로 broadcast 하는
 * snapshot { ts, leader: {joint_names, positions, age_s} | null, follower: ... | null } 을
 * 그대로 reactive 로 노출. 자동 재연결 (1.5s).
 */
import { onBeforeUnmount, ref, type Ref } from 'vue';

export interface JointSnapshot {
  joint_names: string[];
  positions: number[];
  age_s: number;
}

export interface StateSnapshot {
  ts: number;
  leader: JointSnapshot | null;
  follower: JointSnapshot | null;
}

export interface UseEdupingStateWs {
  connected: Ref<boolean>;
  leader: Ref<JointSnapshot | null>;
  follower: Ref<JointSnapshot | null>;
  start: () => void;
  stop: () => void;
}

const RECONNECT_DELAY_MS = 1500;

export function useEdupingStateWs(): UseEdupingStateWs {
  const connected = ref(false);
  const leader = ref<JointSnapshot | null>(null);
  const follower = ref<JointSnapshot | null>(null);

  let ws: WebSocket | null = null;
  let stopRequested = false;
  let reconnectTimer: number | null = null;

  function url(): string {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${proto}//${location.host}/api/eduping/state`;
  }

  function connect(): void {
    if (stopRequested) return;
    try {
      ws = new WebSocket(url());
    } catch (err) {
      console.warn('[edupingState] WS construct 실패', err);
      scheduleReconnect();
      return;
    }
    ws.onopen = () => {
      connected.value = true;
    };
    ws.onmessage = (ev) => {
      try {
        const snap = JSON.parse(ev.data) as StateSnapshot;
        leader.value = snap.leader;
        follower.value = snap.follower;
      } catch (err) {
        console.warn('[edupingState] parse 실패', err);
      }
    };
    ws.onerror = () => {
      // close 가 뒤따라 옴 — 거기서 재연결.
    };
    ws.onclose = () => {
      connected.value = false;
      ws = null;
      scheduleReconnect();
    };
  }

  function scheduleReconnect(): void {
    if (stopRequested || reconnectTimer != null) return;
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, RECONNECT_DELAY_MS);
  }

  function start(): void {
    stopRequested = false;
    connect();
  }

  function stop(): void {
    stopRequested = true;
    if (reconnectTimer != null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
      try {
        ws.close();
      } catch {
        /* noop */
      }
    }
    ws = null;
    connected.value = false;
  }

  onBeforeUnmount(stop);

  return { connected, leader, follower, start, stop };
}
