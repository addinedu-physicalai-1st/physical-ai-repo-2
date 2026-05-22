/**
 * 클라이언트 사이드 face bbox 트래커.
 *
 * 매 frame `update(detections)` 호출 → IoU 기반 greedy 매칭으로 이전 frame track 과
 * 동일 person 판정 → `trackId` 유지. 매칭 안 된 detection 은 새 track 발급.
 * 매칭 안 된 기존 track 은 `expireMs` 후 만료.
 *
 * 인원이 적은 (≤5) 시나리오라 Hungarian 매칭까지 필요 없고 greedy 로 충분.
 */

export type Bbox = [number, number, number, number]; // [x1, y1, x2, y2]

export interface TrackedFace {
  trackId: number;
  bbox: Bbox;
  ageFrames: number;
  isNew: boolean;
  lastSeenMs: number;
}

export interface UseFaceTrackerOptions {
  iouThreshold?: number; // default 0.3
  expireMs?: number; // default 800
}

export function iou(a: Bbox, b: Bbox): number {
  const x1 = Math.max(a[0], b[0]);
  const y1 = Math.max(a[1], b[1]);
  const x2 = Math.min(a[2], b[2]);
  const y2 = Math.min(a[3], b[3]);
  const iw = Math.max(0, x2 - x1);
  const ih = Math.max(0, y2 - y1);
  const inter = iw * ih;
  if (inter === 0) return 0;
  const areaA = Math.max(0, a[2] - a[0]) * Math.max(0, a[3] - a[1]);
  const areaB = Math.max(0, b[2] - b[0]) * Math.max(0, b[3] - b[1]);
  const union = areaA + areaB - inter;
  return union > 0 ? inter / union : 0;
}

export function useFaceTracker(opts: UseFaceTrackerOptions = {}): {
  update(detections: Array<{ bbox: Bbox }>): TrackedFace[];
  getTracks(): TrackedFace[];
  reset(): void;
} {
  const iouThreshold = opts.iouThreshold ?? 0.3;
  const expireMs = opts.expireMs ?? 800;

  let nextId = 1;
  let tracks: TrackedFace[] = [];

  function update(detections: Array<{ bbox: Bbox }>): TrackedFace[] {
    const now = Date.now();

    // 만료된 track 정리.
    tracks = tracks.filter((t) => now - t.lastSeenMs <= expireMs);

    // greedy IoU 매칭 — 각 detection 별로 가장 IoU 높은 track 선택, 1:1.
    const matched: TrackedFace[] = [];
    const usedTrackIds = new Set<number>();
    const usedDetIdx = new Set<number>();

    // 모든 (det, track) 쌍의 IoU 계산 후 큰 순으로 매칭.
    type Pair = { detIdx: number; track: TrackedFace; iou: number };
    const pairs: Pair[] = [];
    for (let i = 0; i < detections.length; i++) {
      for (const t of tracks) {
        const v = iou(detections[i].bbox, t.bbox);
        if (v >= iouThreshold) pairs.push({ detIdx: i, track: t, iou: v });
      }
    }
    pairs.sort((a, b) => b.iou - a.iou);
    for (const p of pairs) {
      if (usedDetIdx.has(p.detIdx)) continue;
      if (usedTrackIds.has(p.track.trackId)) continue;
      usedDetIdx.add(p.detIdx);
      usedTrackIds.add(p.track.trackId);
      matched.push({
        trackId: p.track.trackId,
        bbox: detections[p.detIdx].bbox,
        ageFrames: p.track.ageFrames + 1,
        isNew: false,
        lastSeenMs: now,
      });
    }

    // 매칭 안 된 detection → 새 track.
    for (let i = 0; i < detections.length; i++) {
      if (usedDetIdx.has(i)) continue;
      matched.push({
        trackId: nextId++,
        bbox: detections[i].bbox,
        ageFrames: 0,
        isNew: true,
        lastSeenMs: now,
      });
    }

    // 이번 frame 에서 매칭 안 된 기존 track 은 그대로 유지 (만료까지 살아있음) — 표시는 안 함.
    const stillAlive = tracks.filter((t) => !usedTrackIds.has(t.trackId));
    tracks = [...matched, ...stillAlive];

    return matched;
  }

  function getTracks(): TrackedFace[] {
    return tracks.slice();
  }

  function reset(): void {
    tracks = [];
    nextId = 1;
  }

  return { update, getTracks, reset };
}
