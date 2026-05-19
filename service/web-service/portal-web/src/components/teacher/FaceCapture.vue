<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, computed, watch } from 'vue'
import { FaceMesh, type Results } from '@mediapipe/face_mesh'
import {
  estimateHeadPose,
  matchesTarget,
  TARGET_ORDER,
  TARGET_HINTS,
} from '@/lib/headPose'
import { pickExternalCamera } from '@/lib/selectExternalCamera'
import Icon from '@/components/common/Icon.vue'

const props = withDefaults(defineProps<{
  uploading?: boolean
}>(), {
  uploading: false,
})

const emit = defineEmits<{
  (e: 'complete', images: Blob[]): void
}>()

const videoRef = ref<HTMLVideoElement | null>(null)
const canvasRef = ref<HTMLCanvasElement | null>(null)
const targetIndex = ref(0)
const captured = ref<Blob[]>([])
const thumbs = ref<string[]>([])
const flash = ref(false)
const finalizing = ref(false)

const cameras = ref<MediaDeviceInfo[]>([])
const selectedDeviceId = ref<string>('')
const hasCameras = computed(() => cameras.value.length > 0)

const showSpinner = computed(() => finalizing.value || props.uploading)

// 부모에서 업로드가 종료되면 (성공/실패 무관) finalizing 도 해제해 스피너가
// 남는 일을 방지. 성공 시엔 부모가 capturing=false 로 본 컴포넌트를 unmount 한다.
watch(() => props.uploading, (now, prev) => {
  if (prev && !now) finalizing.value = false
})

const primaryHint = ref<string>('카메라 준비 중...')
const detected = ref<boolean>(false)
const debugYaw = ref<number>(0)
const debugPitch = ref<number>(0)

let stream: MediaStream | null = null
let faceMesh: FaceMesh | null = null
let rafId: number | null = null
let captureLockUntil = 0
let capturePending = false
let stopped = false

const stepLabels: Record<string, string> = {
  front: '정면',
  left: '왼쪽',
  right: '오른쪽',
  up: '위',
  down: '아래',
}

const currentStepLabel = computed(() => {
  const t = TARGET_ORDER[targetIndex.value]
  return t ? stepLabels[t] : '완료'
})

async function listCameras() {
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
  cameras.value = devs.filter((d) => d.kind === 'videoinput')
  if (cameras.value.length === 0) {
    selectedDeviceId.value = ''
    return
  }
  const stillValid = cameras.value.some((c) => c.deviceId === selectedDeviceId.value)
  if (!selectedDeviceId.value || !stillValid) {
    // 기본 외장 USB — 없으면 첫 후보. 노트북 내장 카메라는 보통 위치·각도가 안 맞아
    // 얼굴 등록 정확도가 낮다.
    const ext = await pickExternalCamera()
    selectedDeviceId.value = ext?.deviceId ?? cameras.value[0].deviceId
  }
}

async function setupCamera() {
  if (cameras.value.length === 0) await listCameras()
  const video = selectedDeviceId.value
    ? { deviceId: { exact: selectedDeviceId.value }, width: 640, height: 480 }
    : { width: 640, height: 480 }
  stream = await navigator.mediaDevices.getUserMedia({
    video,
    audio: false,
  })
  if (videoRef.value) {
    videoRef.value.srcObject = stream
    await videoRef.value.play()
  }
}

async function changeCamera() {
  // 캡처 진행 중 카메라 교체 — 기존 stream 만 교체하고 mediapipe·rafId 는 그대로.
  if (!stream) return
  stream.getTracks().forEach((t) => t.stop())
  stream = null
  try {
    await setupCamera()
  } catch {
    primaryHint.value = '카메라 접근 실패 — 권한을 허용했는지 확인해주세요'
  }
}

async function rescan() {
  await listCameras()
}

