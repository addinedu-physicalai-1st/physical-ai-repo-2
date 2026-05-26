/**
 * Doctor teleop scene 의 D435 depth point cloud overlay.
 *
 * robot-web/src/eduping/{useDepthStream,useDepthCloudInScene}.ts 를 portal-web 으로
 * 포팅 — MVP 단계라 DRY 위반을 받아들이고 한 파일로 통합. 향후 plan 에서 robot-web
 * 과 공유 모듈로 추출 예정.
 *
 * 와이어 포맷은 service/control-service/control_service/streaming/depth_protocol.py 의
 * encode_depth_frame() 와 1:1 — 60B "DPTH" 헤더 + zstd-compressed uint16 depth + JPEG color.
 *
 * 좌표 변환:
 *   portal-web doctor scene 은 ROS Z-up base_link 기준. URDF (양팔 OpenArm) 가 origin 에.
 *   D435 는 base_link + (0.5, 0, 0.4) 에서 30° 아래로 내려다본다고 가정 — 정확한 값은
 *   TF 가 들어오기 전까지 시각적으로 튜닝.
 *   TODO(plan-2): /tf_static 에서 d435_depth_optical_frame → base_link 받아서 동적 적용.
 *   Group transform 이 광학 frame (Z forward, X right, Y down) → ROS (X forward, Y left,
 *   Z up) 변환 + 30° 아래 pitch 를 한 번에 처리.
 */
import * as THREE from 'three';
import { decompress as zstdDecompress } from 'fzstd';

const PATH = '/ws/depth-stream';
const HEADER_SIZE = 60;
const MAGIC = 0x44505448; // "DPTH" big-endian as uint32

interface DecodedDepthFrame {
  frameSeq: number;
  tsMs: number;
  depthW: number;
  depthH: number;
  colorW: number;
  colorH: number;
  fx: number;
  fy: number;
  cx: number;
  cy: number;
  depthScale: number;
  depthMinMm: number;
  depthMaxMm: number;
  depth: Uint16Array;
  colorBlob: Blob;
}

export interface DepthCloudHandle {
  dispose(): void;
  setVisible(visible: boolean): void;
}

export interface AttachDepthCloudOpts {
  scene: THREE.Scene;
  edupingId: string;
  /** 최대 표시 거리 (m). 기본 3.0. */
  maxDepthM?: number;
  /** 포인트 사이즈 (px). 기본 3.0. */
  pointSize?: number;
  /** 색 모드. 기본 'depth' (jet colormap). */
  colorMode?: 'rgb' | 'depth';
  /**
   * 매 frame 의 D435 RGB ImageBitmap 콜백. PIP 카메라 뷰 같은 곳에서 사용.
   * 콜백 안에서 즉시 drawImage 로 복사 — bitmap 은 직후 texture 에 할당됨.
   */
  onColorBitmap?: (bm: ImageBitmap, width: number, height: number) => void;
}

const VERTEX_SHADER = /* glsl */ `
  uniform usampler2D u_depth;
  uniform sampler2D u_color;
  uniform float u_fx;
  uniform float u_fy;
  uniform float u_cx;
  uniform float u_cy;
  uniform float u_depth_scale;
  uniform vec2 u_size;
  uniform float u_point_size;
  uniform float u_max_depth_m;
  uniform int u_color_mode;
  out vec3 v_color;
  flat out int v_valid;

  vec3 jetColor(float t) {
    t = clamp(t, 0.0, 1.0);
    return vec3(
      clamp(1.5 - abs(4.0 * t - 3.0), 0.0, 1.0),
      clamp(1.5 - abs(4.0 * t - 2.0), 0.0, 1.0),
      clamp(1.5 - abs(4.0 * t - 1.0), 0.0, 1.0)
    );
  }

  void main() {
    vec2 uv = position.xy;
    ivec2 ix = ivec2(uv);
    uint d_raw = texelFetch(u_depth, ix, 0).r;
    float d_m = float(d_raw) * u_depth_scale;

    if (d_raw == 0u || d_m > u_max_depth_m) {
      gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
      gl_PointSize = 0.0;
      v_color = vec3(0.0);
      v_valid = 0;
      return;
    }

    float x = (uv.x - u_cx) * d_m / u_fx;
    float y = (uv.y - u_cy) * d_m / u_fy;
    float z = d_m;

    vec4 modelPos = vec4(x, y, z, 1.0);
    gl_Position = projectionMatrix * modelViewMatrix * modelPos;
    gl_PointSize = u_point_size;

    if (u_color_mode == 1) {
      v_color = jetColor(d_m / u_max_depth_m);
    } else {
      vec2 norm_uv = (uv + 0.5) / u_size;
      v_color = texture(u_color, norm_uv).rgb;
    }
    v_valid = 1;
  }
`;

