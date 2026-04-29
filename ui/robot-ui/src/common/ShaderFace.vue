<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import * as THREE from 'three';
import type { EmotionId } from '@/config/robots';

const props = defineProps<{ emotion: EmotionId; accent: string }>();

interface EyeP {
  cx: number;
  cy: number;
  sx: number;
  sy: number;
  radius: number;
  // 눈 닫힘 정도. 0=완전히 뜸, 1=완전히 감음
  closure: number;
  // smileArc: 0=일반 사각형 눈, 1=위로 굽은 활(⌒) 눈웃음. 0~1 사이 mix.
  // smileBow=활 높이, smileThickness=활 굵기
  smile: number;
  smileBow: number;
  smileThickness: number;
}

interface BrowP {
  cx: number;
  cy: number;
  halfLen: number;
  thickness: number;
  // CCW 기준. 왼쪽 눈썹의 +tilt → 안쪽(오른쪽 끝)이 위로 올라감 → 슬픔/걱정
  // 왼쪽 눈썹의 −tilt → 안쪽이 내려감 → 분노/위협
  tilt: number;
  // 0 일 때 렌더링하지 않음 (수면)
  visible: number;
  // 0=직선 막대, 1=위로 솟은 ^ 아치
  peak: number;
}

interface MouthP {
  cx: number;
  cy: number;
  halfWidth: number;
  // 양수=웃음(⌣, peak 아래), 음수=찡그림(⌒, peak 위), 0=수평선
  bow: number;
  thickness: number;
  // 0=선/곡선, 1=벌린 입(타원 ○)
  openness: number;
}

interface FacePreset {
  L: EyeP;
  R: EyeP;
  BL: BrowP;
  BR: BrowP;
  M: MouthP;
}

