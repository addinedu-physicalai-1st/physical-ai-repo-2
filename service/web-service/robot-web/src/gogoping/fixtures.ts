/**
 * GogoPing 숨바꼭질 UI mock 데이터.
 *
 * 실제 도입 시 교체:
 *   - WAYPOINTS → nav_graph 의 patrol_* named pose (control-service /api/nav/named_poses)
 *   - PLAY_AREA → nav_graph 의 `운동장2` (SR-PLAY-007 §2.7)
 *   - ROSTER_FALLBACK → /api/children/roster (control-service)
 */

export interface Waypoint {
  /** nav_graph named pose key. 노드별 카메라 회전 시 라벨로 표시. */
  key: string;
  /** 사용자에게 보일 한국어 라벨. */
  label: string;
}

export const PLAY_AREA_LABEL = '운동장2';

export const WAYPOINTS: Waypoint[] = [
  { key: 'patrol_slide', label: '미끄럼틀 옆' },
  { key: 'patrol_sandbox', label: '모래놀이터' },
  { key: 'patrol_tree', label: '큰 나무 뒤' },
  { key: 'patrol_bench', label: '벤치 옆' },
  { key: 'patrol_storage', label: '창고 뒤' },
];

export interface RosterEntry { id: number; name: string }

export const ROSTER_FALLBACK: RosterEntry[] = [
  { id: 1, name: '윤서' },
  { id: 2, name: '도윤' },
  { id: 3, name: '하은' },
  { id: 4, name: '시우' },
  { id: 5, name: '지아' },
];

/** 카운트다운 시간 (초). SR-PLAY-007 카운트다운 단계. */
export const COUNTDOWN_SEC = 30;

/** "꼭꼭 숨어라 머리카락 보일라" 챈트 1회 길이 (ms). 30초 동안 반복 재생. */
export const HIDE_CHANT_INTERVAL_MS = 5000;

/** 모집 단계에서 자동 등록 간격 (mock 용). 실제는 얼굴 인식 매칭. */
export const RECRUIT_AUTO_REGISTER_INTERVAL_MS = 1200;

/** 모집 종료까지 대기 시간 (mock). 사용자가 직접 "시작" 눌러 진행도 가능. */
export const RECRUIT_AUTO_FINISH_MS = 8000;

/** 운동장2 로 이동 mock 지속 시간 (ms). */
export const MOVE_DURATION_MS = 4000;

/** 각 웨이포인트 통과 mock 지속 시간 (ms): 이동(이동시간) + 카메라 회전. */
export const PATROL_TRAVEL_MS = 2500;
export const PATROL_CAMERA_ROTATE_MS = 3500;

/** 한 웨이포인트 도착 시 사람을 찾을 mock 확률. */
export const PATROL_FIND_PROBABILITY = 0.35;

/** 복귀 mock 지속 시간 (ms). */
export const RETURN_DURATION_MS = 4000;
