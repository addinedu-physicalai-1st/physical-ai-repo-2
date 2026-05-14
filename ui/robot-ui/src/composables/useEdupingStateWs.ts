/**
 * /api/eduping/state WS 구독.
 *
 * server/control/eduping/router.py 의 `/api/eduping/state` 가 100ms 주기로 broadcast 하는
 * snapshot { ts, leader: {joint_names, positions, age_s} | null, follower: ... | null } 을
 * 그대로 reactive 로 노출. 자동 재연결 (1.5s).
 */
import { computed, onBeforeUnmount, ref, type ComputedRef, type Ref } from 'vue';

export interface JointSnapshot {
  joint_names: string[];
  positions: number[];
  age_s: number;
}

export interface StateSnapshot {
  ts: number;
  leader: JointSnapshot | null;
  follower: JointSnapshot | null;
  real_active?: boolean;
}

export interface UseEdupingStateWs {
  connected: Ref<boolean>;
  leader: Ref<JointSnapshot | null>;
  follower: Ref<JointSnapshot | null>;
  realActive: Ref<boolean>;
  /** leader 토픽이 최근 2초 내에 들어왔는지 — leader bringup 가동 여부. */
  leaderActive: ComputedRef<boolean>;
  start: () => void;
  stop: () => void;
}

// 첫 재연결은 빠르게, 실패가 반복되면 (서버에 ROS hub 가 안 떠있는 등) 지수 백오프로 늘려서
// vite proxy 로그가 ECONNRESET 으로 도배되는 것을 막는다. open() 성공 시 리셋.
const RECONNECT_INITIAL_MS = 1500;
const RECONNECT_MAX_MS = 30_000;

export function useEdupingStateWs(): UseEdupingStateWs {
  const connected = ref(false);
  const leader = ref<JointSnapshot | null>(null);
  const follower = ref<JointSnapshot | null>(null);
  const realActive = ref(false);

  const leaderActive = computed(() => {
    const l = leader.value;
    if (!l) return false;
    const age = l.age_s ?? Infinity;
    return age < 2.0;
  });

  let ws: WebSocket | null = null;
  let stopRequested = false;
  let reconnectTimer: number | null = null;
  let reconnectDelayMs = RECONNECT_INITIAL_MS;

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
      reconnectDelayMs = RECONNECT_INITIAL_MS;
    };
    ws.onmessage = (ev) => {
      try {
        const snap = JSON.parse(ev.data) as StateSnapshot;
        leader.value = snap.leader;
        follower.value = snap.follower;
        realActive.value = !!snap.real_active;
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
    const delay = reconnectDelayMs;
    reconnectDelayMs = Math.min(reconnectDelayMs * 2, RECONNECT_MAX_MS);
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, delay);
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

  return { connected, leader, follower, realActive, leaderActive, start, stop };
}
