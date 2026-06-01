/**
 * /api/eduping/state WS 구독.
 *
 * service/control-service/control_service/eduping/router.py 의 `/api/eduping/state` 가 100ms 주기로 broadcast 하는
 * snapshot { ts, leader: {joint_names, positions, age_s} | null, follower: ... | null } 을
 * 그대로 reactive 로 노출. 자동 재연결 (1.5s).
 */
import { computed, onBeforeUnmount, ref, type ComputedRef, type Ref } from 'vue';

export interface JointSnapshot {
  joint_names: string[];
  positions: number[];
  age_s: number;
}

export interface HighfiveStatusPayload {
  ts?: number;
  level?: 'ok' | 'warn' | 'danger';
  static_obstacle?: boolean;
  static_px?: number;
  dyn_closest_m?: number;
  dyn_x_norm?: number;
  active_arms?: string[];
  aborted_arms?: string[];
}

export interface StateSnapshot {
  ts: number;
  leader: JointSnapshot | null;
  follower: JointSnapshot | null;
  real_active?: boolean;
  highfive_real_active?: boolean;
  highfive_status?: HighfiveStatusPayload | null;
}

export interface UseEdupingStateWs {
  connected: Ref<boolean>;
  leader: Ref<JointSnapshot | null>;
  follower: Ref<JointSnapshot | null>;
  realActive: Ref<boolean>;
  /** highfive → 실물 forward 활성 — DepthViewer 토글 + bridge 상태. */
  highfiveRealActive: Ref<boolean>;
  /** DCP-RMP obstacle overlay 상태 — bridge 가 /eduping/highfive/status (5Hz) 를 그대로
   *  WS snapshot 에 끼워서 전달. 기존 5Hz HTTP 폴링 대체 (control 서버 로그 spam 제거). */
  highfiveStatus: Ref<HighfiveStatusPayload | null>;
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
  const highfiveRealActive = ref(false);
  const highfiveStatus = ref<HighfiveStatusPayload | null>(null);

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
        highfiveRealActive.value = !!snap.highfive_real_active;
        highfiveStatus.value = snap.highfive_status ?? null;
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

  return {
    connected, leader, follower, realActive, highfiveRealActive,
    highfiveStatus, leaderActive, start, stop,
  };
}
