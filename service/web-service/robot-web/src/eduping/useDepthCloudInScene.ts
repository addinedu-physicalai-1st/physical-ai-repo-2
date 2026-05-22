/**
 * OpenarmViewer scene 에 D435 depth point cloud 를 합성.
 *
 * THREE.Points 를 robot URDF 의 d435_depth_optical_frame link 자식으로 붙임 — 부모 chain
 * (optical → d435_link → body → world → wrapper rotation -pi/2 about X) 이 자동으로
 * 좌표 변환. 셰이더는 optical frame native (Z forward, X right, Y down) 으로 출력.
 *
 * DepthViewer.vue 의 셰이더와 비슷하지만 axis flip 없음 — parent chain 이 모든 변환 처리.
 */
import * as THREE from 'three';
import { useDepthStream, type DecodedDepthFrame, type UseDepthStream } from './useDepthStream';

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
  uniform float u_world_bound_xz;
  uniform float u_world_min_y;
  uniform int u_color_mode;   // 0 = RGB (JPEG), 1 = depth jet colormap
  uniform int u_use_hand_bbox;   // 1 = 손 bbox 안만 렌더 (cloud 필터링)
  uniform vec2 u_hand_uv_min;
  uniform vec2 u_hand_uv_max;
  out vec3 v_color;
  flat out int v_valid;

  // Jet colormap — RViz / RealSense-Viewer 의 cold-to-warm 그라데이션.
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

    // 손 bbox 필터링 — DepthViewer 의 toggle 이 ON 일 때만 활성.
    if (u_use_hand_bbox == 1) {
      if (uv.x < u_hand_uv_min.x || uv.x > u_hand_uv_max.x ||
          uv.y < u_hand_uv_min.y || uv.y > u_hand_uv_max.y) {
        gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
        gl_PointSize = 0.0;
        v_color = vec3(0.0);
        v_valid = 0;
        return;
      }
    }

    float x = (uv.x - u_cx) * d_m / u_fx;
    float y = (uv.y - u_cy) * d_m / u_fy;
    float z = d_m;

    // y flip 제거 — D435 정상 장착 시 optical y-down 그대로 사용. URDF 의
    // d435_depth_optical_frame rpy 가 parent chain 에서 자동 변환.
    vec4 modelPos = vec4(x, y, z, 1.0);

    vec4 worldPos = modelMatrix * modelPos;
    if (abs(worldPos.x) > u_world_bound_xz ||
        abs(worldPos.z) > u_world_bound_xz ||
        worldPos.y < u_world_min_y) {
      gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
      gl_PointSize = 0.0;
      v_color = vec3(0.0);
      v_valid = 0;
      return;
    }

    gl_Position = projectionMatrix * modelViewMatrix * modelPos;
    gl_PointSize = u_point_size;

    if (u_color_mode == 1) {
      // Depth jet colormap — near=blue, mid=green, far=red.
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

export interface UseDepthCloudInSceneOpts {
  /** URDFLoader 로 로드된 robot (URDFRobot 인스턴스). */
  robot: { links?: Record<string, THREE.Object3D> };
  /** 최대 표시 거리 (m) — 이보다 멀면 cull. 기본 3.0m (등원 시나리오). */
  maxDepthM?: number;
  /** 포인트 사이즈 (px). OpenarmViewer 카메라 거리 (~2m) 에서는 4.0+ 권장. 기본 4.0. */
  pointSize?: number;
  /** OpenarmViewer GridHelper 반-크기 (m). 이 박스 밖 포인트는 cull. 기본 1.0 (=grid 2.0m). */
  worldBoundXZ?: number;
  /** 그리드 평면 y (m). 이 아래 포인트는 cull. 기본 -0.05 (작은 여유). */
  worldMinY?: number;
  /** Points 객체 local scale. URDF 가 mm-mesh + m-link 라 1:1 안 맞으면 여기서 dial-in.
   *  기본 1.0 (=1m optical = 1m world). 사용자가 보기에 cloud 가 너무 크면 0.5 등. */
  cloudScale?: number;
  /** D435 FoV 와이어프레임 frustum 표시 (RealSense viewer 의 녹색 박스 같은). 기본 true. */
  showFrustum?: boolean;
  /** Frustum near plane (m). 기본 0.3 (D435 minZ). */
  frustumNearM?: number;
  /** Frustum far plane (m). 기본 maxDepthM 와 동일. */
  frustumFarM?: number;
  /** 색 모드: 'rgb' = JPEG 컬러 / 'depth' = jet colormap (near 파랑 → far 빨강). 기본 'depth'. */
  colorMode?: 'rgb' | 'depth';
  /** Parent-owned stream — omit to create a private WS (prefer one shared instance). */
  depthStream?: UseDepthStream;
}

export interface HandBbox {
  uMin: number;
  uMax: number;
  vMin: number;
  vMax: number;
}

export interface UseDepthCloudInScene {
  /** 마운트 끊고 모든 리소스 dispose. */
  dispose(): void;
  /** 현재 cloud 표시 여부 토글 — Points.visible 조작. */
  setVisible(visible: boolean): void;
  /** 손 bbox 필터 — null 이면 전체 cloud, 값 있으면 bbox 내부만. */
  setHandBbox(box: HandBbox | null): void;
}

export function useDepthCloudInScene(
  opts: UseDepthCloudInSceneOpts,
): UseDepthCloudInScene {
  const opticalLink = opts.robot.links?.['d435_depth_optical_frame'];
  if (!opticalLink) {
    console.warn(
      '[useDepthCloudInScene] d435_depth_optical_frame link not in URDF tree — skipping',
    );
    return { dispose: () => {}, setVisible: () => {}, setHandBbox: () => {} };
  }

  const stream = opts.depthStream ?? useDepthStream('eduping');
  const ownsStream = !opts.depthStream;
  let points: THREE.Points | null = null;
  let depthTexture: THREE.DataTexture | null = null;
  let depthCopy: Uint16Array | null = null;
  let colorTexture: THREE.Texture | null = null;
  let dims = { w: 0, h: 0 };
  let disposed = false;
  let frustum: THREE.LineSegments | null = null;

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
    geom.boundingSphere = new THREE.Sphere(new THREE.Vector3(0, 0, 0), 10);

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
        u_point_size: { value: opts.pointSize ?? 4.0 },
        u_max_depth_m: { value: opts.maxDepthM ?? 3.0 },
        u_world_bound_xz: { value: opts.worldBoundXZ ?? 1.0 },
        u_world_min_y: { value: opts.worldMinY ?? -0.05 },
        u_color_mode: { value: opts.colorMode === 'rgb' ? 0 : 1 },
        u_use_hand_bbox: { value: 0 },
        u_hand_uv_min: { value: new THREE.Vector2(0, 0) },
        u_hand_uv_max: { value: new THREE.Vector2(0, 0) },
      },
      vertexShader: VERTEX_SHADER,
      fragmentShader: FRAGMENT_SHADER,
      depthTest: true,
      depthWrite: false,
    });

    points = new THREE.Points(geom, material);
    if (opts.cloudScale && opts.cloudScale !== 1.0) {
      points.scale.setScalar(opts.cloudScale);
    }
    opticalLink!.add(points);
    dims = { w, h };
  }

  function ensureFrustum(
    w: number, h: number, fx: number, fy: number, cx: number, cy: number,
  ): void {
    if (frustum || !opts.showFrustum) return;
    const nearZ = opts.frustumNearM ?? 0.3;
    const farZ = opts.frustumFarM ?? (opts.maxDepthM ?? 3.0);
    // 4 corner ray vectors (pixel → camera direction). 광학 frame 그대로.
    const corner = (u: number, v: number, z: number) => [
      ((u - cx) * z) / fx,
      ((v - cy) * z) / fy,
      z,
    ];
    const nearC = [
      corner(0, 0, nearZ),     corner(w - 1, 0, nearZ),
      corner(w - 1, h - 1, nearZ), corner(0, h - 1, nearZ),
    ];
    const farC = [
      corner(0, 0, farZ),       corner(w - 1, 0, farZ),
      corner(w - 1, h - 1, farZ), corner(0, h - 1, farZ),
    ];
    // cloud 와 동일 mapping — y flip 제거 후 raw optical 그대로.
    const N = nearC;
    const F = farC;
    // LineSegments edges: near 4, far 4, near→far 4 = 12 edges = 24 vertices
    const e = (a: number[], b: number[]) => [...a, ...b];
    const verts = new Float32Array([
      ...e(N[0], N[1]), ...e(N[1], N[2]), ...e(N[2], N[3]), ...e(N[3], N[0]),
      ...e(F[0], F[1]), ...e(F[1], F[2]), ...e(F[2], F[3]), ...e(F[3], F[0]),
      ...e(N[0], F[0]), ...e(N[1], F[1]), ...e(N[2], F[2]), ...e(N[3], F[3]),
    ]);
    const geom = new THREE.BufferGeometry();
    geom.setAttribute('position', new THREE.BufferAttribute(verts, 3));
    const material = new THREE.LineBasicMaterial({
      color: 0x22ee22,
      transparent: true,
      opacity: 0.5,
      depthTest: true,
    });
    frustum = new THREE.LineSegments(geom, material);
    if (opts.cloudScale && opts.cloudScale !== 1.0) {
      frustum.scale.setScalar(opts.cloudScale);
    }
    opticalLink!.add(frustum);
  }

  function teardownGeometry(): void {
    if (points && opticalLink) {
      opticalLink.remove(points);
      points.geometry.dispose();
      (points.material as THREE.Material).dispose();
      points = null;
    }
    if (frustum && opticalLink) {
      opticalLink.remove(frustum);
      frustum.geometry.dispose();
      (frustum.material as THREE.Material).dispose();
      frustum = null;
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

  function handleFrame(frame: DecodedDepthFrame): void {
    if (disposed) return;
    ensureGeometry(frame.depthW, frame.depthH);
    ensureFrustum(
      frame.depthW, frame.depthH,
      frame.fx, frame.fy, frame.cx, frame.cy,
    );
    if (!points || !depthTexture || !colorTexture) return;

    if (!depthCopy || depthCopy.length !== frame.depth.length) {
      depthCopy = new Uint16Array(frame.depth.length);
    }
    depthCopy.set(frame.depth);
    depthTexture.image.data = depthCopy;
    depthTexture.needsUpdate = true;

    void createImageBitmap(frame.colorBlob).then((bm) => {
      if (disposed || !colorTexture) { bm.close(); return; }
      if (colorTexture.image && (colorTexture.image as ImageBitmap).close) {
        try { (colorTexture.image as ImageBitmap).close(); } catch { /* ignore */ }
      }
      colorTexture.image = bm;
      colorTexture.needsUpdate = true;
    }).catch((e) => console.warn('[useDepthCloudInScene] color decode:', e));

    const u = (points.material as THREE.ShaderMaterial).uniforms;
    u.u_fx.value = frame.fx;
    u.u_fy.value = frame.fy;
    u.u_cx.value = frame.cx;
    u.u_cy.value = frame.cy;
    u.u_depth_scale.value = frame.depthScale;
  }

  stream.onFrame(handleFrame);

  return {
    dispose(): void {
      disposed = true;
      teardownGeometry();
      if (ownsStream) stream.stop();
    },
    setVisible(visible: boolean): void {
      if (points) points.visible = visible;
    },
    setHandBbox(box: HandBbox | null): void {
      if (!points) return;
      const u = (points.material as THREE.ShaderMaterial).uniforms;
      if (box === null) {
        u.u_use_hand_bbox.value = 0;
        return;
      }
      u.u_use_hand_bbox.value = 1;
      (u.u_hand_uv_min.value as THREE.Vector2).set(box.uMin, box.vMin);
      (u.u_hand_uv_max.value as THREE.Vector2).set(box.uMax, box.vMax);
    },
  };
}
