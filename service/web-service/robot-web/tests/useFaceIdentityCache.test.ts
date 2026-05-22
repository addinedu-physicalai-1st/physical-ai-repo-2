import { describe, expect, it } from 'vitest';
import { useFaceIdentityCache, type IdentityResult } from '../src/composables/useFaceIdentityCache';
import type { TrackedFace } from '../src/composables/useFaceTracker';

function track(trackId: number, ageFrames = 5): TrackedFace {
  return {
    trackId,
    bbox: [0, 0, 10, 10],
    ageFrames,
    isNew: ageFrames === 0,
    lastSeenMs: Date.now(),
  };
}

describe('useFaceIdentityCache', () => {
  it('identifies a stable track exactly once', async () => {
    let calls = 0;
    const identify = async (tracks: TrackedFace[]): Promise<IdentityResult[]> => {
      calls++;
      return tracks.map((t) => ({
        trackId: t.trackId,
        childId: 100 + t.trackId,
        childName: `kid${t.trackId}`,
        distance: 0.1,
      }));
    };
    const cache = useFaceIdentityCache({ identify, stableFramesRequired: 3 });

    await cache.feed([track(1, 5)]);
    await cache.feed([track(1, 6)]);
    await cache.feed([track(1, 7)]);

    expect(calls).toBe(1);
    expect(cache.getChildId(1)).toBe(101);
  });

  it('does not identify when track has not reached stableFramesRequired', async () => {
    let calls = 0;
    const identify = async () => { calls++; return []; };
    const cache = useFaceIdentityCache({ identify, stableFramesRequired: 5 });
    await cache.feed([track(1, 2)]);
    expect(calls).toBe(0);
  });

  it('reassigns binding when same childId resolves to a newer trackId', async () => {
    const responses: Record<number, IdentityResult> = {
      1: { trackId: 1, childId: 100, childName: 'kid', distance: 0.1 },
      2: { trackId: 2, childId: 100, childName: 'kid', distance: 0.1 },
    };
    const identify = async (tracks: TrackedFace[]): Promise<IdentityResult[]> =>
      tracks.map((t) => responses[t.trackId]);
    const cache = useFaceIdentityCache({ identify, stableFramesRequired: 3 });

    await cache.feed([track(1, 5)]);
    expect(cache.getChildId(1)).toBe(100);

    await cache.feed([track(2, 5)]);
    expect(cache.getChildId(2)).toBe(100);
    // 옛 trackId 의 binding 은 제거됨.
    expect(cache.getChildId(1)).toBeNull();
  });

  it('drops binding for trackIds no longer in feed', async () => {
    const identify = async (tracks: TrackedFace[]): Promise<IdentityResult[]> =>
      tracks.map((t) => ({ trackId: t.trackId, childId: 100, childName: 'k', distance: 0.1 }));
    const cache = useFaceIdentityCache({ identify, stableFramesRequired: 3 });

    await cache.feed([track(1, 5)]);
    expect(cache.getChildId(1)).toBe(100);
    await cache.feed([]); // track 사라짐 → tracker 가 expire 시킨 상황
    expect(cache.getChildId(1)).toBeNull();
  });

  it('forget(childId) invalidates binding for that child', async () => {
    const identify = async (tracks: TrackedFace[]): Promise<IdentityResult[]> =>
      tracks.map((t) => ({ trackId: t.trackId, childId: 100, childName: 'k', distance: 0.1 }));
    const cache = useFaceIdentityCache({ identify, stableFramesRequired: 3 });

    await cache.feed([track(1, 5)]);
    expect(cache.getChildId(1)).toBe(100);
    cache.forget(100);
    expect(cache.getChildId(1)).toBeNull();
  });

  it('does not re-identify a track that returned childId=null (unmatched)', async () => {
    let calls = 0;
    const identify = async (tracks: TrackedFace[]): Promise<IdentityResult[]> => {
      calls++;
      return tracks.map((t) => ({ trackId: t.trackId, childId: null, childName: null, distance: 1.0 }));
    };
    const cache = useFaceIdentityCache({ identify, stableFramesRequired: 3 });

    await cache.feed([track(1, 5)]);
    await cache.feed([track(1, 6)]);
    await cache.feed([track(1, 7)]);
    expect(calls).toBe(1);
  });
});
