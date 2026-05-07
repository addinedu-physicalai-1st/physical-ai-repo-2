<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import * as THREE from 'three';
import { useVoiceStore } from '@/stores/voice';
import type { EmotionId } from '@/config/robots';

const props = defineProps<{ 
  emotion: EmotionId; 
  accent: string;
  thinking?: boolean;
  speaking?: boolean;
}>();

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
    L: { cx: -0.42, cy: 0.06, sx: 0.16, sy: 0.22, radius: 0.10, closure: 0, ...NO_SMILE },
    R: { cx: 0.42, cy: 0.06, sx: 0.16, sy: 0.22, radius: 0.10, closure: 0, ...NO_SMILE },
    BL: { cx: -0.42, cy: 0.44, halfLen: 0.18, thickness: 0.04, tilt: 0, visible: 1, peak: 1 },
    BR: { cx: 0.42, cy: 0.44, halfLen: 0.18, thickness: 0.04, tilt: 0, visible: 1, peak: 1 },
    M: { cx: 0, cy: -0.40, halfWidth: 0.16, bow: 0, thickness: 0.05, openness: 0 },
  },
  happy: {
    L: { cx: -0.42, cy: 0.06, sx: 0.20, sy: 0.10, radius: 0.05, closure: 0, smile: 1, smileBow: 0.18, smileThickness: 0.07 },
    R: { cx: 0.42, cy: 0.06, sx: 0.20, sy: 0.10, radius: 0.05, closure: 0, smile: 1, smileBow: 0.18, smileThickness: 0.07 },
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
    L: { cx: -0.42, cy: 0.06, sx: 0.14, sy: 0.22, radius: 0.08, closure: 0, ...NO_SMILE },
    R: { cx: 0.42, cy: 0.06, sx: 0.14, sy: 0.22, radius: 0.08, closure: 0, ...NO_SMILE },
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
    L: { cx: -0.42, cy: 0.06, sx: 0.16, sy: 0.20, radius: 0.10, closure: 0, ...NO_SMILE },
    R: { cx: 0.42, cy: 0.06, sx: 0.16, sy: 0.20, radius: 0.10, closure: 0, ...NO_SMILE },
    BL: { cx: -0.42, cy: 0.38, halfLen: 0.18, thickness: 0.04, tilt: 0.24, visible: 1, peak: 0 },
    BR: { cx: 0.42, cy: 0.38, halfLen: 0.18, thickness: 0.04, tilt: -0.24, visible: 1, peak: 0 },
    M: { cx: 0, cy: -0.38, halfWidth: 0.20, bow: -0.10, thickness: 0.06, openness: 0 },
  },
  angry: {
    L: { cx: -0.42, cy: 0.06, sx: 0.16, sy: 0.18, radius: 0.10, closure: 0, ...NO_SMILE },
    R: { cx: 0.42, cy: 0.06, sx: 0.16, sy: 0.18, radius: 0.10, closure: 0, ...NO_SMILE },
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
uniform float uCheeks;
uniform vec3 uCheeksColor;

float sdCircle(vec2 p, float r) {
  return length(p) - r;
}

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
  // Clamp x to avoid parabola extending to infinity and causing spooky glow streaks
  float px = clamp(q.x, -halfWidth, halfWidth);
  
  // Parabola bend to match the smile/frown curve
  // when x = 0, shift = -bow. when x = halfWidth, shift = 0
  float parabola = -bow + (bow / max(halfWidth * halfWidth, 0.0001)) * (px * px);
  
  float openY = max(openness, 0.0);
  
  // Simulate lower jaw dropping when mouth opens widely
  float jawDrop = halfWidth * 0.2 * openY; 
  
  // Apply bend and drop to local space
  vec2 qBend = vec2(q.x, q.y - parabola + jawDrop);
  
  // The open mouth uses a mathematically exact rounded box in bent space
  float r = thickness * 0.5 + openY * halfWidth * 0.3; 
  float totalWidth = halfWidth * 0.95;
  float bx = max(totalWidth - r, 0.0);
  float totalHeight = thickness * 0.5 + openY * halfWidth * 0.4;
  float by = max(totalHeight - r, 0.0);
  
  vec2 d_box = abs(qBend) - vec2(bx, by);
  return length(max(d_box, 0.0)) + min(max(d_box.x, d_box.y), 0.0) - r;
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
  vec3 color = uAccent * (0.92 + 0.42 * innerGlow);

  // 바깥 헤일로
  float halo = exp(-max(d, 0.0) * 16.0);
  float outA = mask + (1.0 - mask) * halo * 0.30;

  // --- CHEEKS (Blush) ---
  // Position them significantly below and slightly outward from the eyes
  float cheekL = sdCircle(uv - (uLEyeCenter + vec2(-0.30, -0.42)), 0.18);
  float cheekR = sdCircle(uv - (uREyeCenter + vec2(0.30, -0.42)), 0.18);
  float cheekD = min(cheekL, cheekR);
  
  // Stronger exponential glow for cheeks (softer falloff = bigger appearance)
  float cheekGlow = exp(-max(cheekD, 0.0) * 8.0) * uCheeks;
  
  // High-visibility alpha punch-through for black backgrounds
  outA = max(outA, cheekGlow * 0.85);
  
  // Vibrant blush color blending
  color = mix(color, uCheeksColor, cheekGlow * 1.0);

  gl_FragColor = vec4(color, outA);
}
`;

const canvasRef = ref<HTMLCanvasElement | null>(null);

let renderer: THREE.WebGLRenderer | null = null;
let scene: THREE.Scene | null = null;
let camera: THREE.OrthographicCamera | null = null;
let material: THREE.ShaderMaterial | null = null;
const voiceStore = useVoiceStore();

// Korean Sub-syllable Phonetic Decomposition for Realistic Lip Sync
function getVisemeForSyllable(char: string, t_ms: number) {
  if (!char) return null;
  const code = char.charCodeAt(0);
  
  // Hangul Syllables: AC00–D7A3
  if (code < 0xAC00 || code > 0xD7A3) {
    if (char.trim() === '') return null;
    // Generic bounce for non-Korean chars
    const bounce = t_ms < 75 ? 0.8 : 0.4;
    return { openness: bounce, width: 0.9, bowOffset: 0.0 };
  }
  
  const index = code - 0xAC00;
  const onsetIdx = Math.floor(index / 588);
  const vowelIdx = Math.floor((index % 588) / 28);
  const codaIdx = index % 28;
  
  // Identify bilabials (ㅁ, ㅂ, ㅃ, ㅍ) which require lips to completely close
  const isBilabialOnset = [6, 7, 8, 17].includes(onsetIdx); 
  const isBilabialCoda = [16, 17, 10, 11, 14, 26, 18].includes(codaIdx);

  // Base Vowel Viseme
  let vOpenness = 0.6;
  let vWidth = 1.0;
  let vBow = 0.0;
  
  if ([0, 1, 2, 3].includes(vowelIdx)) { vOpenness = 1.1; vWidth = 1.05; vBow = -0.05; } // ㅏ (Ah)
  else if ([4, 5, 6, 7].includes(vowelIdx)) { vOpenness = 0.8; vWidth = 0.95; vBow = 0.0; } // ㅓ (Eo)
  else if ([8, 9, 10, 11, 12].includes(vowelIdx)) { vOpenness = 0.65; vWidth = 0.5; vBow = 0.1; } // ㅗ (Oh)
  else if ([13, 14, 15, 16, 17].includes(vowelIdx)) { vOpenness = 0.4; vWidth = 0.35; vBow = 0.15; } // ㅜ (U)
  else if ([18, 19].includes(vowelIdx)) { vOpenness = 0.2; vWidth = 1.25; vBow = 0.0; } // ㅡ (Eu)
  else if (vowelIdx === 20) { vOpenness = 0.3; vWidth = 1.4; vBow = 0.05; } // ㅣ (E/I)

  let openness = vOpenness;
  let width = vWidth;
  let bow = vBow;

  // Syllable Timing (assuming ~220ms per syllable block from TTS)
  if (t_ms < 50) {
    // 1. Onset Phase
    if (isBilabialOnset) {
      openness = 0.0; // Lips closed
      width = 0.8;
    } else {
      openness = vOpenness * 0.3; // Slight prep opening
      width = vWidth * 0.9;
    }
  } else if (t_ms < 150) {
    // 2. Nucleus (Vowel) Phase
    openness = vOpenness;
    width = vWidth;
  } else {
    // 3. Coda Phase
    if (isBilabialCoda) {
      openness = 0.0; // Lips closed
      width = 0.8;
    } else if (codaIdx === 0) {
      openness = vOpenness * 0.7; // Fade out slightly
    } else {
      openness = vOpenness * 0.4; // Tongue moves, jaw partially closes
    }
  }
  
  return { openness, width, bowOffset: bow };
}

const visemeTarget = ref({ openness: 0, width: 1, bowOffset: 0 });
let currentViseme = { openness: 0, width: 1, bowOffset: 0 };
let speechWeight = 0;
let lastSpokenChar = '';
let charStartTime = 0;
let speakingStartTime = 0;
let wasSpeaking = false;

let geometry: THREE.PlaneGeometry | null = null;
let mesh: THREE.Mesh | null = null;
let resizeObserver: ResizeObserver | null = null;
let raf = 0;
const isThinkingActive = ref(!!props.thinking);
watch(() => props.thinking, (val) => {
  isThinkingActive.value = !!val;
});

let displayed: FacePreset = clonePreset(PRESETS[props.emotion]);
let source: FacePreset = clonePreset(displayed);
let target: FacePreset = clonePreset(displayed);
let tweenStart = 0;
let displayedCheeks = 0;
let targetCheeks = 0;
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
      uMouthCenter: { value: new THREE.Vector2() },
      uMouthHalfWidth: { value: 0 },
      uMouthBow: { value: 0 },
      uMouthThickness: { value: 0 },
      uMouthOpenness: { value: 0 },

      uHandSize: { value: new THREE.Vector2(0.06, 0.35) },
      uHand1Center: { value: new THREE.Vector2() },
      uHand2Center: { value: new THREE.Vector2() },
      uHand1Tilt: { value: 0.0 },
      uHand2Tilt: { value: 0.0 },
      uHandsActive: { value: 0.0 },
      uCheeks: { value: 0.0 },
      uCheeksColor: { value: new THREE.Vector3(1, 0.4, 0.5) },

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
  
  // Thinking scanning motion: kill if speaking
  let thinkingX = 0;
  let thinkingY = 0;
  if (isThinkingActive.value && !props.speaking) {
    const time = now / 1000;
    // Look top-left and top-right while thinking (Micro-range, ultra-subtle)
    const scan = Math.sin(time * 2.5); 
    thinkingX = scan * 0.06; // Micro sweep
    thinkingY = 0.08 + Math.abs(scan) * 0.02; // Very low upward drift
  }

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

  // Render-time offset for thinking (does not affect 'displayed' state used for next transition)
  let renderL = { ...displayed.L };
  let renderR = { ...displayed.R };
  
  if (isThinkingActive.value && !props.speaking) {
    // Focused thinking shape: perfect circles (aspect-corrected)
    const thinkingSize = 0.10;
    const sx = thinkingSize * material.uniforms.uAspect.value;
    const sy = thinkingSize;
    const radius = thinkingSize * material.uniforms.uAspect.value; // Large enough to force circle
    
    renderL = { 
      ...renderL, 
      cx: renderL.cx + thinkingX, 
      cy: renderL.cy + thinkingY,
      sx, sy, radius
    };
    renderR = { 
      ...renderR, 
      cx: renderR.cx + thinkingX, 
      cy: renderR.cy + thinkingY,
      sx, sy, radius
    };
  }

  let renderBL = { ...displayed.BL };
  let renderBR = { ...displayed.BR };
  let renderM = { ...displayed.M };
  
  // Speech Chatter & Viseme Sync
  const time = now / 1000;
  
  if (voiceStore.currentChar !== lastSpokenChar) {
    lastSpokenChar = voiceStore.currentChar;
    charStartTime = now;
  }

  let speechWeightTarget = 0.0;
  
  if (props.speaking) {
    let charToUse = voiceStore.currentChar;
    let t_ms = now - charStartTime;

    // Fallback: If TTS events fail to fire (Server-Side TTS or browser bugs), autonomously simulate phonetic timing
    if (!charToUse && voiceStore.robotReply) {
      if (!wasSpeaking) {
        speakingStartTime = now;
      }
      const t_speaking = now - speakingStartTime;
      const charIdx = Math.floor(t_speaking / 220);
      
      if (charIdx < voiceStore.robotReply.length) {
        charToUse = voiceStore.robotReply.charAt(charIdx);
        t_ms = t_speaking % 220;
      } else {
        // Fallback pulse if audio outlasts the text
        charToUse = '아';
        t_ms = t_speaking % 400;
      }
    }

    wasSpeaking = true;

    if (charToUse) {
      const viseme = getVisemeForSyllable(charToUse, t_ms);
      if (viseme) {
        speechWeightTarget = 1.0;
        let openness = viseme.openness;
        // 웃는 표정일 때는 입을 조금 더 크게 벌려 자연스럽게
        if (props.emotion === 'happy') {
          openness *= 1.2;
        }
        visemeTarget.value = { 
          openness: openness, 
          width: viseme.width,
          bowOffset: viseme.bowOffset
        };
      }
    }
  } else {
    wasSpeaking = false;
    speechWeightTarget = 0.0;
  }

  // Decay/Smooth toward target - Much softer alpha for organic, less spazzy movement
  const alpha = 0.18; 
  currentViseme.openness = currentViseme.openness * (1 - alpha) + visemeTarget.value.openness * alpha;
  currentViseme.width = currentViseme.width * (1 - alpha) + visemeTarget.value.width * alpha;
  currentViseme.bowOffset = currentViseme.bowOffset * (1 - alpha) + visemeTarget.value.bowOffset * alpha;
  
  // Independent speech weight allows explicit width/bow changes even for closed phonemes
  const weightAlpha = 0.15;
  speechWeight = speechWeight * (1 - weightAlpha) + speechWeightTarget * weightAlpha;

  // Apply viseme overrides using the independent speech weight
  renderM.openness = lerp(displayed.M.openness, currentViseme.openness, speechWeight);
  renderM.halfWidth = lerp(displayed.M.halfWidth, displayed.M.halfWidth * currentViseme.width, speechWeight);
  renderM.bow = displayed.M.bow + currentViseme.bowOffset * speechWeight;



  // Eyebrow shake when happy/smiling
  if (props.emotion === 'happy') {
    const shake = Math.sin(now / 40) * 0.015;
    renderBL.cy += shake;
    renderBR.cy += shake;
  }

  applyEyeUniforms('L', renderL);
  applyEyeUniforms('R', renderR);
  applyBrowUniforms('L', renderBL);
  applyBrowUniforms('R', renderBR);
  applyMouthUniforms(renderM);

  material.uniforms.uHandsActive.value = handsActive;
  (material.uniforms.uHand1Center.value as THREE.Vector2).set(-1.05, -0.55);
  (material.uniforms.uHand2Center.value as THREE.Vector2).set(1.05, -0.55);
  material.uniforms.uHand1Tilt.value = hand1Tilt;
  material.uniforms.uHand2Tilt.value = hand2Tilt;

  const [r, g, b] = hexToRgb(props.accent);
  (material.uniforms.uAccent.value as THREE.Vector3).set(r, g, b);

  // Cheeks logic: Happy/Fun/Interest/Hello get blush
  const blushingEmotions: EmotionId[] = ['happy', 'fun', 'interest', 'hello'];
  targetCheeks = blushingEmotions.includes(props.emotion) ? 1.0 : 0.0;
  displayedCheeks = lerp(displayedCheeks, targetCheeks, 0.08); // Smooth fade
  // Blush Color: Mix accent color with a soft red/pink for a natural glow
  const accentColor = new THREE.Color(props.accent);
  const blushColor = new THREE.Color(1.0, 0.2, 0.5); // Vibrant Magenta/Pink
  blushColor.lerp(accentColor, 0.1); // Keep 90% pink, 10% accent
  material.uniforms.uCheeksColor.value.set(blushColor.r, blushColor.g, blushColor.b);
  material.uniforms.uCheeks.value = displayedCheeks;

  renderer.render(scene, camera);
  raf = requestAnimationFrame(tick);
}

watch(
  () => props.emotion,
  (next) => {
    source = clonePreset(displayed);
    target = clonePreset(PRESETS[next] || PRESETS.basic);
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
