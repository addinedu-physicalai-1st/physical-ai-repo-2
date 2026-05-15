import type { EmotionId } from './emotions';
import robotsData from '../../../../shared/robots.json';

export type { EmotionId };
export type RobotId = 'eduping' | 'gogoping' | 'noriarm';

export interface ModeTreeGroup {
  id: string;
  children: ModeTreeNode[];
  selfSelectable?: boolean; // false 로 명시하면 드롭다운 안에 자기 자신 항목을 표시하지 않음
}

export type ModeTreeNode = string | ModeTreeGroup;

export interface RobotConfig {
  id: RobotId;
  displayName: string;
  wakeWord: string;
  wakeWordAliases: string[];
  modes: string[];
  modeTree: ModeTreeNode[];
  defaultEmotionByMode: Record<string, EmotionId>;
  restrictedVoiceMode: string | null;
}

interface RawRobot {
  id: string;
  displayName: string;
  wakeWord: string;
  wakeWordAliases?: string[];
  modes: string[];
  modeTree: ModeTreeNode[];
  defaultEmotionByMode: Record<string, string>;
  restrictedVoiceMode: string | null;
}

const RAW: RawRobot[] = robotsData.robots as unknown as RawRobot[];

export const ROBOT_CONFIGS: Record<RobotId, RobotConfig> = Object.fromEntries(
  RAW.map((r) => [
    r.id,
    {
      id: r.id as RobotId,
      displayName: r.displayName,
      wakeWord: r.wakeWord,
      wakeWordAliases: r.wakeWordAliases ?? [],
      modes: r.modes,
      modeTree: r.modeTree,
      defaultEmotionByMode: r.defaultEmotionByMode as Record<string, EmotionId>,
      restrictedVoiceMode: r.restrictedVoiceMode,
    },
  ])
) as Record<RobotId, RobotConfig>;

export const MODE_DESCRIPTIONS: Readonly<Record<string, string>> =
  robotsData.modeDescriptions;

/**
 * STT 가 호출어를 비슷한 음으로 잘못 인식하는 경우 (예: '에듀핑' → '에듀핀') 도
 * 호출 성공으로 처리하기 위한 (변형 → 정식 wakeWord) 매핑 테이블.
 */
export const WAKE_WORD_VARIANT_MAP: { variant: string; canonical: string }[] =
  Object.values(ROBOT_CONFIGS).flatMap((c) => [
    { variant: c.wakeWord, canonical: c.wakeWord },
    ...c.wakeWordAliases.map((a) => ({ variant: a, canonical: c.wakeWord })),
  ]);

/** URL `?robot=<id>` 우선, 없으면 `VITE_ROBOT`, 둘 다 없으면 'gogoping'. 휴대전화 진입 시 같은 빌드로 로봇 선택. */
export function getCurrentRobot(): RobotConfig {
  let id: string | null = null;
  if (typeof window !== 'undefined') {
    id = new URLSearchParams(window.location.search).get('robot');
  }
  id = id ?? (import.meta.env.VITE_ROBOT as string | undefined) ?? 'gogoping';
  const config = ROBOT_CONFIGS[id as RobotId];
  if (!config) {
    console.warn(`Unknown robot="${id}", falling back to gogoping. Use eduping | gogoping | noriarm.`);
    return ROBOT_CONFIGS.gogoping;
  }
  return config;
}

