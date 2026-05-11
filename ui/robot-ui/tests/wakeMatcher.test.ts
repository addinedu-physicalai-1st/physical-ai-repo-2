import { describe, expect, it } from 'vitest';
import {
  buildWakeRegex,
  canonicalizeWakeWord,
  isLikelyEchoOfRobotReply,
  isStopIntent,
  isWakeOnlyUtterance,
  normalizeWakeText,
  tryWakeFromText,
  wakeHeuristicMatch,
  type WakeWordVariant,
} from '../src/composables/wakeMatcher';

// 실제 robots.json 에서 파생되는 alias 표를 줄여서 재현
const VARIANTS: WakeWordVariant[] = [
  { variant: '고고핑', canonical: '고고핑' },
  { variant: '꼬꼬핑', canonical: '고고핑' },
  { variant: '에듀핑', canonical: '에듀핑' },
  { variant: '에듀핀', canonical: '에듀핑' },
  { variant: '노리암', canonical: '노리암' },
];
const REGEX = buildWakeRegex(VARIANTS);

describe('normalizeWakeText', () => {
  it('strips whitespace and punctuation', () => {
    expect(normalizeWakeText('  고고핑, 안녕!')).toBe('고고핑안녕');
  });
  it('lowercases ascii', () => {
    expect(normalizeWakeText('Hello WORLD')).toBe('helloworld');
  });
});

describe('wakeHeuristicMatch', () => {
  it('matches gogoping near-miss STT shapes', () => {
    expect(wakeHeuristicMatch('꼬꼬빙', '고고핑')).toBe(true);
    expect(wakeHeuristicMatch('고고핀', '고고핑')).toBe(true);
  });
  it('rejects unrelated text', () => {
    expect(wakeHeuristicMatch('안녕하세요', '고고핑')).toBe(false);
  });
  it('respects wake word identity', () => {
    expect(wakeHeuristicMatch('에듀핑', '고고핑')).toBe(false);
  });
});

describe('canonicalizeWakeWord', () => {
  it('maps alias to canonical', () => {
    expect(canonicalizeWakeWord('에듀핀', VARIANTS)).toBe('에듀핑');
  });
  it('returns null for unknown', () => {
    expect(canonicalizeWakeWord('헬로', VARIANTS)).toBeNull();
  });
});

describe('tryWakeFromText', () => {
  it('finds wake word with trailing command', () => {
    const r = tryWakeFromText('고고핑 자장가 틀어줘', '고고핑', VARIANTS, REGEX);
    expect(r).toEqual({ wakeWord: '고고핑', remainder: '자장가 틀어줘' });
  });

  it('tolerates STT spaces inside wake word', () => {
    const r = tryWakeFromText('고고 핑 안녕', '고고핑', VARIANTS, REGEX);
    expect(r?.wakeWord).toBe('고고핑');
    expect(r?.remainder).toBe('안녕');
  });

  it('matches alias and normalizes to canonical', () => {
    const r = tryWakeFromText('에듀핀', '에듀핑', VARIANTS, REGEX);
    expect(r?.wakeWord).toBe('에듀핑');
  });

  it('falls back to heuristic for near-miss STT', () => {
    const r = tryWakeFromText('꼬꼬빙', '고고핑', VARIANTS, REGEX);
    expect(r?.wakeWord).toBe('고고핑');
  });

  it('returns null for other robot wake words', () => {
    expect(tryWakeFromText('에듀핑 안녕', '고고핑', VARIANTS, REGEX)).toBeNull();
  });

  it('returns null for plain command', () => {
    expect(tryWakeFromText('자장가 틀어줘', '고고핑', VARIANTS, REGEX)).toBeNull();
  });
});

describe('isWakeOnlyUtterance', () => {
  it('true when wake word is alone', () => {
    expect(isWakeOnlyUtterance('고고핑', '고고핑', VARIANTS, REGEX)).toBe(true);
    expect(isWakeOnlyUtterance('  고고핑!  ', '고고핑', VARIANTS, REGEX)).toBe(true);
  });

  it('false when remainder is present', () => {
    expect(isWakeOnlyUtterance('고고핑 자장가', '고고핑', VARIANTS, REGEX)).toBe(false);
  });

  it('false when no wake word', () => {
    expect(isWakeOnlyUtterance('안녕', '고고핑', VARIANTS, REGEX)).toBe(false);
  });
});

describe('isStopIntent', () => {
  it.each(['정지해', '멈춰', '그만!', '스톱'])('matches stop token %s', (text) => {
    expect(isStopIntent(text)).toBe(true);
  });

  it('rejects unrelated text', () => {
    expect(isStopIntent('계속 가자')).toBe(false);
  });
});

describe('isLikelyEchoOfRobotReply', () => {
  it('empty heard is echo', () => {
    expect(isLikelyEchoOfRobotReply('', '안녕하세요')).toBe(true);
  });

  it('exact match is echo', () => {
    expect(isLikelyEchoOfRobotReply('안녕하세요', '안녕하세요')).toBe(true);
  });

  it('substring of spoken (>=2 chars) is echo', () => {
    expect(isLikelyEchoOfRobotReply('하세요', '안녕하세요')).toBe(true);
  });

  it('single char substring is NOT echo', () => {
    // 1자 echo 는 의도적으로 통과시킴 (사용자가 짧은 명령을 외쳤을 가능성)
    expect(isLikelyEchoOfRobotReply('아', '안녕하세요')).toBe(false);
  });

  it('short ack tokens are echo', () => {
    expect(isLikelyEchoOfRobotReply('네', '안녕')).toBe(true);
    expect(isLikelyEchoOfRobotReply('네요', '안녕')).toBe(true);
  });

  it('genuine user follow-up is not echo', () => {
    expect(isLikelyEchoOfRobotReply('자장가틀어줘', '안녕하세요')).toBe(false);
  });
});
