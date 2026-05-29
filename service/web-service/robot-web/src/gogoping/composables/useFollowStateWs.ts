/**
 * GogoPing follow_node mode WS 구독 — /ws/follow-state 가 follow_node 의 mode 전이를 fan-out.
 *
 * 사용: App.vue 의 voice-guided search TTS watcher (VOICE_SEARCH→VOICE_FOUND 전이
 * 시 "선생님 찾았습니다" 발화 등).
 */
import { onBeforeUnmount, ref, type Ref } from 'vue';

export type FollowMode =
  | 'idle'
  | 'stop'
  | 'reactive'
  | 'nav2'
  | 'recovery'
  | 'waiting_hint'
  | 'voice_search'
  | 'voice_found'
  | 'voice_resume';

export interface FollowStateRef {
  mode: FollowMode | null;
}

export interface UseFollowStateWs {
  state: Ref<FollowStateRef>;
  connected: Ref<boolean>;
  stop: () => void;
}

const RECONNECT_DELAY_MS = 5000;

export function useFollowStateWs(): UseFollowStateWs {
  const state = ref<FollowStateRef>({ mode: null });
  const connected = ref<boolean>(false);

  const protocol =
    typeof window !== 'undefined' && window.location.protocol === 'https:' ? 'wss' : 'ws';
  const host = typeof window !== 'undefined' ? window.location.host : 'localhost';
  const url = `${protocol}://${host}/ws/follow-state`;

  let ws: WebSocket | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let stopped = false;

  function connect(): void {
    if (stopped) return;
    ws = new WebSocket(url);

    ws.onopen = () => {
      connected.value = true;
    };

    ws.onmessage = (ev: MessageEvent<string>) => {
      try {
        const payload = JSON.parse(ev.data) as { mode: FollowMode };
        state.value = { mode: payload.mode };
      } catch {
        // 다음 메시지에서 회복
      }
    };

    ws.onclose = () => {
      ws = null;
      connected.value = false;
      if (stopped) return;
      reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS);
    };

    ws.onerror = () => {
      ws?.close();
    };
  }

  function stop(): void {
    stopped = true;
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (ws) {
      ws.close();
    }
    ws = null;
  }

  connect();
  onBeforeUnmount(stop);

  return { state, connected, stop };
}
