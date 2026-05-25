/**
 * 술래잡기 control-service API helper.
 *
 * - `postRecruitComplete`: 모집 종료 → BT 의 AwaitRecruitComplete 게이트 SUCCESS
 *   (HideAndSeekGame "출발" 버튼 → Task 12).
 * - `postCaught`: 발견 → BT 의 HideSeekCaughtMonitor blackboard append
 *   (PatrolPhase / ReturnPhase 의 얼굴 매칭 → Task 13~14).
 *
 * 응답 본문은 사용하지 않고 ok 여부만 boolean 으로 반환 — UI 는 fail 시 console.warn
 * 정도만 하고 phase 전환은 BT snapshot 이 트리거.
 */
const DEVICE_TOKEN = import.meta.env.VITE_ROBOT_TOKEN ?? 'dev-robot-token-change-me';

export async function postRecruitComplete(childIds: number[]): Promise<boolean> {
  try {
    const res = await fetch('/api/gogoping/play/hideseek/recruit-complete', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Device-Token': DEVICE_TOKEN,
      },
      body: JSON.stringify({ child_ids: childIds }),
    });
    return res.ok;
  } catch {
    return false;
  }
}

export async function postCaught(
  childId: number,
  caughtAtWaypoint?: string,
): Promise<boolean> {
  try {
    const res = await fetch('/api/gogoping/play/hideseek/caught', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Device-Token': DEVICE_TOKEN,
      },
      body: JSON.stringify({
        child_id: childId,
        ...(caughtAtWaypoint ? { caught_at_waypoint: caughtAtWaypoint } : {}),
      }),
    });
    return res.ok;
  } catch {
    return false;
  }
}

/**
 * Debug: 현재 phase 를 즉시 SUCCESS 시켜 다음 phase 로 advance.
 * 지원: recruit / countdown / patrol / return. 그 외 phase 는 reject.
 */
export async function postSkipPhase(currentPhase: string): Promise<boolean> {
  try {
    const res = await fetch('/api/gogoping/play/hideseek/debug/skip-phase', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Device-Token': DEVICE_TOKEN,
      },
      body: JSON.stringify({ current_phase: currentPhase }),
    });
    return res.ok;
  } catch {
    return false;
  }
}
