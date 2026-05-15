// shared/emotions.json 의 id 목록과 1:1 매칭. JSON 추가 시 이 union 도 같이 업데이트할 것.
import emotionsData from '../../../../../shared/emotions.json';

export type EmotionId =
  | 'basic'
  | 'hello'
  | 'happy'
  | 'fun'
  | 'interest'
  | 'bored'
  | 'sad'
  | 'angry'
  | 'sleep';

export interface EmotionDef {
  id: EmotionId;
  label: string;
  description: string;
  chat_eligible: boolean;
}

export const EMOTIONS: readonly EmotionDef[] = emotionsData.emotions as EmotionDef[];

export const ALL_EMOTION_IDS: readonly EmotionId[] = EMOTIONS.map((e) => e.id);

export const CHAT_EMOTION_IDS: readonly EmotionId[] = EMOTIONS.filter(
  (e) => e.chat_eligible
).map((e) => e.id);

const ID_SET: ReadonlySet<EmotionId> = new Set(ALL_EMOTION_IDS);

export function isEmotionId(value: unknown): value is EmotionId {
  return typeof value === 'string' && ID_SET.has(value as EmotionId);
}
