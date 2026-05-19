export interface JoystickVector { pan: number; tilt: number }
export interface JoystickConfig {
  radiusPx: number;
  maxDegPerSec: number;
}

export function vectorFromOffset(
  dxPx: number,
  dyPx: number,
  cfg: JoystickConfig,
): JoystickVector {
  const r = Math.hypot(dxPx, dyPx);
  if (r === 0) return { pan: 0, tilt: 0 };
  const clampedR = Math.min(r, cfg.radiusPx);
  const ux = (dxPx / r) * (clampedR / cfg.radiusPx);
  const uy = (dyPx / r) * (clampedR / cfg.radiusPx);
  return {
    pan:  ux * cfg.maxDegPerSec,
    tilt: -uy * cfg.maxDegPerSec,
  };
}
