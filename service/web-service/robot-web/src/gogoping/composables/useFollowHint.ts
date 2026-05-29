/**
 * Lost-recovery hint composable — POST /api/gogoping/follow/hint.
 *
 * 디버그 패널의 left/right/front/back 버튼이 호출. control-service 가
 * /gogoping/follow_hint (std_msgs/String) publish → follow_node WAITING_HINT mode 처리.
 */
export type HintDirection = 'left' | 'right' | 'front' | 'back' | 'search' | 'resume';

export interface HintResponse {
  ok: boolean;
  published: HintDirection;
}

export interface FollowHintDeps {
  fetch?: typeof fetch;
}

export interface UseFollowHint {
  sendHint(direction: HintDirection): Promise<HintResponse>;
}

const HINT_URL = '/api/gogoping/follow/hint';

export function useFollowHint(deps: FollowHintDeps = {}): UseFollowHint {
  const fetchFn = deps.fetch ?? globalThis.fetch.bind(globalThis);

  async function sendHint(direction: HintDirection): Promise<HintResponse> {
    const res = await fetchFn(HINT_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ direction }),
    });
    if (!res.ok) {
      throw new Error(`hint POST failed: ${res.status}`);
    }
    return (await res.json()) as HintResponse;
  }

  return { sendHint };
}
