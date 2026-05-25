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

// 빈 fixture — backend 가 BT snapshot 의 patrol.vertices 로 동적 채움.
// PatrolPhase mount 직후 useGogopingStateWs → hideseekPhaseStore.setPatrol →
// HideAndSeekGame watch → actions.setPatrolVertices → state.waypoints 갱신.
// hardcoded fallback 없음 — BT 데이터 받기 전 잠깐 빈 list 가 UI 자연스러움.
export const WAYPOINTS: Waypoint[] = [];

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
