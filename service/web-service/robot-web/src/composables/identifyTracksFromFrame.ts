/**
 * 전체 frame 을 /api/attendance/recognize-multi 에 보내고 응답 bbox 를 클라이언트 track 에
 * greedy IoU 매칭해 IdentityResult[] 로 변환.
 *
 * 클라의 MediaPipe 와 서버의 InsightFace 가 같은 프레임을 각각 detect 한다. 한쪽이
 * 잡지 못한 얼굴은 결과에 안 포함 — 그 trackId 는 다음 stable feed 에서 재시도된다
 * (`useFaceIdentityCache` 가 candidate 에서 빠진 result 를 fail 로 마킹하지 않음).
 */
import { iou, type Bbox, type TrackedFace } from './useFaceTracker';
import type { IdentityResult } from './useFaceIdentityCache';

export interface ServerMatch {
  matched: boolean;
  child_id: number | null;
  child_name: string | null;
  distance: number | null;
  bbox: number[] | null;
}

export async function postRecognizeMulti(
  frame: Blob,
  deviceToken: string,
): Promise<ServerMatch[]> {
  const form = new FormData();
  form.append('file', frame, 'frame.jpg');
  try {
    const res = await fetch('/api/attendance/recognize-multi', {
      method: 'POST',
      headers: { 'X-Device-Token': deviceToken },
      body: form,
    });
    if (!res.ok) return [];
    const body = (await res.json()) as { matches: ServerMatch[] };
    return body.matches;
  } catch {
    return [];
  }
}

/**
 * 서버 matches[] 를 클라이언트 tracks 에 1:1 greedy IoU 매칭.
 * 매칭 안 된 track 은 결과에서 빠짐 (다음 stable feed 에서 재시도).
 */
export function mapMatchesToTracks(
  tracks: TrackedFace[],
  matches: ServerMatch[],
  iouThreshold = 0.3,
): Array<{ result: IdentityResult; track: TrackedFace; match: ServerMatch }> {
  type Pair = { matchIdx: number; trackIdx: number; iou: number };
  const pairs: Pair[] = [];
  for (let mi = 0; mi < matches.length; mi++) {
    const mb = matches[mi].bbox;
    if (!mb || mb.length < 4) continue;
    const mbbox: Bbox = [mb[0], mb[1], mb[2], mb[3]];
    for (let ti = 0; ti < tracks.length; ti++) {
      const v = iou(mbbox, tracks[ti].bbox);
      if (v >= iouThreshold) pairs.push({ matchIdx: mi, trackIdx: ti, iou: v });
    }
  }
  pairs.sort((a, b) => b.iou - a.iou);
  const usedMatch = new Set<number>();
  const usedTrack = new Set<number>();
  const out: Array<{ result: IdentityResult; track: TrackedFace; match: ServerMatch }> = [];
  for (const p of pairs) {
    if (usedMatch.has(p.matchIdx) || usedTrack.has(p.trackIdx)) continue;
    usedMatch.add(p.matchIdx);
    usedTrack.add(p.trackIdx);
    const m = matches[p.matchIdx];
    const t = tracks[p.trackIdx];
    out.push({
      track: t,
      match: m,
      result: {
        trackId: t.trackId,
        childId: m.matched ? m.child_id : null,
        childName: m.matched ? m.child_name : null,
        distance: m.distance,
      },
    });
  }
  return out;
}