const FRAGMENT_SHADER = /* glsl */ `
  in vec3 v_color;
  flat in int v_valid;
  out vec4 outColor;
  void main() {
    if (v_valid == 0) discard;
    outColor = vec4(v_color, 1.0);
  }
`;

function decodeFrame(buf: ArrayBuffer): DecodedDepthFrame | null {
  if (buf.byteLength < HEADER_SIZE) return null;
  const dv = new DataView(buf);
  const magic = dv.getUint32(0, false);
  if (magic !== MAGIC) return null;
  const version = dv.getUint8(4);
  if (version !== 1) return null;
  const frameSeq = dv.getUint32(8, false);
  const tsHi = dv.getUint32(12, false);
  const tsLo = dv.getUint32(16, false);
  const tsMs = tsHi * 0x1_0000_0000 + tsLo;
  const depthW = dv.getUint16(20, false);
  const depthH = dv.getUint16(22, false);
  const colorW = dv.getUint16(24, false);
  const colorH = dv.getUint16(26, false);
  const fx = dv.getFloat32(28, false);
  const fy = dv.getFloat32(32, false);
  const cx = dv.getFloat32(36, false);
  const cy = dv.getFloat32(40, false);
  const depthScale = dv.getFloat32(44, false);
  const depthMinMm = dv.getUint16(48, false);
  const depthMaxMm = dv.getUint16(50, false);
  const depthSize = dv.getUint32(52, false);
  const colorSize = dv.getUint32(56, false);

  if (HEADER_SIZE + depthSize + colorSize !== buf.byteLength) return null;

  const depthZstd = new Uint8Array(buf, HEADER_SIZE, depthSize);
  const colorBytes = new Uint8Array(buf, HEADER_SIZE + depthSize, colorSize);

  let depthRaw: Uint8Array;
  try {
    depthRaw = zstdDecompress(depthZstd);
  } catch (e) {
    console.warn('[DepthCloud] zstd decompress failed:', e);
    return null;
  }
  if (depthRaw.byteLength !== depthW * depthH * 2) {
    console.warn(
      `[DepthCloud] depth size mismatch: got ${depthRaw.byteLength}, expected ${depthW * depthH * 2}`,
    );
    return null;
  }
  const depth = new Uint16Array(
    depthRaw.buffer, depthRaw.byteOffset, depthW * depthH,
  );

  const colorBlob = new Blob([colorBytes], { type: 'image/jpeg' });

  return {
    frameSeq, tsMs,
    depthW, depthH, colorW, colorH,
    fx, fy, cx, cy, depthScale,
    depthMinMm, depthMaxMm,
    depth, colorBlob,
  };
}

/**
 * scene 에 D435 depth cloud 를 attach.
 *
 * 내부에 Group 하나를 만들어 광학 frame → base_link 정적 변환을 걸고, 그 자식으로
 * THREE.Points 를 매단다. WS frame 마다 depth/color texture 와 intrinsics uniform 갱신.
 */
