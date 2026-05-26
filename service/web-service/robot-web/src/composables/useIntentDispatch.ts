import type { EmotionId, RobotId } from '@/config/robots';

/**
 * 의도 분류 응답 타입 — `useVoiceController` 가 WebRTC DataChannel `intent` 메시지
 * payload 의 type guard 로 사용. 서버 (`ai-service /voice/intent`) 가 동일 shape.
 */
export type IntentResponse =
  | { kind: 'mode_change'; mode: string }
  | { kind: 'sub_command'; action: 'stop' | 'return' | 'start' }
  | { kind: 'goto_vertex'; name: string }
  | { kind: 'store_item'; item: string }
  | { kind: 'chat'; reply: string; emotion: EmotionId }
  | { kind: 'rhythm_play'; song: string; display_name: string }
  | { kind: 'rhythm_stop' }
  | { kind: 'confirm_yes' }
  | { kind: 'confirm_no' }
  | { kind: 'ignored' };

/**
 * 모드 셀렉터 UI 클릭 → 서버 알림 — ROS bridge / 로깅 등이 후속 처리.
 * 음성 intent 와는 별개 경로 (UI 클릭만).
 */
export async function postModeClick(mode: string, robot: RobotId): Promise<void> {
  const response = await fetch('/api/mode', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ robot, mode }),
  });
  if (!response.ok) {
    throw new Error(`/api/mode ${response.status}`);
  }
}
