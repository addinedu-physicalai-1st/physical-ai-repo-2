/**
 * 외장 USB 카메라 선택 — 노트북 내장 카메라 (Integrated/Built-in/Bison 등) 와
 * RealSense depth 카메라를 label 패턴으로 제외하고 첫 외장 후보를 돌려준다. 없으면 null.
 *
 * label 이 비어 있으면 (권한 직전 / 일부 드라이버) 후보로 간주.
 */
const INTERNAL_LABEL_PATTERNS: RegExp[] = [
  /\b(integrated|built[- ]?in|internal)\b/i,
  /\b(facetime hd|facetime|iris|fbcam)\b/i,
  /\b(hp truevision|hp wide vision|lenovo easycamera|cyberlink|mi webcam)\b/i,
  /\bbison\b/i,
  /내장/,
];

// RealSense (Intel depth 카메라, 예: D435) — eduping depth 파이프라인의 ROS
// d435_camera 노드가 librealsense 로 디바이스를 독점 점유한다. 그래서 브라우저
// getUserMedia 로 같은 디바이스(Depth/RGB 모듈)를 열면 busy → black frame 이라
// 얼굴인식·비전에 못 쓴다. label 에 "RealSense" 가 들어가는 Depth/RGB 항목 둘 다 제외.
const DEPTH_CAMERA_LABEL_PATTERNS: RegExp[] = [
  /realsense/i,
];

/** RealSense 등 depth 카메라 (getUserMedia 로는 동작 안 함) 인지. */
export function isDepthCamera(d: MediaDeviceInfo): boolean {
  return DEPTH_CAMERA_LABEL_PATTERNS.some((rx) => rx.test(d.label || ''));
}

function isExternalCamera(d: MediaDeviceInfo): boolean {
  if (d.kind !== 'videoinput') return false;
  const label = (d.label || '').trim();
  if (!label) return true;
  if (isDepthCamera(d)) return false;   // RealSense = busy/black, face-rec 불가
  return !INTERNAL_LABEL_PATTERNS.some((rx) => rx.test(label));
}

export async function pickExternalCamera(): Promise<MediaDeviceInfo | null> {
  let devs = await navigator.mediaDevices.enumerateDevices();
  if (devs.filter((d) => d.kind === 'videoinput').every((d) => !d.label)) {
    try {
      const tmp = await navigator.mediaDevices.getUserMedia({ video: true });
      tmp.getTracks().forEach((t) => t.stop());
    } catch {
      /* 권한 거부해도 enumerate 는 동작 (label 빈 채로) */
    }
    devs = await navigator.mediaDevices.enumerateDevices();
  }
  return devs.find(isExternalCamera) ?? null;
}
