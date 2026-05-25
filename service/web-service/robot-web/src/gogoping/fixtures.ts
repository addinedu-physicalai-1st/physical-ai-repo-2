/**
 * GogoPing 숨바꼭질 UI 상수 + fetch fallback.
 *
 * WAYPOINTS / PLAY_AREA_LABEL 은 control-service `state_to_goal.py` 의 "숨바꼭질"
 * 분기 search_waypoints/play_area_key 와 일치시킨다 (BT 가 실제 nav 하는 vertex
 * 와 UI 표시가 같은 위치를 가리키도록). 향후 `/api/nav/named_poses` 동적 조회로 교체.
 *
 * ROSTER_FALLBACK 은 `/api/children/roster` fetch 실패 시 fallback —
 * `db/control-db/control_db/seed.py` 의 CHILD_SAMPLES 와 동일한 6명. fetch 성공
 * 시 응답 (실제 child_id + 최신 명단) 으로 덮어쓴다.
 */

export interface Waypoint {
  /** nav_graph named pose key. 노드별 카메라 회전 시 라벨로 표시. */
  key: string;
  /** 사용자에게 보일 한국어 라벨. */
  label: string;
}

export const PLAY_AREA_LABEL = '운동장2';

// key 는 waypoints.yaml 에 실제 등록된 vertex 이름과 일치해야 한다 — UI 표시 라벨
// 과 BT NavigateToVertex 의 destination 이 같은 vertex 를 가리키도록.
// state_to_goal.py 의 "숨바꼭질" 분기 search_waypoints 와도 일치 유지.
export const WAYPOINTS: Waypoint[] = [
  { key: '운동장3', label: '운동장3' },
  { key: '운동장입구', label: '운동장 입구' },
  { key: '놀이방2', label: '놀이방2' },
];

export interface RosterEntry { id: number; name: string }

// seed.py (CHILD_SAMPLES) 와 동일 — 햇님반 6명. /api/children/roster fetch
// 성공 시 실제 응답으로 덮어쓰므로 child_id 가 DB SERIAL 와 정확히 일치 안 해도
// 데모 영향 없음 (그래도 INSERT 순서 기준 1~6 일 가능성이 높음).
export const ROSTER_FALLBACK: RosterEntry[] = [
  { id: 1, name: '박우림' },
  { id: 2, name: '최민성' },
  { id: 3, name: '이정우' },
  { id: 4, name: '이지수' },
  { id: 5, name: '이강택' },
  { id: 6, name: '노영주' },
];

/** 카운트다운 시간 (초). SR-PLAY-007 카운트다운 단계. */
export const COUNTDOWN_SEC = 30;

/** "꼭꼭 숨어라 머리카락 보일라" 챈트 1회 길이 (ms). 30초 동안 반복 재생. */
export const HIDE_CHANT_INTERVAL_MS = 5000;
