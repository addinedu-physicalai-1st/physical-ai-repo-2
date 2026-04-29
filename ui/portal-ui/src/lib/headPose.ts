export interface Landmark {
  x: number
  y: number
  z: number
}

export interface HeadPose {
  yaw: number    // 음수=왼쪽, 양수=오른쪽
  pitch: number  // 음수=위, 양수=아래
}

export enum AngleTarget {
  FRONT = 'front',
  LEFT  = 'left',
  RIGHT = 'right',
  UP    = 'up',
  DOWN  = 'down',
}

export const TARGET_HINTS: Record<AngleTarget, string> = {
  [AngleTarget.FRONT]: '카메라를 정면으로 봐주세요',
  [AngleTarget.LEFT]:  '천천히 왼쪽을 봐주세요',
  [AngleTarget.RIGHT]: '천천히 오른쪽을 봐주세요',
  [AngleTarget.UP]:    '살짝 위를 봐주세요',
  [AngleTarget.DOWN]:  '살짝 아래를 봐주세요',
}

export const TARGET_ORDER: AngleTarget[] = [
  AngleTarget.FRONT,
  AngleTarget.LEFT,
  AngleTarget.RIGHT,
  AngleTarget.UP,
  AngleTarget.DOWN,
]

export function estimateHeadPose(landmarks: Landmark[]): HeadPose {
  const noseTip     = landmarks[1]
  const leftTemple  = landmarks[234]
  const rightTemple = landmarks[454]
  const forehead    = landmarks[10]
  const chin        = landmarks[152]

  const faceWidth = Math.max(rightTemple.x - leftTemple.x, 1e-6)
  const faceCenterX = (leftTemple.x + rightTemple.x) / 2

  // 코의 좌우 편차 비율 → yaw
  // 카메라 raw 이미지는 좌우 반전이지만 UI(scaleX(-1))는 거울처럼 보여주므로
  // 사용자(거울) 관점에 맞추기 위해 부호를 뒤집어 음수=사용자 왼쪽, 양수=사용자 오른쪽으로 정규화한다.
  const yawNorm = (noseTip.x - faceCenterX) / (faceWidth / 2)
  const yaw = -yawNorm * 90

  const faceHeight = Math.max(chin.y - forehead.y, 1e-6)
  const noseRel = (noseTip.y - forehead.y) / faceHeight
  // 정면 코 위치 ≈ 0.5; 위 보면 < 0.5, 아래 보면 > 0.5
  const pitch = (noseRel - 0.5) * 180

  return { yaw, pitch }
}

const YAW_FRONT = 15
const YAW_SIDE  = 30
const PITCH_VERT = 15
const PITCH_FRONT = 25

export function matchesTarget(pose: HeadPose, target: AngleTarget): boolean {
  switch (target) {
    case AngleTarget.FRONT:
      return Math.abs(pose.yaw) < YAW_FRONT && Math.abs(pose.pitch) < PITCH_FRONT
    case AngleTarget.LEFT:
      return pose.yaw < -YAW_SIDE && Math.abs(pose.pitch) < PITCH_FRONT
    case AngleTarget.RIGHT:
      return pose.yaw > YAW_SIDE && Math.abs(pose.pitch) < PITCH_FRONT
    case AngleTarget.UP:
      return Math.abs(pose.yaw) < 25 && pose.pitch < -PITCH_VERT
    case AngleTarget.DOWN:
      return Math.abs(pose.yaw) < 25 && pose.pitch > PITCH_VERT
  }
}
