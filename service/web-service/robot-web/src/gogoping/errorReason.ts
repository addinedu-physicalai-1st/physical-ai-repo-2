/**
 * GogoPing FSM ERROR(고장) 상태의 machine-readable error_reason → 교사용 한국어 안내.
 *
 * 백엔드(blackboard.error_reason)는 reason 코드만 보내고, 친근한 문구는 여기서 매핑한다
 * (admin-app 은 별도 매핑 가능). 알 수 없는/빈 reason 은 폴백.
 *
 * reason 코드 출처(controller/gogoping_modes):
 *   user_emergency_stop  command_listener (e-stop srv)
 *   out_of_map           map_boundary_monitor
 *   lidar_timeout / odom_timeout  hardware_health_monitor
 */
const TEACHER_TEXT: Record<string, string> = {
  user_emergency_stop: '비상 정지 버튼이 눌렸어요 · 전원 재시작이 필요해요',
  out_of_map: '로봇이 정해진 구역 밖으로 나갔어요 · 제자리로 옮긴 뒤 재시작해 주세요',
  lidar_timeout: '거리 센서(라이다) 응답이 없어요 · 전원 재시작이 필요해요',
  odom_timeout: '주행 센서 응답이 없어요 · 전원 재시작이 필요해요',
};

const FALLBACK = '점검이 필요해요 · 전원 재시작이 필요해요';

/** error_reason 코드 → 교사용 안내 문구. 미매핑/빈 값은 폴백. */
export function errorReasonToTeacherText(reason: string): string {
  return TEACHER_TEXT[reason] ?? FALLBACK;
}

/** 아이용 기본 메시지 — 사유와 무관하게 항상 동일(안심). */
export const ERROR_CHILD_MESSAGE = '앗, 잠깐 쉬고 있어요. 선생님을 불러주세요!';
