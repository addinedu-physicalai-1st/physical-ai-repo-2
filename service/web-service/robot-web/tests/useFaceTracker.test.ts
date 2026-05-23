import { describe, expect, it } from 'vitest';
import { useFaceTracker } from '../src/composables/useFaceTracker';

type Bbox = [number, number, number, number];

function det(...bs: Bbox[]) {
  return bs.map((bbox) => ({ bbox }));
}

describe('useFaceTracker', () => {
  it('assigns new trackId to first detection', () => {
    const tr = useFaceTracker({ expireMs: 1000 });
    const out = tr.update(det([10, 10, 50, 50]));
    expect(out).toHaveLength(1);
    expect(out[0].isNew).toBe(true);
    expect(out[0].ageFrames).toBe(0);
  });

  it('keeps same trackId when bbox overlaps with prior frame (IoU > 0.3)', () => {
    const tr = useFaceTracker();
    const a = tr.update(det([10, 10, 50, 50]));
    const b = tr.update(det([12, 12, 52, 52])); // 거의 동일 위치
    expect(b[0].trackId).toBe(a[0].trackId);
    expect(b[0].isNew).toBe(false);
    expect(b[0].ageFrames).toBe(1);
  });

  it('assigns new trackId when bbox jumps far (IoU 0)', () => {
    const tr = useFaceTracker();
    const a = tr.update(det([10, 10, 50, 50]));
    const b = tr.update(det([200, 200, 250, 250]));
    expect(b[0].trackId).not.toBe(a[0].trackId);
    expect(b[0].isNew).toBe(true);
  });

  it('matches two tracks across frames by IoU', () => {
    const tr = useFaceTracker();
    const a = tr.update(det([10, 10, 50, 50], [100, 100, 140, 140]));
    const b = tr.update(det([102, 102, 142, 142], [11, 11, 51, 51]));
    // 입력 순서 바뀌어도 trackId 는 위치 기준 매칭
    const aIds = a.map((t) => t.trackId).sort();
    const bIds = b.map((t) => t.trackId).sort();
    expect(bIds).toEqual(aIds);
  });

  it('expires track after expireMs of no detection', async () => {
    const tr = useFaceTracker({ expireMs: 50 });
    const a = tr.update(det([10, 10, 50, 50]));
    tr.update([]); // 사라짐
    await new Promise((r) => setTimeout(r, 70));
    const c = tr.update(det([10, 10, 50, 50]));
    expect(c[0].trackId).not.toBe(a[0].trackId);
    expect(c[0].isNew).toBe(true);
  });

  it('reset() clears all tracks and resets ID counter', () => {
    const tr = useFaceTracker();
    tr.update(det([10, 10, 50, 50]));
    tr.reset();
    const out = tr.update(det([10, 10, 50, 50]));
    expect(out[0].isNew).toBe(true);
  });
});
