/**
 * Precompute clipped poses off the main thread (compare playback).
 */

interface JointLimit {
  min: number;
  max: number;
}

interface ClipRequest {
  frames: number[][];
  jointNames: string[];
  limitsBefore: Record<string, JointLimit>;
  limitsAfter: Record<string, JointLimit>;
}

function clipPose(
  pose: number[],
  names: string[],
  limits: Record<string, JointLimit>,
): Float32Array {
  const out = new Float32Array(pose.length);
  for (let i = 0; i < pose.length; i++) {
    const lim = limits[names[i]];
    const v = pose[i];
    out[i] = lim ? Math.min(Math.max(v, lim.min), lim.max) : v;
  }
  return out;
}

self.onmessage = (ev: MessageEvent<ClipRequest>) => {
  const { frames, jointNames, limitsBefore, limitsAfter } = ev.data;
  const before: Float32Array[] = [];
  const after: Float32Array[] = [];
  for (const pose of frames) {
    before.push(clipPose(pose, jointNames, limitsBefore));
    after.push(clipPose(pose, jointNames, limitsAfter));
  }
  self.postMessage({ before, after });
};
