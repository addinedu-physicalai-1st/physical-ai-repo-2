import type { EmotionId, RobotId } from '@/config/robots';

export type IntentResponse =
  | { kind: 'mode_change'; mode: string }
  | { kind: 'sub_command'; action: string }
  | { kind: 'chat'; reply: string; emotion: EmotionId }
  | { kind: 'ignored' };

export async function dispatchIntent(
  text: string,
  robot: RobotId,
  signal?: AbortSignal
): Promise<IntentResponse> {
  const response = await fetch('/api/voice/intent', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, robot }),
    signal,
  });
  if (!response.ok) {
    throw new Error(`/api/voice/intent ${response.status}`);
  }
  return (await response.json()) as IntentResponse;
}

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