// 표정 프리셋 — 눈 + 눈썹 + 입의 3-요소 캐릭터 페이스 (Moxie/Miko 계열)
// 좌표계: x ≈ ±aspect 범위, y 는 [-1, +1]. 페이스 그룹은 y=0 (화면 가운데) 부근에 배치
const NO_SMILE = { smile: 0, smileBow: 0, smileThickness: 0 };
const PRESETS: Record<EmotionId, FacePreset> = {
  basic: {
    L: { cx: -0.42, cy: 0.06, sx: 0.16, sy: 0.20, radius: 0.10, closure: 0, ...NO_SMILE },
    R: { cx: 0.42, cy: 0.06, sx: 0.16, sy: 0.20, radius: 0.10, closure: 0, ...NO_SMILE },
    BL: { cx: -0.42, cy: 0.40, halfLen: 0.18, thickness: 0.04, tilt: 0, visible: 1, peak: 0 },
    BR: { cx: 0.42, cy: 0.40, halfLen: 0.18, thickness: 0.04, tilt: 0, visible: 1, peak: 0 },
    M: { cx: 0, cy: -0.40, halfWidth: 0.16, bow: 0.04, thickness: 0.05, openness: 0 },
  },
  hello: {
    L: { cx: -0.42, cy: 0.08, sx: 0.16, sy: 0.22, radius: 0.10, closure: 0, ...NO_SMILE },
    R: { cx: 0.42, cy: 0.08, sx: 0.16, sy: 0.22, radius: 0.10, closure: 0, ...NO_SMILE },
    // ^^ 모양 — tilt 없이 peak 만 사용
    BL: { cx: -0.42, cy: 0.44, halfLen: 0.18, thickness: 0.04, tilt: 0, visible: 1, peak: 1 },
    BR: { cx: 0.42, cy: 0.44, halfLen: 0.18, thickness: 0.04, tilt: 0, visible: 1, peak: 1 },
    // 입은 tick 에서 작은 o ↔ 큰 O 로 천천히 oscillate
    M: { cx: 0, cy: -0.40, halfWidth: 0.16, bow: 0, thickness: 0.05, openness: 0 },
  },
  happy: {
    // 눈웃음 ⌒⌒ — 박스 대신 위로 굽은 활 형태. closure 는 0 (활이 sy 만으로 그려짐)
    L: { cx: -0.42, cy: 0.06, sx: 0.20, sy: 0.10, radius: 0.05, closure: 0,
         smile: 1, smileBow: 0.18, smileThickness: 0.07 },
    R: { cx: 0.42, cy: 0.06, sx: 0.20, sy: 0.10, radius: 0.05, closure: 0,
         smile: 1, smileBow: 0.18, smileThickness: 0.07 },
    BL: { cx: -0.42, cy: 0.42, halfLen: 0.18, thickness: 0.04, tilt: -0.10, visible: 1, peak: 0 },
    BR: { cx: 0.42, cy: 0.42, halfLen: 0.18, thickness: 0.04, tilt: 0.10, visible: 1, peak: 0 },
    M: { cx: 0, cy: -0.38, halfWidth: 0.26, bow: 0.16, thickness: 0.07, openness: 0 },
  },
  fun: {
    L: { cx: -0.42, cy: 0.06, sx: 0.18, sy: 0.24, radius: 0.12, closure: 0, ...NO_SMILE },
    R: { cx: 0.42, cy: 0.06, sx: 0.18, sy: 0.24, radius: 0.12, closure: 0, ...NO_SMILE },
    BL: { cx: -0.42, cy: 0.46, halfLen: 0.20, thickness: 0.04, tilt: -0.16, visible: 1, peak: 0 },
    BR: { cx: 0.42, cy: 0.46, halfLen: 0.20, thickness: 0.04, tilt: 0.16, visible: 1, peak: 0 },
    M: { cx: 0, cy: -0.38, halfWidth: 0.16, bow: 0.10, thickness: 0.06, openness: 0.7 },
  },
  interest: {
    L: { cx: -0.34, cy: 0.08, sx: 0.14, sy: 0.22, radius: 0.08, closure: 0, ...NO_SMILE },
    R: { cx: 0.34, cy: 0.08, sx: 0.14, sy: 0.22, radius: 0.08, closure: 0, ...NO_SMILE },
    BL: { cx: -0.34, cy: 0.44, halfLen: 0.16, thickness: 0.04, tilt: -0.06, visible: 1, peak: 0 },
    BR: { cx: 0.34, cy: 0.44, halfLen: 0.16, thickness: 0.04, tilt: 0.06, visible: 1, peak: 0 },
    M: { cx: 0, cy: -0.40, halfWidth: 0.10, bow: 0.02, thickness: 0.05, openness: 0 },
  },
  bored: {
    L: { cx: -0.42, cy: 0.06, sx: 0.16, sy: 0.20, radius: 0.10, closure: 0.55, ...NO_SMILE },
    R: { cx: 0.42, cy: 0.06, sx: 0.16, sy: 0.20, radius: 0.10, closure: 0.55, ...NO_SMILE },
    BL: { cx: -0.42, cy: 0.36, halfLen: 0.18, thickness: 0.04, tilt: 0.04, visible: 1, peak: 0 },
    BR: { cx: 0.42, cy: 0.36, halfLen: 0.18, thickness: 0.04, tilt: -0.04, visible: 1, peak: 0 },
    M: { cx: 0, cy: -0.40, halfWidth: 0.16, bow: 0, thickness: 0.05, openness: 0 },
  },
  sad: {
    L: { cx: -0.42, cy: 0.04, sx: 0.16, sy: 0.20, radius: 0.10, closure: 0, ...NO_SMILE },
    R: { cx: 0.42, cy: 0.04, sx: 0.16, sy: 0.20, radius: 0.10, closure: 0, ...NO_SMILE },
    // 슬픔: 안쪽 눈썹이 위로 올라가 ⌒ 모양 (걱정·간청).
    BL: { cx: -0.42, cy: 0.38, halfLen: 0.18, thickness: 0.04, tilt: 0.24, visible: 1, peak: 0 },
    BR: { cx: 0.42, cy: 0.38, halfLen: 0.18, thickness: 0.04, tilt: -0.24, visible: 1, peak: 0 },
    M: { cx: 0, cy: -0.38, halfWidth: 0.20, bow: -0.10, thickness: 0.06, openness: 0 },
  },
  angry: {
    L: { cx: -0.42, cy: 0.06, sx: 0.16, sy: 0.18, radius: 0.10, closure: 0, ...NO_SMILE },
    R: { cx: 0.42, cy: 0.06, sx: 0.16, sy: 0.18, radius: 0.10, closure: 0, ...NO_SMILE },
    // 분노: 안쪽 눈썹이 아래로 내려와 ╲╱ 모양 (찌푸린 미간).
    BL: { cx: -0.42, cy: 0.36, halfLen: 0.20, thickness: 0.05, tilt: -0.30, visible: 1, peak: 0 },
    BR: { cx: 0.42, cy: 0.36, halfLen: 0.20, thickness: 0.05, tilt: 0.30, visible: 1, peak: 0 },
    M: { cx: 0, cy: -0.38, halfWidth: 0.18, bow: -0.06, thickness: 0.06, openness: 0 },
  },
  sleep: {
    L: { cx: -0.42, cy: 0.06, sx: 0.26, sy: 0.20, radius: 0.10, closure: 0.92, ...NO_SMILE },
    R: { cx: 0.42, cy: 0.06, sx: 0.26, sy: 0.20, radius: 0.10, closure: 0.92, ...NO_SMILE },
    BL: { cx: -0.42, cy: 0.40, halfLen: 0.16, thickness: 0.03, tilt: 0, visible: 0, peak: 0 },
    BR: { cx: 0.42, cy: 0.40, halfLen: 0.16, thickness: 0.03, tilt: 0, visible: 0, peak: 0 },
    M: { cx: 0, cy: -0.40, halfWidth: 0.10, bow: 0.04, thickness: 0.04, openness: 0 },
  },
};