export function attachDepthCloud(opts: AttachDepthCloudOpts): DepthCloudHandle {
  const maxDepthM = opts.maxDepthM ?? 3.0;
  const pointSize = opts.pointSize ?? 3.0;
  const colorMode = opts.colorMode ?? 'depth';

  // ── 정적 transform: 광학 frame → base_link ──────────────────────────────
  // base_link 는 ROS Z-up (X forward, Y left, Z up). 광학 frame 은 (X right, Y down,
  // Z forward). 광학 → base_link 회전은 표준 ROS 관례로 rpy=(-π/2, 0, -π/2).
  // 그 위에 30° 아래로 내려다보는 pitch 를 base_link Y 축 (left) 기준으로 추가.
  // TODO(plan-2): /tf_static 에서 d435_depth_optical_frame → base_link 동적 수신.
  const cloudGroup = new THREE.Group();
  cloudGroup.position.set(0.5, 0, 0.4);
  // 광학 → ROS body (camera_link) 회전: rpy(-π/2, 0, -π/2) (extrinsic XYZ).
  const opticalToBody = new THREE.Quaternion().setFromEuler(
    new THREE.Euler(-Math.PI / 2, 0, -Math.PI / 2, 'XYZ'),
  );
  // 30° 아래로 pitch — camera body 기준 Y (left) 축 회전.
  const pitchDown = new THREE.Quaternion().setFromAxisAngle(
    new THREE.Vector3(0, 1, 0), THREE.MathUtils.degToRad(30),
  );
  // base_link → body: pitchDown 만. base_link → optical: pitchDown * opticalToBody.
  cloudGroup.quaternion.copy(pitchDown).multiply(opticalToBody);
  opts.scene.add(cloudGroup);

  // ── WS state ────────────────────────────────────────────────────────────
  const clientId = `depth-${globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2)}`;
  const wsUrl = (() => {
    const loc = (globalThis as { location?: Location }).location;
    if (!loc) return PATH;
    const proto = loc.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${proto}//${loc.host}${PATH}`;
  })();

  let currentWs: WebSocket | null = null;
  let stopped = false;
  let backoffMs = 1000;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  // ── three.js cloud state ────────────────────────────────────────────────
  let points: THREE.Points | null = null;
  let depthTexture: THREE.DataTexture | null = null;
  let depthCopy: Uint16Array | null = null;
  let colorTexture: THREE.Texture | null = null;
  let dims = { w: 0, h: 0 };
  let disposed = false;

  function teardownGeometry(): void {
    if (points) {
      cloudGroup.remove(points);
      points.geometry.dispose();
      (points.material as THREE.Material).dispose();
      points = null;
    }
    if (depthTexture) {
      depthTexture.dispose();
      depthTexture = null;
    }
    if (colorTexture?.image && (colorTexture.image as ImageBitmap).close) {
      try { (colorTexture.image as ImageBitmap).close(); } catch { /* ignore */ }
    }
    colorTexture?.dispose();
    colorTexture = null;
  }

  function ensureGeometry(w: number, h: number): void {
    if (dims.w === w && dims.h === h && points) return;
    teardownGeometry();

    const count = w * h;
    const positions = new Float32Array(count * 3);
    let idx = 0;
    for (let v = 0; v < h; v++) {
      for (let u = 0; u < w; u++) {
        positions[idx++] = u;
        positions[idx++] = v;
        positions[idx++] = 0;
      }
    }
    const geom = new THREE.BufferGeometry();
    geom.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    // 모든 vertex 가 셰이더에서 광학 → 3D 변환된 뒤 그려지므로 frustum culling 비활성.
    geom.boundingSphere = new THREE.Sphere(new THREE.Vector3(0, 0, 0), 100);

    const blank = new Uint16Array(w * h);
    depthTexture = new THREE.DataTexture(
      blank, w, h,
      THREE.RedIntegerFormat, THREE.UnsignedShortType,
    );
    depthTexture.internalFormat = 'R16UI';
    depthTexture.magFilter = THREE.NearestFilter;
    depthTexture.minFilter = THREE.NearestFilter;
    depthTexture.needsUpdate = true;

    colorTexture = new THREE.Texture();
    colorTexture.minFilter = THREE.LinearFilter;
    colorTexture.magFilter = THREE.LinearFilter;
    colorTexture.colorSpace = THREE.NoColorSpace;

    const material = new THREE.ShaderMaterial({
      glslVersion: THREE.GLSL3,
      uniforms: {
        u_depth: { value: depthTexture },
        u_color: { value: colorTexture },
        u_fx: { value: 1.0 },
        u_fy: { value: 1.0 },
        u_cx: { value: w / 2 },
        u_cy: { value: h / 2 },
        u_depth_scale: { value: 0.001 },
        u_size: { value: new THREE.Vector2(w, h) },
        u_point_size: { value: pointSize },
        u_max_depth_m: { value: maxDepthM },
        u_color_mode: { value: colorMode === 'rgb' ? 0 : 1 },
      },
      vertexShader: VERTEX_SHADER,
      fragmentShader: FRAGMENT_SHADER,
      depthTest: true,
      depthWrite: false,
    });

    points = new THREE.Points(geom, material);
    points.frustumCulled = false;
    cloudGroup.add(points);
    dims = { w, h };
  }

  function handleFrame(frame: DecodedDepthFrame): void {
    if (disposed) return;
    ensureGeometry(frame.depthW, frame.depthH);
    if (!points || !depthTexture || !colorTexture) return;

    if (!depthCopy || depthCopy.length !== frame.depth.length) {
      depthCopy = new Uint16Array(frame.depth.length);
    }
    depthCopy.set(frame.depth);
    depthTexture.image.data = depthCopy;
    depthTexture.needsUpdate = true;

    void createImageBitmap(frame.colorBlob).then((bm) => {
      if (disposed || !colorTexture) { bm.close(); return; }
      // PIP 카메라 뷰 콜백 — texture 할당 전에 호출 (콜백 내부에서 drawImage 동기 복사 가정).
      try { opts.onColorBitmap?.(bm, frame.colorW, frame.colorH); } catch (e) {
        console.warn('[DepthCloud] onColorBitmap handler:', e);
      }
      if (colorTexture.image && (colorTexture.image as ImageBitmap).close) {
        try { (colorTexture.image as ImageBitmap).close(); } catch { /* ignore */ }
      }
      colorTexture.image = bm;
      colorTexture.needsUpdate = true;
    }).catch((e) => console.warn('[DepthCloud] color decode:', e));

    const u = (points.material as THREE.ShaderMaterial).uniforms;
    u.u_fx.value = frame.fx;
    u.u_fy.value = frame.fy;
    u.u_cx.value = frame.cx;
    u.u_cy.value = frame.cy;
    u.u_depth_scale.value = frame.depthScale;
  }

  function scheduleReconnect(): void {
    if (stopped || reconnectTimer) return;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      backoffMs = Math.min(backoffMs * 2, 30000);
      connect();
    }, backoffMs);
  }

  function connect(): void {
    const ws = new WebSocket(wsUrl);
    currentWs = ws;
    ws.binaryType = 'arraybuffer';

    ws.onopen = () => { /* await welcome */ };
    ws.onclose = () => { scheduleReconnect(); };
    ws.onerror = () => { /* rely on onclose */ };

    ws.onmessage = (ev: MessageEvent) => {
      const data = ev.data;
      if (typeof data === 'string') {
        let m: { type?: string };
        try { m = JSON.parse(data); } catch { return; }
        if (m.type === 'welcome') {
          ws.send(JSON.stringify({
            type: 'hello', client_id: clientId, client_kind: 'depth-viewer',
            ts_ms: Date.now(),
          }));
        } else if (m.type === 'hello_ack') {
          // doctor 진찰 대상은 EduPing 한 대 — robot 키로 subscribe.
          // TODO(plan-2): edupingId → robot 매핑 (현재는 'eduping' 단일 가정).
          ws.send(JSON.stringify({
            type: 'subscribe', robot: 'eduping', stream: 0, ts_ms: Date.now(),
          }));
          backoffMs = 1000;
        } else if (m.type === 'ping') {
          ws.send(JSON.stringify({ type: 'pong', ts_ms: Date.now() }));
        }
        return;
      }
      if (!(data instanceof ArrayBuffer)) return;
      const frame = decodeFrame(data);
      if (frame === null) return;
      try { handleFrame(frame); } catch (e) { console.error('[DepthCloud] handleFrame:', e); }
    };
  }

  // edupingId 는 현재 미사용 — 같은 ws-url 로 단일 EduPing subscribe.
  // 추후 multi-EduPing 지원 시 hello/subscribe 페이로드에 포함시킨다.
  void opts.edupingId;

  connect();

  return {
    dispose(): void {
      disposed = true;
      stopped = true;
      if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
      try { currentWs?.close(); } catch { /* ignore */ }
      teardownGeometry();
      opts.scene.remove(cloudGroup);
    },
    setVisible(visible: boolean): void {
      cloudGroup.visible = visible;
    },
  };
}