let deviceChangeDebounce: number | null = null
function scheduleListCamerasOnDeviceChange() {
  if (deviceChangeDebounce !== null) {
    window.clearTimeout(deviceChangeDebounce)
  }
  deviceChangeDebounce = window.setTimeout(() => {
    deviceChangeDebounce = null
    void listCameras()
  }, 400)
}

function setupFaceMesh() {
  faceMesh = new FaceMesh({
    locateFile: (file) =>
      `https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh@0.4/${file}`,
  })
  faceMesh.setOptions({
    maxNumFaces: 1,
    refineLandmarks: false,
    minDetectionConfidence: 0.6,
    minTrackingConfidence: 0.6,
  })
  faceMesh.onResults(handleResults)
}

function handleResults(results: Results) {
  if (targetIndex.value >= TARGET_ORDER.length) return

  const landmarks = results.multiFaceLandmarks?.[0]
  if (!landmarks) {
    detected.value = false
    primaryHint.value = '얼굴이 보이지 않아요'
    return
  }

  detected.value = true
  const target = TARGET_ORDER[targetIndex.value]
  const pose = estimateHeadPose(landmarks as any)
  primaryHint.value = TARGET_HINTS[target]
  debugYaw.value = pose.yaw
  debugPitch.value = pose.pitch

  if (capturePending || Date.now() < captureLockUntil) return

  if (matchesTarget(pose, target)) {
    // canvas.toBlob 이 비동기라 락을 .then() 안에 두면 그 사이 프레임들이
    // 모두 matchesTarget 을 통과해 다중 캡처가 발생한다. 동기적으로 잠근다.
    capturePending = true
    flash.value = true
    setTimeout(() => { flash.value = false }, 200)
    captureFrame().then((blob) => {
      captureLockUntil = Date.now() + 800
      capturePending = false
      if (!blob) return
      captured.value.push(blob)
      thumbs.value.push(URL.createObjectURL(blob))

      if (captured.value.length >= TARGET_ORDER.length) {
        // 마지막 썸네일/체크 표시를 사용자가 인지하도록 잠시 대기 후 emit.
        finalizing.value = true
        cleanup()
        setTimeout(() => {
          emit('complete', captured.value)
        }, 600)
      } else {
        targetIndex.value += 1
      }
    })
  }
}

async function captureFrame(): Promise<Blob | null> {
  const video = videoRef.value
  const canvas = canvasRef.value
  if (!video || !canvas) return null
  canvas.width = video.videoWidth
  canvas.height = video.videoHeight
  const ctx = canvas.getContext('2d')
  if (!ctx) return null
  ctx.drawImage(video, 0, 0)
  return new Promise((resolve) =>
    canvas.toBlob((b) => resolve(b), 'image/jpeg', 0.85)
  )
}

async function loop() {
  if (stopped) return
  if (videoRef.value && faceMesh && videoRef.value.readyState >= 2) {
    try {
      await faceMesh.send({ image: videoRef.value })
    } catch {
      // faceMesh 가 close 되는 도중 send 가 throw 할 수 있음 — 그냥 종료.
      return
    }
  }
  // await 사이에 cleanup 이 일어났을 수 있으므로 재예약 직전에 다시 확인.
  if (stopped) return
  rafId = requestAnimationFrame(loop)
}

function cleanup() {
  if (stopped) return
  stopped = true
  if (rafId !== null) cancelAnimationFrame(rafId)
  rafId = null
  stream?.getTracks().forEach((t) => t.stop())
  stream = null
  const mesh = faceMesh
  faceMesh = null
  mesh?.close()
}

onMounted(async () => {
  try {
    await listCameras()
    await setupCamera()
    setupFaceMesh()
    rafId = requestAnimationFrame(loop)
    primaryHint.value = TARGET_HINTS[TARGET_ORDER[0]]
  } catch {
    primaryHint.value = '카메라 접근 실패 — 권한을 허용했는지 확인해주세요'
  }
  navigator.mediaDevices.addEventListener('devicechange', scheduleListCamerasOnDeviceChange)
})

