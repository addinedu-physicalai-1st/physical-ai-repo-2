/**
 * /api/eduping/recording WS 구독.
 *
 * snapshot 형태:
 *   { ts, active: false }
 *   { ts, active: true, kind, name, frame_count, elapsed_s, joint_names }
 */
import { onBeforeUnmount, ref, type Ref } from 'vue';

export interface RecordingSnapshot {
  ts: number;
  active: boolean;
  kind?: string;       // 'dance' | 'greeting'
  name?: string;
  frame_count?: number;
  elapsed_s?: number;
  joint_names?: string[];
}

export interface UseEdupingRecordingWs {
  connected: Ref<boolean>;
  recording: Ref<RecordingSnapshot | null>;
  start: () => void;
  stop: () => void;
}

const RECONNECT_DELAY_MS = 1500;

export function useEdupingRecordingWs(): UseEdupingRecordingWs {
  const connected = ref(false);
  const recording = ref<RecordingSnapshot | null>(null);

  let ws: WebSocket | null = null;
  let stopRequested = false;
  let reconnectTimer: number | null = null;

  function url(): string {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${proto}//${location.host}/api/eduping/recording`;
  }

  function connect(): void {
    if (stopRequested) return;
    try {
      ws = new WebSocket(url());
    } catch (err) {
      console.warn('[edupingRecording] WS construct 실패', err);
      scheduleReconnect();
      return;
    }
    ws.onopen = () => {
      connected.value = true;
    };
    ws.onmessage = (ev) => {
      try {
        recording.value = JSON.parse(ev.data) as RecordingSnapshot;
      } catch (err) {
        console.warn('[edupingRecording] parse 실패', err);
      }
    };
    ws.onerror = () => {
      /* close 가 뒤따라 옴 */
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

  return { connected, recording, start, stop };
}
