import { describe, it, expect } from 'vitest';
import { gogopingStateMessage } from '../src/gogoping/stateMessage';

describe('gogopingStateMessage', () => {
  it('maps 대기 to the friendly idle prompt', () => {
    expect(gogopingStateMessage('대기')).toBe('심심해요, 말 걸어주세요!');
  });

  it('maps each known mode to a non-empty message', () => {
    for (const mode of ['대기', '충전', '이동', '추종', '자장가', '숨바꼭질', '수동', '복귀', '오류']) {
      expect(gogopingStateMessage(mode).length).toBeGreaterThan(0);
    }
  });

  it('falls back for unknown / empty mode', () => {
    expect(gogopingStateMessage('')).toBe('안녕하세요!');
    expect(gogopingStateMessage('존재하지않는모드')).toBe('안녕하세요!');
  });
});
