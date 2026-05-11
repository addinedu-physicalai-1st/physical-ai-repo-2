import type { RobotId } from './robots';

/**
 * 로봇별 색 토큰.
 * - face: ShaderFace 의 accent (배경/얼굴 발광색).
 * - chrome: 위 색 배경 위에 얹히는 UI chrome (FAB 아이콘, 오버레이 텍스트 등).
 *           gogoping 처럼 face 가 밝은 라임일 때 chrome 은 검정이어야 가독성이 확보된다.
 */
export interface RobotColorTokens {
  face: string;
  chrome: string;
}

export const ROBOT_COLORS: Record<RobotId, RobotColorTokens> = {
  eduping: { face: '#db2777', chrome: '#db2777' },
  gogoping: { face: '#bef32c', chrome: '#000000' },
  noriarm: { face: '#3a8fc2', chrome: '#3a8fc2' },
};

export function faceAccent(id: RobotId): string {
  return ROBOT_COLORS[id].face;
}

export function chromeAccent(id: RobotId): string {
  return ROBOT_COLORS[id].chrome;
}
