/**
 * URDF loader wrapper — single bimanual URDF 로부터 좌/우 팔의 joint·ee 핸들을 추출.
 *
 * `package://openarm_description/...` URI 는 브라우저가 풀 수 없으므로 urdf-loader 의
 * `packages` 맵을 사용해 path prefix 로 치환한다 (Step 6 option b).
 *
 * 한 URDF 를 두 번 로드해 좌/우 각각의 EE link 를 잡아내는 식이 아니라, 한 번 로드 후
 * 두 prefix (`openarm_left_`, `openarm_right_`) 로 joint·link 를 나눠 잡는다 — robot
 * 트리는 공유.
 */
import * as THREE from 'three';
// urdf-loader 의 d.ts 는 default export 이지만 일부 환경에서 namespace 로 해석된다.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
import URDFLoader from 'urdf-loader';
import type { URDFRobot } from 'urdf-loader';

export interface LoadedArm {
  /** 양팔이 한 트리 안에 있을 때는 좌/우 모두 같은 robot 인스턴스를 공유한다. */
  robot: URDFRobot;
  /** 이 팔의 movable joint 이름들 (fixed/floating 제외). 길이 7 기대 (openarm v10). */
  jointNames: string[];
  /** End-effector link (handle 부착 대상, TCP 또는 tool0). */
  endEffectorLink: THREE.Object3D;
}

export type PackagesMap = Record<string, string>;

/** 로드된 URDF 에서 prefix 로 시작하는 movable joint 이름 (선언 순서 유지). */
function filterArmJoints(robot: URDFRobot, prefix: string): string[] {
  return Object.keys(robot.joints).filter((n) => {
    if (!n.startsWith(prefix)) return false;
    const jt = robot.joints[n].jointType;
    return jt !== 'fixed' && jt !== 'floating';
  });
}

/**
 * URDF 를 1회 로드. urdf-loader 는 동기 콜백 스타일이지만 비동기 mesh 다운로드 (collada
 * 등) 를 내부에서 일으키므로 robot 객체는 즉시 반환되어도 mesh 가 비어 있을 수 있다.
 * 사용처에서는 매 프레임 render 가 도는 한 mesh 가 나중에 채워져도 문제 없다.
 */
export async function loadRobot(urdfUrl: string, packages: PackagesMap): Promise<URDFRobot> {
  const loader = new URDFLoader();
  // collision geometry 는 안 쓰니까 파싱 비활성 — 대역폭/메모리 절감.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (loader as any).parseCollision = false;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (loader as any).packages = packages;

  return new Promise<URDFRobot>((resolve, reject) => {
    loader.load(
      urdfUrl,
      (robot: URDFRobot) => resolve(robot),
      undefined,
      // urdf-loader 의 onError 는 표준 ErrorEvent — Error 로 감싸 reject.
      (err: unknown) => reject(err instanceof Error ? err : new Error(String(err))),
    );
  });
}

/**
 * 한 robot 인스턴스에서 좌/우 팔을 prefix 로 분리. EE 링크 이름은 보통
 * `openarm_left_hand_tcp` / `openarm_right_hand_tcp` (또는 `..._tool0`).
 * 두 후보 모두 시도하고 못 찾으면 에러.
 */
export function splitBimanual(
  robot: URDFRobot,
  opts?: {
    leftPrefix?: string;
    rightPrefix?: string;
    leftEeCandidates?: string[];
    rightEeCandidates?: string[];
  },
): { left: LoadedArm; right: LoadedArm } {
  const leftPrefix = opts?.leftPrefix ?? 'openarm_left_';
  const rightPrefix = opts?.rightPrefix ?? 'openarm_right_';
  const leftCandidates = opts?.leftEeCandidates ?? [
    'openarm_left_hand_tcp', 'openarm_left_tool0', 'openarm_left_link7',
  ];
  const rightCandidates = opts?.rightEeCandidates ?? [
    'openarm_right_hand_tcp', 'openarm_right_tool0', 'openarm_right_link7',
  ];

  const findEe = (candidates: string[]): THREE.Object3D => {
    for (const name of candidates) {
      const link = robot.links[name];
      if (link) return link;
    }
    throw new Error(`URDF missing ee link — tried: ${candidates.join(', ')}`);
  };

  return {
    left: {
      robot,
      jointNames: filterArmJoints(robot, leftPrefix),
      endEffectorLink: findEe(leftCandidates),
    },
    right: {
      robot,
      jointNames: filterArmJoints(robot, rightPrefix),
      endEffectorLink: findEe(rightCandidates),
    },
  };
}

/** state frame 의 7-DOF joint 배열을 URDF joint 에 적용. 길이 불일치는 잘라낸다.
 *  gripper 가 주어지면 prismatic finger_joint1 (양팔 동일 이름 패턴) 에 추가 적용. */
export function applyJoints(arm: LoadedArm, jointAngles: number[], gripper?: number): void {
  const n = Math.min(arm.jointNames.length, jointAngles.length);
  for (let i = 0; i < n; i++) {
    arm.robot.setJointValue(arm.jointNames[i], jointAngles[i]);
  }
  if (gripper !== undefined) {
    const fingerName = arm.jointNames.find((nm) => nm.endsWith('finger_joint1'));
    if (fingerName) arm.robot.setJointValue(fingerName, gripper);
  }
}
