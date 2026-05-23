/**
 * track_id → child_id 캐시 + identify 발사 게이트.
 *
 * 매 frame `feed(tracks)` 호출:
 *  1) tracks 에 더 이상 안 보이는 trackId 의 binding 제거 (tracker 가 expire 시킨 것).
 *  2) 안정적 (ageFrames >= stableFramesRequired) 이고 아직 식별 안 된 track 모음.
 *  3) identify(tracks) 호출 → 결과를 bindings 에 등록.
 *
 * 동일 childId 가 두 trackId 에 매핑되면 더 큰 (= 더 최근) trackId 만 유지.
 * childId=null 결과는 "얼굴은 있지만 매칭 실패" 의미 — 재시도 안 함 (낭비 방지).
 */
import { readonly, ref } from 'vue';
import type { Ref, DeepReadonly } from 'vue';
import type { TrackedFace } from './useFaceTracker';

export interface IdentityResult {
  trackId: number;
  childId: number | null;
  childName: string | null;
  distance: number | null;
}

export interface IdentityBinding {
  trackId: number;
  childId: number | null;
  childName: string | null;
  distance: number | null;
  resolvedAt: number;
}

export interface UseFaceIdentityCacheOptions {
  stableFramesRequired?: number;  // default 5
  identifyTimeoutMs?: number;     // default 4000
  identify: (tracks: TrackedFace[]) => Promise<IdentityResult[]>;
}

export function useFaceIdentityCache(opts: UseFaceIdentityCacheOptions): {
  feed(tracks: TrackedFace[]): Promise<void>;
  bindings: DeepReadonly<Ref<Map<number, IdentityBinding>>>;
  getChildId(trackId: number): number | null;
  forget(childId: number): void;
  reset(): void;
} {
  const stableFramesRequired = opts.stableFramesRequired ?? 5;
  const identifyTimeoutMs = opts.identifyTimeoutMs ?? 4000;

  const bindings = ref(new Map<number, IdentityBinding>());
  // 이미 식별 시도 후 childId=null 로 끝난 trackId — 재시도 안 함.
  const failedTrackIds = new Set<number>();
  let inflight = false;
  let inflightStartedAt = 0;

  function syncExistingTracks(tracks: TrackedFace[]): void {
    const liveIds = new Set(tracks.map((t) => t.trackId));
    const next = new Map(bindings.value);
    for (const id of next.keys()) {
      if (!liveIds.has(id)) next.delete(id);
    }
    bindings.value = next;
    for (const id of [...failedTrackIds]) {
      if (!liveIds.has(id)) failedTrackIds.delete(id);
    }
  }

  function applyResults(results: IdentityResult[]): void {
    const next = new Map(bindings.value);
    const now = Date.now();
    for (const r of results) {
      if (r.childId === null) {
        failedTrackIds.add(r.trackId);
        continue;
      }
      // 같은 childId 가 다른 trackId 에 이미 바인딩됐다면 최신 trackId 로 이관.
      for (const [tid, b] of next) {
        if (b.childId === r.childId && tid !== r.trackId) next.delete(tid);
      }
      next.set(r.trackId, {
        trackId: r.trackId,
        childId: r.childId,
        childName: r.childName,
        distance: r.distance,
        resolvedAt: now,
      });
    }
    bindings.value = next;
  }

  async function feed(tracks: TrackedFace[]): Promise<void> {
    syncExistingTracks(tracks);

    // inflight timeout 해제.
    if (inflight && Date.now() - inflightStartedAt > identifyTimeoutMs) {
      inflight = false;
    }
    if (inflight) return;

    const candidates = tracks.filter(
      (t) =>
        t.ageFrames >= stableFramesRequired &&
        !bindings.value.has(t.trackId) &&
        !failedTrackIds.has(t.trackId),
    );
    if (candidates.length === 0) return;

    inflight = true;
    inflightStartedAt = Date.now();
    try {
      const results = await opts.identify(candidates);
      applyResults(results);
    } finally {
      inflight = false;
    }
  }

  function getChildId(trackId: number): number | null {
    return bindings.value.get(trackId)?.childId ?? null;
  }

  function forget(childId: number): void {
    const next = new Map(bindings.value);
    for (const [tid, b] of next) {
      if (b.childId === childId) next.delete(tid);
    }
    bindings.value = next;
  }

  function reset(): void {
    bindings.value = new Map();
    failedTrackIds.clear();
    inflight = false;
  }

  return {
    feed,
    bindings: readonly(bindings) as DeepReadonly<Ref<Map<number, IdentityBinding>>>,
    getChildId,
    forget,
    reset,
  };
}