const VERTEX_SHADER = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = vec4(position.xy, 0.0, 1.0);
}
`;

const FRAGMENT_SHADER = /* glsl */ `
precision highp float;

varying vec2 vUv;
uniform float uTime;
uniform float uAspect;
uniform float uBlink;
uniform vec3 uAccent;

uniform vec2 uLEyeCenter;  uniform vec2 uLEyeSize;  uniform float uLEyeRadius;  uniform float uLEyeClosure;
uniform float uLEyeSmile;  uniform float uLEyeSmileBow;  uniform float uLEyeSmileThickness;
uniform vec2 uREyeCenter;  uniform vec2 uREyeSize;  uniform float uREyeRadius;  uniform float uREyeClosure;
uniform float uREyeSmile;  uniform float uREyeSmileBow;  uniform float uREyeSmileThickness;

uniform vec2 uLBrowCenter; uniform float uLBrowHalfLen; uniform float uLBrowThickness; uniform float uLBrowTilt; uniform float uLBrowVisible; uniform float uLBrowPeak;
uniform vec2 uRBrowCenter; uniform float uRBrowHalfLen; uniform float uRBrowThickness; uniform float uRBrowTilt; uniform float uRBrowVisible; uniform float uRBrowPeak;

uniform vec2 uMouthCenter; uniform float uMouthHalfWidth; uniform float uMouthBow; uniform float uMouthThickness; uniform float uMouthOpenness;

uniform vec2 uHandSize;
uniform vec2 uHand1Center;
uniform vec2 uHand2Center;
uniform float uHand1Tilt;
uniform float uHand2Tilt;
uniform float uHandsActive;

float sdRoundBox(vec2 p, vec2 b, float r) {
  vec2 q = abs(p) - b + r;
  return min(max(q.x, q.y), 0.0) + length(max(q, 0.0)) - r;
}

