import { describe, expect, it } from 'vitest';
import { parsePerceptionEvent } from '../src/eduping/useMugunghwaPerception';

describe('parsePerceptionEvent', () => {
  it('parses registered', () => {
    expect(parsePerceptionEvent('{"type":"registered","child_id":7}'))
      .toEqual({ type: 'registered', childId: 7 });
  });

  it('parses eliminated with child_ids', () => {
    expect(parsePerceptionEvent('{"type":"eliminated","child_ids":[3,5]}'))
      .toEqual({ type: 'eliminated', childIds: [3, 5] });
  });

  it('parses motion', () => {
    expect(parsePerceptionEvent('{"type":"motion"}')).toEqual({ type: 'motion' });
  });

  it('ignores peer/presence messages', () => {
    expect(parsePerceptionEvent('{"type":"peer","present":true}')).toBeNull();
  });

  it('returns null on malformed json', () => {
    expect(parsePerceptionEvent('not json')).toBeNull();
  });

  it('returns null on unknown type', () => {
    expect(parsePerceptionEvent('{"type":"wat"}')).toBeNull();
  });
});
