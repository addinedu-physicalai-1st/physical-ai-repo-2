/**
 * Doctor teleop WS hook — control-service `/ws/doctor/teleop` 구독.
 * Binary frame (ArrayBuffer) → StateFrame, text frame → DoctorEvent.
 *
 * Spec: docs/superpowers/specs/2026-05-26-doctor-ui-telemedicine-design.md §4
 * Plan: docs/superpowers/plans/2026-05-26-doctor-teleop-core.md Task 8.
 */
import { ref, type Ref } from 'vue';
import { decodeState, encodeTarget, type StateFrame, type TargetFrame } from './pose_codec';

export type DoctorTeleopStatus = 'connecting' | 'open' | 'closed';

export interface DoctorEvent {
  type: string;
  [k: string]: unknown;
}

/**
 * Pure message dispatcher — exported for unit testing.
 * - ArrayBuffer → decodeState → onState
 * - string     → JSON.parse  → onEvent
 * 다른 타입(Blob 등) 은 무시. 디코드 실패는 console.warn 후 swallow — 단일 메시지가
 * 전체 hook 을 죽이지 않게.
 */
export function handleIncomingMessage(
  ev: MessageEvent,
  onState: (s: StateFrame) => void,
  onEvent: (e: DoctorEvent) => void,
): void {
  if (ev.data instanceof ArrayBuffer) {
    try {
      onState(decodeState(ev.data));
    } catch (e) {
      console.warn('[doctor-teleop] state decode failed', e);
    }
  } else if (typeof ev.data === 'string') {
    try {
      const j = JSON.parse(ev.data);
      if (j && typeof j === 'object') onEvent(j as DoctorEvent);
    } catch {
      /* malformed JSON — ignore */
    }
  }
}

export interface UseDoctorTeleopWS {
  status: Ref<DoctorTeleopStatus>;
  sendTarget: (frame: TargetFrame) => void;
  sendEvent: (evt: DoctorEvent) => void;
  close: () => void;
}

export function useDoctorTeleopWS(opts: {
  edupingId: string;
  onState: (s: StateFrame) => void;
  onEvent?: (e: DoctorEvent) => void;
}): UseDoctorTeleopWS {
  const status = ref<DoctorTeleopStatus>('connecting');
  const url = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}` +
              `/ws/doctor/teleop?eduping_id=${encodeURIComponent(opts.edupingId)}`;
  const ws = new WebSocket(url);
  ws.binaryType = 'arraybuffer';

  ws.onopen = () => { status.value = 'open'; };
  ws.onclose = () => { status.value = 'closed'; };
  ws.onerror = () => { /* onclose follows */ };
  ws.onmessage = (ev) => handleIncomingMessage(ev, opts.onState, opts.onEvent ?? (() => {}));

  return {
    status,
    sendTarget(frame) {
      if (ws.readyState !== WebSocket.OPEN) return;
      ws.send(encodeTarget(frame));
    },
    sendEvent(evt) {
      if (ws.readyState !== WebSocket.OPEN) return;
      ws.send(JSON.stringify(evt));
    },
    close() {
      ws.close();
    },
  };
}