// 양수 tilt → 형상이 화면에서 CCW 회전 (왼쪽 눈썹의 +tilt → 안쪽 끝 UP)
mat2 rot(float t) {
  float c = cos(t), s = sin(t);
  return mat2(c, -s, s, c);
}

// ^ 모양 chevron SDF — 두 선분 (±halfWidth, 0) → (0, bow) 가 만난다.
// 활(arc) 대신 직선 세그먼트라서 아래쪽 평평한 cutoff 가 없고 capsule 끝이 자연스럽다.
float eyeSmileArcSDF(vec2 q, float halfWidth, float bow, float thickness) {
  vec2 p = vec2(abs(q.x), q.y);
  vec2 a = vec2(0.0, max(bow, 0.0001));
  vec2 b = vec2(halfWidth, 0.0);
  vec2 ab = b - a;
  vec2 ap = p - a;
  float t = clamp(dot(ap, ab) / dot(ab, ab), 0.0, 1.0);
  vec2 closest = a + t * ab;
  return length(p - closest) - thickness * 0.5;
}

float eyeSDF(vec2 p, vec2 center, vec2 size, float radius, float closure,
             float smile, float smileBow, float smileThickness) {
  vec2 q = p - center;
  // closure: 0=open, 1=fully closed → height 압축
  float blinkScale = max(1.0 - uBlink, 0.0);
  float closureScale = max(1.0 - closure, 0.0);
  float scaleY = max(blinkScale * closureScale, 0.005);
  vec2 sz = vec2(size.x, size.y * scaleY);
  float r = min(radius, min(sz.x, sz.y) * 0.95);
  float dBox = sdRoundBox(q, sz, r);

  if (smile > 0.001) {
    float dArc = eyeSmileArcSDF(q, size.x, smileBow * blinkScale, smileThickness * blinkScale);
    return mix(dBox, dArc, clamp(smile, 0.0, 1.0));
  }
  return dBox;
}

float browSDF(vec2 p, vec2 center, float halfLen, float thickness, float tilt, float peak) {
  vec2 q = p - center;
  q = rot(tilt) * q;
  vec2 b = vec2(halfLen, thickness * 0.5);
  float dBox = sdRoundBox(q, b, thickness * 0.5);
  if (peak > 0.001) {
    // ^ 모양 — 위로 굽은 활. peak 가 크면 뾰족함이 강해짐
    float bow = peak * 0.07;
    float dArc = eyeSmileArcSDF(q, halfLen, bow, thickness);
    return mix(dBox, dArc, clamp(peak, 0.0, 1.0));
  }
  return dBox;
}

float mouthCurveSDF(vec2 q, float halfWidth, float bow, float thickness) {
  if (abs(bow) < 0.0015) {
    // 평평한 캡슐
    float dx = max(abs(q.x) - halfWidth, 0.0);
    return length(vec2(dx, q.y)) - thickness * 0.5;
  }
  // 곡선 입: 양수 bow=웃음(peak 아래), 음수 bow=찡그림(peak 위)
  float absBow = abs(bow);
  float R = (halfWidth * halfWidth + absBow * absBow) / (2.0 * absBow);
  float ccy = sign(bow) * (R - absBow);
  vec2 cc = vec2(0.0, ccy);
  float dRing = abs(length(q - cc) - R) - thickness * 0.5;
  float dWidth = abs(q.x) - halfWidth;
  float dWrong = sign(bow) * q.y;
  return max(max(dRing, dWidth), dWrong);
}

float mouthEllipseSDF(vec2 q, float halfWidth, float thickness, float openness) {
  // 타원 ○ — openness 가 클수록 세로로 길어진다
  vec2 ellSize = vec2(halfWidth * 0.55, thickness + halfWidth * 0.55 * openness);
  float k = length(q / ellSize) - 1.0;
  return k * min(ellSize.x, ellSize.y);
}

