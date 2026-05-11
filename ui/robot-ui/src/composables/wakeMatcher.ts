/**
 * Wake-word / echo 매칭 로직.
 *
 * useVoiceController 내부 closure 에 묶여있던 순수 함수를 추출해 단위 테스트 가능하게
 * 분리한 모듈. Pinia / Vue / DOM 의존이 없도록 유지한다.
 */

export interface WakeMatch {
  wakeWord: string;
  remainder: string;
}

export interface WakeWordVariant {
  variant: string;
  canonical: string;
}

const STOP_TOKENS = ['정지', '멈춰', '그만', '스톱'];
// 짧은 ack 만 final 로 떨어진 경우는 사용자가 아닌 로봇 echo 로 본다.
const ECHO_ACK_TOKENS = ['네', '네요'];

export function normalizeWakeText(text: string): string {
  return text
    .replace(/\s+/g, '')
    .replace(/[^\p{Script=Hangul}a-zA-Z0-9]/gu, '')
    .toLowerCase();
}

/** wake word 의 alias 가 없을 때, STT 가 비슷한 음으로 잘못 옮긴 케이스를 휴리스틱으로 잡는다. */
export function wakeHeuristicMatch(compact: string, wakeWord: string): boolean {
  if (!compact) return false;
  if (wakeWord === '고고핑') return /(고고|꼬꼬)(핑|핀|팽|빙)/.test(compact);
  if (wakeWord === '에듀핑') return /(에듀|애듀)(핑|핀|팽|빙)/.test(compact);
  if (wakeWord === '노리암') return /(노리|놀이|노라)(암|아)/.test(compact);
  return false;
}

export function buildWakeRegex(variants: WakeWordVariant[]): RegExp {
  const patterns = variants.map(({ variant }) => variant.split('').join('\\s*'));
  return new RegExp(`(${patterns.join('|')})[\\s,.!?]*(.*)$`);
}

export function canonicalizeWakeWord(
  matched: string,
  variants: WakeWordVariant[],
): string | null {
  const compact = normalizeWakeText(matched);
  const hit = variants.find((v) => v.variant === compact);
  return hit?.canonical ?? null;
}

export function tryWakeFromText(
  text: string,
  wakeWord: string,
  variants: WakeWordVariant[],
  regex: RegExp,
): WakeMatch | null {
  const match = text.match(regex);
  if (match) {
    const canonical = canonicalizeWakeWord(match[1] ?? '', variants);
    if (canonical === wakeWord) {
      return { wakeWord: canonical, remainder: (match[2] ?? '').trim() };
    }
  }

  // 공백/기호가 섞인 STT 결과에서도 호출어를 안정적으로 탐지
  const compact = normalizeWakeText(text);
  if (!compact) return null;
  for (const v of variants) {
    if (v.canonical !== wakeWord) continue;
    const vv = normalizeWakeText(v.variant);
    if (vv && compact.includes(vv)) {
      return { wakeWord, remainder: '' };
    }
  }
  if (wakeHeuristicMatch(compact, wakeWord)) {
    return { wakeWord, remainder: '' };
  }
  return null;
}

export function isWakeOnlyUtterance(
  text: string,
  wakeWord: string,
  variants: WakeWordVariant[],
  regex: RegExp,
): boolean {
  const wake = tryWakeFromText(text, wakeWord, variants, regex);
  return !!wake && wake.remainder.trim().length === 0;
}

export function isStopIntent(text: string): boolean {
  return STOP_TOKENS.some((token) => text.includes(token));
}

/**
 * 로봇이 방금 말한 문장이 마이크로 다시 잡혀 STT final 로 떨어진 케이스 판정.
 * - 사용자 침묵 / 빈 입력
 * - 로봇 발화와 완전 일치
 * - 로봇 발화의 부분 문자열 (2자 이상)
 * - 짧은 ack ("네", "네요")
 */
export function isLikelyEchoOfRobotReply(heard: string, spoken: string): boolean {
  if (!heard) return true;
  if (heard === spoken) return true;
  if (heard.length >= 2 && spoken.includes(heard)) return true;
  return ECHO_ACK_TOKENS.includes(heard);
}
