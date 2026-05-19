/**
 * 외장 USB 카메라 선택 — 노트북 내장 카메라 (Integrated/Built-in/Bison 등) 를
 * label 패턴으로 제외하고 첫 외장 후보를 돌려준다. 없으면 null.
 *
 * label 이 비어 있으면 (권한 직전 / 일부 드라이버) 후보로 간주.
 *
 * 노트: robot-web 의 `composables/selectExternalCamera.ts` 와 동일한 구현 — 두 앱이
 * 별도 번들이라 코드 공유가 안 돼서 중복 유지. 패턴 추가 시 양쪽을 같이 수정한다.
 */
const INTERNAL_LABEL_PATTERNS: RegExp[] = [
  /\b(integrated|built[- ]?in|internal)\b/i,
  /\b(facetime hd|facetime|iris|fbcam)\b/i,
  /\b(hp truevision|hp wide vision|lenovo easycamera|cyberlink|mi webcam)\b/i,
  /\bbison\b/i,
  /내장/,
]

function isExternalCamera(d: MediaDeviceInfo): boolean {
  if (d.kind !== 'videoinput') return false
  const label = (d.label || '').trim()
  if (!label) return true
  return !INTERNAL_LABEL_PATTERNS.some((rx) => rx.test(label))
}

export async function pickExternalCamera(): Promise<MediaDeviceInfo | null> {
  let devs = await navigator.mediaDevices.enumerateDevices()
  if (devs.filter((d) => d.kind === 'videoinput').every((d) => !d.label)) {
    try {
      const tmp = await navigator.mediaDevices.getUserMedia({ video: true })
      tmp.getTracks().forEach((t) => t.stop())
    } catch {
      /* 권한 거부해도 enumerate 는 동작 (label 빈 채로) */
    }
    devs = await navigator.mediaDevices.enumerateDevices()
  }
  return devs.find(isExternalCamera) ?? null
}