onBeforeUnmount(() => {
  navigator.mediaDevices.removeEventListener('devicechange', scheduleListCamerasOnDeviceChange)
  if (deviceChangeDebounce !== null) {
    window.clearTimeout(deviceChangeDebounce)
    deviceChangeDebounce = null
  }
  cleanup()
  thumbs.value.forEach((url) => URL.revokeObjectURL(url))
})
</script>

<template>
  <div class="capture">
    <div class="capture__main">
      <div class="capture__cam-controls">
        <select
          v-model="selectedDeviceId"
          :disabled="!hasCameras"
          class="capture__cam-select"
          @change="changeCamera"
        >
          <option v-if="!hasCameras" disabled value="">— 카메라 없음 —</option>
          <option v-for="c in cameras" :key="c.deviceId" :value="c.deviceId">
            {{ c.label || `카메라 ${c.deviceId.slice(0, 8)}…` }}
          </option>
        </select>
        <button class="capture__cam-rescan" type="button" title="다시 스캔" @click="rescan">↻</button>
      </div>
      <div class="capture__preview" :class="{ 'capture__preview--flash': flash }">
        <video ref="videoRef" muted playsinline />
        <canvas ref="canvasRef" class="capture__canvas" />
        <div class="capture__overlay">
          <div class="capture__oval" :class="{ 'capture__oval--ok': detected }" />
        </div>
        <div v-if="flash" class="capture__flash" />
        <div v-if="showSpinner" class="capture__spinner" role="status" aria-live="polite">
          <Icon name="loader-circle" :size="32" class="capture__spinner-icon" />
          <span class="capture__spinner-label">
            {{ props.uploading ? '얼굴 사진 등록 중...' : '캡처 완료, 업로드 준비 중...' }}
          </span>
        </div>
      </div>

      <div class="capture__thumbs">
        <div
          v-for="(t, i) in TARGET_ORDER"
          :key="t"
          class="capture__thumb"
          :class="{ 'capture__thumb--done': i < captured.length, 'capture__thumb--active': i === targetIndex }"
        >
          <img v-if="thumbs[i]" :src="thumbs[i]" :alt="stepLabels[t]" />
          <span v-else class="capture__thumb-label">{{ stepLabels[t] }}</span>
          <span v-if="i < captured.length" class="capture__thumb-check">
            <Icon name="check" :size="14" />
          </span>
        </div>
      </div>
    </div>

    <aside class="capture__panel">
      <div class="capture__panel-head">
        <span class="capture__step">STEP {{ Math.min(targetIndex + 1, TARGET_ORDER.length) }} / {{ TARGET_ORDER.length }}</span>
        <h3 class="capture__title">{{ currentStepLabel }}</h3>
      </div>

      <div class="capture__progress">
        <div class="capture__progress-fill" :style="{ width: `${(captured.length / TARGET_ORDER.length) * 100}%` }" />
      </div>

      <div class="capture__instruction" :class="{ 'capture__instruction--warn': !detected }">
        <Icon :name="detected ? 'camera' : 'alert-circle'" :size="18" />
        <span>{{ primaryHint }}</span>
      </div>

      <dl class="capture__debug">
        <div class="capture__debug-row">
          <dt>Yaw</dt>
          <dd class="numeric">{{ debugYaw.toFixed(0) }}°</dd>
        </div>
        <div class="capture__debug-row">
          <dt>Pitch</dt>
          <dd class="numeric">{{ debugPitch.toFixed(0) }}°</dd>
        </div>
      </dl>
    </aside>
  </div>
</template>

<style scoped>
.capture {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 280px;
  gap: var(--space-5);
  align-items: stretch;
}

.capture__main {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  min-width: 0;
}