float mouthSDF(vec2 p, vec2 center, float halfWidth, float bow, float thickness, float openness) {
  vec2 q = p - center;
  float dCurve = mouthCurveSDF(q, halfWidth, bow, thickness);
  float dEllipse = mouthEllipseSDF(q, halfWidth, thickness, openness);
  // openness 0 → 곡선, 1 → 타원 으로 부드럽게 보간
  return mix(dCurve, dEllipse, clamp(openness, 0.0, 1.0));
}

void main() {
  vec2 uv = vUv * 2.0 - 1.0;
  uv.x *= uAspect;

  // Idle micro-saccade
  vec2 saccade = vec2(sin(uTime * 0.31) * 0.008, sin(uTime * 0.23) * 0.005);
  uv -= saccade;

  // 모든 형상의 거리장을 union (min)
  float dEye = min(
    eyeSDF(uv, uLEyeCenter, uLEyeSize, uLEyeRadius, uLEyeClosure,
           uLEyeSmile, uLEyeSmileBow, uLEyeSmileThickness),
    eyeSDF(uv, uREyeCenter, uREyeSize, uREyeRadius, uREyeClosure,
           uREyeSmile, uREyeSmileBow, uREyeSmileThickness)
  );

  float dBrow = 1e9;
  if (uLBrowVisible > 0.001) {
    dBrow = min(dBrow, browSDF(uv, uLBrowCenter, uLBrowHalfLen, uLBrowThickness, uLBrowTilt, uLBrowPeak));
  }
  if (uRBrowVisible > 0.001) {
    dBrow = min(dBrow, browSDF(uv, uRBrowCenter, uRBrowHalfLen, uRBrowThickness, uRBrowTilt, uRBrowPeak));
  }

  float dMouth = mouthSDF(uv, uMouthCenter, uMouthHalfWidth, uMouthBow, uMouthThickness, uMouthOpenness);

  float d = min(min(dEye, dBrow), dMouth);

  // hello 일 때만 활성화되는 두 작대기 (양손) — \ ↔ / 회전
  if (uHandsActive > 0.5) {
    // 손목(작대기 아래쪽 끝) 을 회전축으로 → 자연스러운 흔들기
    vec2 pivot1 = uHand1Center - vec2(0.0, uHandSize.y);
    vec2 q1 = rot(uHand1Tilt) * (uv - pivot1) - vec2(0.0, uHandSize.y);
    float dHand1 = sdRoundBox(q1, uHandSize, min(uHandSize.x, uHandSize.y) * 0.6);

    vec2 pivot2 = uHand2Center - vec2(0.0, uHandSize.y);
    vec2 q2 = rot(uHand2Tilt) * (uv - pivot2) - vec2(0.0, uHandSize.y);
    float dHand2 = sdRoundBox(q2, uHandSize, min(uHandSize.x, uHandSize.y) * 0.6);

    d = min(d, min(dHand1, dHand2));
  }

  float aa = max(fwidth(d) * 1.2, 0.002);
  float mask = 1.0 - smoothstep(-aa, aa, d);

  // 안쪽 살짝 밝게 — OLED 발광 느낌
  float innerGlow = smoothstep(0.04, -0.04, d);
  vec3 col = uAccent * (0.92 + 0.42 * innerGlow);

  // 바깥 헤일로
  float halo = exp(-max(d, 0.0) * 16.0);
  float outA = mask + (1.0 - mask) * halo * 0.30;

  gl_FragColor = vec4(col, outA);
}
`;

const canvasRef = ref<HTMLCanvasElement | null>(null);

let renderer: THREE.WebGLRenderer | null = null;
let scene: THREE.Scene | null = null;
let camera: THREE.OrthographicCamera | null = null;
let material: THREE.ShaderMaterial | null = null;
let geometry: THREE.PlaneGeometry | null = null;
let mesh: THREE.Mesh | null = null;
let resizeObserver: ResizeObserver | null = null;
let raf = 0;

let displayed: FacePreset = clonePreset(PRESETS[props.emotion]);
let source: FacePreset = clonePreset(displayed);
let target: FacePreset = clonePreset(displayed);
let tweenStart = 0;
const TWEEN_DURATION = 320;

let nextBlinkAt = performance.now() + 2400 + Math.random() * 2400;
let blinkStart = 0;
const BLINK_DURATION = 130;

function clonePreset(p: FacePreset): FacePreset {
  return {
    L: { ...p.L },
    R: { ...p.R },
    BL: { ...p.BL },
    BR: { ...p.BR },
    M: { ...p.M },
  };
}
function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}
function lerpEye(a: EyeP, b: EyeP, t: number): EyeP {
  return {
    cx: lerp(a.cx, b.cx, t),
    cy: lerp(a.cy, b.cy, t),
    sx: lerp(a.sx, b.sx, t),
    sy: lerp(a.sy, b.sy, t),
    radius: lerp(a.radius, b.radius, t),
    closure: lerp(a.closure, b.closure, t),
    smile: lerp(a.smile, b.smile, t),
    smileBow: lerp(a.smileBow, b.smileBow, t),
    smileThickness: lerp(a.smileThickness, b.smileThickness, t),
  };
}
function lerpBrow(a: BrowP, b: BrowP, t: number): BrowP {
  return {
    cx: lerp(a.cx, b.cx, t),
    cy: lerp(a.cy, b.cy, t),
    halfLen: lerp(a.halfLen, b.halfLen, t),
    thickness: lerp(a.thickness, b.thickness, t),
    tilt: lerp(a.tilt, b.tilt, t),
    visible: lerp(a.visible, b.visible, t),
    peak: lerp(a.peak, b.peak, t),
  };
}
function lerpMouth(a: MouthP, b: MouthP, t: number): MouthP {
  return {
    cx: lerp(a.cx, b.cx, t),
    cy: lerp(a.cy, b.cy, t),
    halfWidth: lerp(a.halfWidth, b.halfWidth, t),
    bow: lerp(a.bow, b.bow, t),
    thickness: lerp(a.thickness, b.thickness, t),
    openness: lerp(a.openness, b.openness, t),
  };
}
function easeInOut(t: number): number {
  return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
}
function hexToRgb(hex: string): [number, number, number] {
  const v = hex.replace('#', '');
  const full = v.length === 3 ? v.split('').map((c) => c + c).join('') : v;
  const n = parseInt(full, 16);
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
}

function applyEyeUniforms(prefix: 'L' | 'R', e: EyeP): void {
  if (!material) return;
  const u = material.uniforms;
  (u[`u${prefix}EyeCenter`].value as THREE.Vector2).set(e.cx, e.cy);
  (u[`u${prefix}EyeSize`].value as THREE.Vector2).set(e.sx, e.sy);
  u[`u${prefix}EyeRadius`].value = e.radius;
  u[`u${prefix}EyeClosure`].value = e.closure;
  u[`u${prefix}EyeSmile`].value = e.smile;
  u[`u${prefix}EyeSmileBow`].value = e.smileBow;
  u[`u${prefix}EyeSmileThickness`].value = e.smileThickness;
}
function applyBrowUniforms(prefix: 'L' | 'R', b: BrowP): void {
  if (!material) return;
  const u = material.uniforms;
  (u[`u${prefix}BrowCenter`].value as THREE.Vector2).set(b.cx, b.cy);
  u[`u${prefix}BrowHalfLen`].value = b.halfLen;
  u[`u${prefix}BrowThickness`].value = b.thickness;
  u[`u${prefix}BrowTilt`].value = b.tilt;
  u[`u${prefix}BrowVisible`].value = b.visible;
  u[`u${prefix}BrowPeak`].value = b.peak;
}
function applyMouthUniforms(m: MouthP): void {
  if (!material) return;
  const u = material.uniforms;
  (u.uMouthCenter.value as THREE.Vector2).set(m.cx, m.cy);
  u.uMouthHalfWidth.value = m.halfWidth;
  u.uMouthBow.value = m.bow;
  u.uMouthThickness.value = m.thickness;
  u.uMouthOpenness.value = m.openness;
}

function setupRenderer(canvas: HTMLCanvasElement): void {
  renderer = new THREE.WebGLRenderer({
    canvas,
    alpha: true,
    antialias: true,
    premultipliedAlpha: true,
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setClearColor(0x000000, 0);

  scene = new THREE.Scene();
  camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);

  const [r, g, b] = hexToRgb(props.accent);
  material = new THREE.ShaderMaterial({
    vertexShader: VERTEX_SHADER,
    fragmentShader: FRAGMENT_SHADER,
    transparent: true,
    uniforms: {
      uTime: { value: 0 },
      uAspect: { value: 1 },
      uBlink: { value: 0 },
      uAccent: { value: new THREE.Vector3(r, g, b) },

      uLEyeCenter: { value: new THREE.Vector2() },
      uLEyeSize: { value: new THREE.Vector2() },
      uLEyeRadius: { value: 0 },
      uLEyeClosure: { value: 0 },
      uLEyeSmile: { value: 0 },
      uLEyeSmileBow: { value: 0 },
      uLEyeSmileThickness: { value: 0 },
      uREyeCenter: { value: new THREE.Vector2() },
      uREyeSize: { value: new THREE.Vector2() },
      uREyeRadius: { value: 0 },
      uREyeClosure: { value: 0 },
      uREyeSmile: { value: 0 },
      uREyeSmileBow: { value: 0 },
      uREyeSmileThickness: { value: 0 },

      uLBrowCenter: { value: new THREE.Vector2() },
      uLBrowHalfLen: { value: 0 },
      uLBrowThickness: { value: 0 },
      uLBrowTilt: { value: 0 },
      uLBrowVisible: { value: 1 },
      uLBrowPeak: { value: 0 },
      uRBrowCenter: { value: new THREE.Vector2() },
      uRBrowHalfLen: { value: 0 },
      uRBrowThickness: { value: 0 },
      uRBrowTilt: { value: 0 },
      uRBrowVisible: { value: 1 },
      uRBrowPeak: { value: 0 },

      uMouthCenter: { value: new THREE.Vector2() },
      uMouthHalfWidth: { value: 0 },
      uMouthBow: { value: 0 },
      uMouthThickness: { value: 0 },
      uMouthOpenness: { value: 0 },

      uHandSize: { value: new THREE.Vector2(0.04, 0.20) },
      uHand1Center: { value: new THREE.Vector2() },
      uHand2Center: { value: new THREE.Vector2() },
      uHand1Tilt: { value: 0 },
      uHand2Tilt: { value: 0 },
      uHandsActive: { value: 0 },
    },
  });

  geometry = new THREE.PlaneGeometry(2, 2);
  mesh = new THREE.Mesh(geometry, material);
  scene.add(mesh);
}

function resize(): void {
  if (!renderer || !material || !canvasRef.value) return;
  const parent = canvasRef.value.parentElement;
  if (!parent) return;
  const w = parent.clientWidth;
  const h = parent.clientHeight;
  if (w === 0 || h === 0) return;
  renderer.setSize(w, h, false);
  material.uniforms.uAspect.value = w / h;
}

function tick(): void {
  if (!renderer || !scene || !camera || !material) return;
  const now = performance.now();

  // Emotion 트윈
  const tRaw = Math.min(1, (now - tweenStart) / TWEEN_DURATION);
  const t = easeInOut(tRaw);
  displayed = {
    L: lerpEye(source.L, target.L, t),
    R: lerpEye(source.R, target.R, t),
    BL: lerpBrow(source.BL, target.BL, t),
    BR: lerpBrow(source.BR, target.BR, t),
    M: lerpMouth(source.M, target.M, t),
  };

  // Blink — sleep 일 때는 항상 닫힘으로 처리하므로 별도 깜빡임 없음
  let blink = 0;
  if (props.emotion === 'sleep') {
    blink = 0;
  } else {
    if (blinkStart === 0 && now >= nextBlinkAt) {
      blinkStart = now;
      nextBlinkAt = now + 2400 + Math.random() * 3200;
    }
    if (blinkStart > 0) {
      const bt = (now - blinkStart) / BLINK_DURATION;
      if (bt >= 1) {
        blinkStart = 0;
        blink = 0;
      } else {
        blink = bt < 0.5 ? bt * 2 : (1 - bt) * 2;
      }
    }
  }

  // 표정별 idle 모션
  let handsActive = 0;
  let hand1Tilt = 0;
  let hand2Tilt = 0;
  if (props.emotion === 'hello') {
    // 입: 작은 o ↔ 큰 O 천천히 (1.8s 주기)
    const mouthPhase = ((now / 1800) % 1) * Math.PI * 2;
    const mt = (1 - Math.cos(mouthPhase)) * 0.5;
    displayed.M = {
      ...displayed.M,
      openness: 1,
      thickness: 0,
      halfWidth: lerp(0.06, 0.16, mt),
    };
    // 양손 작대기: \ ↔ / 좌우 흔들기 (0.55s 주기, ±45°)
    // 두 손이 거울 대칭으로 움직이도록 부호 반대 — 양손을 안팎으로 펼치는 인사 동작
    handsActive = 1;
    const handPhase = ((now / 550) % 1) * Math.PI * 2;
    const swing = Math.sin(handPhase) * (Math.PI / 4);
    hand1Tilt = swing;
    hand2Tilt = -swing;
  }

  material.uniforms.uTime.value = now / 1000;
  material.uniforms.uBlink.value = blink;

  applyEyeUniforms('L', displayed.L);
  applyEyeUniforms('R', displayed.R);
  applyBrowUniforms('L', displayed.BL);
  applyBrowUniforms('R', displayed.BR);
  applyMouthUniforms(displayed.M);

  material.uniforms.uHandsActive.value = handsActive;
  (material.uniforms.uHand1Center.value as THREE.Vector2).set(-1.05, -0.55);
  (material.uniforms.uHand2Center.value as THREE.Vector2).set(1.05, -0.55);
  material.uniforms.uHand1Tilt.value = hand1Tilt;
  material.uniforms.uHand2Tilt.value = hand2Tilt;

  const [r, g, b] = hexToRgb(props.accent);
  (material.uniforms.uAccent.value as THREE.Vector3).set(r, g, b);

  renderer.render(scene, camera);
  raf = requestAnimationFrame(tick);
}

watch(
  () => props.emotion,
  (next) => {
    source = clonePreset(displayed);
    target = clonePreset(PRESETS[next]);
    tweenStart = performance.now();
  }
);

onMounted(() => {
  if (!canvasRef.value) return;
  setupRenderer(canvasRef.value);
  resize();
  resizeObserver = new ResizeObserver(() => resize());
  if (canvasRef.value.parentElement) {
    resizeObserver.observe(canvasRef.value.parentElement);
  }
  raf = requestAnimationFrame(tick);
});

onBeforeUnmount(() => {
  cancelAnimationFrame(raf);
  resizeObserver?.disconnect();
  resizeObserver = null;
  geometry?.dispose();
  material?.dispose();
  renderer?.dispose();
  renderer = null;
  scene = null;
  camera = null;
  material = null;
  geometry = null;
  mesh = null;
});
</script>

<template>
  <canvas ref="canvasRef" class="shader-face" />
</template>

<style scoped>
.shader-face {
  display: block;
  width: 100%;
  height: 100%;
}
</style>
