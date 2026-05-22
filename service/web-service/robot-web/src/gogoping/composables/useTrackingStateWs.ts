/**
 * GogoPing tracking state WS 구독 — perception 의 /gogoping/tracking_state 를
 * control-service /ws/tracking-state 로 fan-out 받는다. 5 Hz.
 *
 * 사용: FollowMode.vue 에서 추종 진행 중 bbox + 텔레메트리 표시.
 */
import { onBeforeUnmount, ref, type Ref } from 'vue';

export interface TrackingState {
  active: boolean;
  matched: boolean;
  distance_m: number | null;
  angle_deg: number | null;
  bbox_size_px: number | null;
  bbox_x1: number | null;
  bbox_y1: number | null;
  bbox_x2: number | null;
  bbox_y2: number | null;
  track_id: number | null;
  reid_sim: number | null;
  teacher_id: string | null;
  updated_at_ms: number | null;
}

const DEFAULT_STATE: TrackingState = {
  active: false,
  matched: false,
  distance_m: null,
  angle_deg: null,
  bbox_size_px: null,
  bbox_x1: null,
  bbox_y1: null,
  bbox_x2: null,
  bbox_y2: null,
  track_id: null,
  reid_sim: null,
  teacher_id: null,
  updated_at_ms: null,
};

export interface UseTrackingStateWs {
  state: Ref<TrackingState>;
  connected: Ref<boolean>;
  stop: () => void;
}

export function useTrackingStateWs(): UseTrackingStateWs {
  const state = ref<TrackingState>({ ...DEFAULT_STATE });
  const connected = ref<boolean>(false);

  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const url = `${protocol}://${window.location.host}/ws/tracking-state`;

  let ws: WebSocket | null = null;
  let reconnectTimer: number | null = null;
  let stopped = false;

  function connect(): void {
    if (stopped) return;
    ws = new WebSocket(url);

    ws.onopen = () => {
      connected.value = true;
    };

    ws.onmessage = (ev) => {
      try {
        const payload = JSON.parse(ev.data) as Partial<TrackingState>;
        state.value = { ...DEFAULT_STATE, ...payload };
      } catch {
        // 다음 메시지에서 회복
      }
    };

    ws.onclose = () => {
      ws = null;
      connected.value = false;
      if (stopped) return;
      reconnectTimer = window.setTimeout(connect, 1000);
    };

    ws.onerror = () => {
      // close 가 이어서 호출됨 — 별도 처리 X
    };
  }

  connect();

  function stop(): void {
    stopped = true;
    if (reconnectTimer !== null) {
      window.clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
      ws.close();
    }
    ws = null;
  }

  onBeforeUnmount(stop);

  return { state, connected, stop };
}