.capture__cam-controls {
  display: flex;
  gap: var(--space-2);
  align-items: center;
}
.capture__cam-select {
  flex: 1;
  min-width: 0;
  padding: 6px 8px;
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border-subtle);
  font-size: var(--font-size-sm);
  font-family: inherit;
  background: var(--color-surface-raised);
  color: var(--color-text-primary);
}
.capture__cam-select:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.capture__cam-rescan {
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-md);
  padding: 4px 10px;
  cursor: pointer;
  font-size: 14px;
  font-family: inherit;
  color: var(--color-text-secondary);
  flex-shrink: 0;
}

.capture__preview {
  position: relative;
  width: 100%;
  aspect-ratio: 4 / 3;
  border-radius: var(--radius-lg);
  overflow: hidden;
  box-shadow: var(--shadow-sm);
  background: #1a1a1a;
  transition: box-shadow var(--motion-base) var(--motion-ease);
}
.capture__preview--flash {
  box-shadow: 0 0 0 4px var(--color-status-success);
}
.capture__preview video {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  transform: scaleX(-1);
}
.capture__canvas { display: none !important; }

.capture__overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}
.capture__oval {
  width: 56%;
  height: 78%;
  border: 3px dashed var(--color-brand-primary);
  border-radius: 50%;
  opacity: 0.7;
  transition: border-color var(--motion-base) var(--motion-ease), opacity var(--motion-base) var(--motion-ease);
}
.capture__oval--ok {
  border-color: var(--color-status-success);
  border-style: solid;
  opacity: 0.9;
}

.capture__flash {
  position: absolute;
  inset: 0;
  background: rgba(255, 255, 255, 0.4);
  pointer-events: none;
}

.capture__spinner {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  backdrop-filter: blur(2px);
  z-index: 2;
}
.capture__spinner-icon {
  animation: capture-spin 1s linear infinite;
}
.capture__spinner-label {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
}
@keyframes capture-spin {
  to { transform: rotate(360deg); }
}

.capture__thumbs {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: var(--space-2);
}
.capture__thumb {
  position: relative;
  aspect-ratio: 1;
  border-radius: var(--radius-md);
  border: 2px solid var(--color-border-subtle);
  background: var(--color-surface-sunken);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  transition: border-color var(--motion-base) var(--motion-ease);
}
.capture__thumb--active {
  border-color: var(--color-brand-primary);
  box-shadow: 0 0 0 2px var(--color-brand-primary-soft);
}
.capture__thumb--done {
  border-color: var(--color-status-success);
}
.capture__thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transform: scaleX(-1);
}
.capture__thumb-label {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  font-weight: var(--font-weight-medium);
}
.capture__thumb-check {
  position: absolute;
  top: 4px;
  right: 4px;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--color-status-success);
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.capture__panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-5);
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-lg);
}

.capture__panel-head {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
.capture__step {
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-semibold);
  letter-spacing: 0.08em;
  color: var(--color-text-muted);
}
.capture__title {
  font-size: var(--font-size-2xl);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin: 0;
  line-height: 1.1;
}

.capture__progress {
  height: 8px;
  background: var(--color-surface-sunken);
  border-radius: var(--radius-full);
  overflow: hidden;
}
.capture__progress-fill {
  height: 100%;
  background: var(--color-status-success);
  border-radius: inherit;
  transition: width var(--motion-base) var(--motion-ease);
}

.capture__instruction {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  background: var(--color-brand-primary-soft);
  color: var(--color-brand-primary);
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  line-height: 1.4;
}
.capture__instruction--warn {
  background: var(--color-status-warning-soft, #FFF4E0);
  color: var(--color-status-warning, #B97800);
}

.capture__debug {
  display: flex;
  gap: var(--space-4);
  margin: 0;
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-border-subtle);
}
.capture__debug-row {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.capture__debug-row dt {
  font-size: 11px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--color-text-muted);
}
.capture__debug-row dd {
  margin: 0;
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-secondary);
}
</style>
