"""무궁화 device-local perception.

  /d435/color/image_raw (ROS, 로컬)
        │ cv_bridge → BGR
        ▼
  yolo.track(persist=True, classes=[0])  → tracks[{track_id,bbox,conf}]
        │
        ├─ ENTRY:     1~2Hz full frame → control-service /api/attendance/recognize-multi
        │             (InsightFace) → IoU 매칭 → track_id↔child_id 바인딩 → registered 이벤트
        ├─ OBSERVING: track baseline 대비 변위 → 탈락 child_id 선정 (device-local)
        │             → eliminated 이벤트 / 미식별 motion 이벤트
        └─ WS producer ×2:
             /ws/eduping/mugunghwa?role=robot         JSON 이벤트 송신 + 명령 수신
             /ws/eduping/mugunghwa/video?role=producer JPEG 프레임

상태는 브라우저 명령(observe_start/observe_stop/reset)으로 전이. recognize POST 는
blocking 이라 별도 worker thread 에서 수행 — ROS 콜백/hot loop 비차단.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request

import cv2
import numpy as np
import rclpy
import tf2_ros
from cv_bridge import CvBridge
from rcl_interfaces.msg import SetParametersResult
from rclpy.node import Node
from rclpy.time import Time
from sensor_msgs.msg import CameraInfo, Image
from websockets.sync.client import connect as ws_connect

from eduarm.arm_self_mask import arm_pixel_mask, backproject
from eduarm.mugunghwa_motion import (
    bbox_motion,
    centroid,
    match_recognize_to_tracks,
    max_displacement,
    max_motion,
    select_movers,
    select_movers_sad,
)
from eduarm.proximity import (
    OFF_FRAMES_DEFAULT,
    ON_FRAMES_DEFAULT,
    REACH_PCTL_DEFAULT,
    REACH_SELF_FLOOR_MM_DEFAULT,
    person_distance_mm,
    step_debounce,
)

ALIGNED_DEPTH_TOPIC = "/d435/aligned_depth_to_color/image_raw"
COLOR_INFO_TOPIC = "/d435/color/camera_info"
# aligned_depth_to_color 는 color 광학 프레임에 정렬 → 같은 프레임에서 back-projection.
CAMERA_OPTICAL_FRAME = "d435_color_optical_frame"
# 팔 캡슐 = consecutive link 원점 쌍. link0..7 양팔. (URDF openarm_{side}_link{i})
ARM_LINK_CHAIN = [f"link{i}" for i in range(8)]

EVENT_PATH = "/ws/eduping/mugunghwa?role=robot"
VIDEO_PATH = "/ws/eduping/mugunghwa/video?role=producer"
RECOGNIZE_PATH = "/api/attendance/recognize-multi"


def _post_recognize_multi(url: str, jpeg: bytes, token: str, timeout: float = 2.0) -> list[dict]:
    """multipart/form-data 로 recognize-multi 호출. matched=True 인 match 만 반환."""
    boundary = "----mugunghwaBoundary7d8e9f0a1b"
    body = b"".join([
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="file"; filename="frame.jpg"\r\n',
        b"Content-Type: image/jpeg\r\n\r\n",
        jpeg,
        f"\r\n--{boundary}--\r\n".encode(),
    ])
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("X-Device-Token", token)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())
    out: list[dict] = []
    for m in data.get("matches", []):
        if m.get("matched") and m.get("child_id") is not None and m.get("bbox"):
            out.append({"child_id": int(m["child_id"]), "bbox": m["bbox"]})
    return out


class _WsProducer:
    """control-service 로 붙는 WS producer + 재접속 데몬 (d435_rgb_uploader 패턴)."""

    def __init__(self, url: str, logger, *, name: str = "mugunghwa-ws", on_message=None) -> None:
        self._url = url
        self._log = logger
        self._on_message = on_message
        self._ws = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        threading.Thread(target=self._loop, name=name, daemon=True).start()

    def _loop(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                ws = ws_connect(self._url, max_size=None)
                with self._lock:
                    self._ws = ws
                self._log.info(f"WS connected → {self._url}")
                backoff = 1.0
                try:
                    for msg in ws:
                        if self._on_message and isinstance(msg, str):
                            self._on_message(msg)
                except Exception:
                    pass
            except Exception as exc:
                self._log.warn(f"WS connect failed: {exc}")
            with self._lock:
                self._ws = None
            self._stop.wait(backoff)
            backoff = min(backoff * 2, 30.0)

    def send_text(self, text: str) -> None:
        with self._lock:
            ws = self._ws
        if ws is None:
            return
        try:
            ws.send(text)
        except Exception:
            pass

    def send_bytes(self, payload: bytes) -> None:
        with self._lock:
            ws = self._ws
        if ws is None:
            return
        try:
            ws.send(payload)
        except Exception:
            pass

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            if self._ws:
                try:
                    self._ws.close()
                except Exception:
                    pass
                self._ws = None


class MugunghwaPerception(Node):
    def __init__(self) -> None:
        super().__init__("mugunghwa_perception")
        self.declare_parameter("control_url", "ws://localhost:8000")
        self.declare_parameter("recognize_base_url", "http://localhost:8000")
        # control-service ROBOT_DEVICE_TOKEN / robot-web VITE_ROBOT_TOKEN 와 동일한 dev 기본값.
        # 운영에선 launch arg(device_token:=) 또는 env 로 override. 빈값이면 recognize 401.
        self.declare_parameter("device_token", "dev-robot-token-change-me")
        self.declare_parameter("jpeg_quality", 75)
        self.declare_parameter("throttle_hz", 15.0)
        self.declare_parameter("entry_recognize_hz", 1.5)
        self.declare_parameter("yolo_model", "yolov8n.pt")
        self.declare_parameter("yolo_conf", 0.20)
        self.declare_parameter("yolo_imgsz", 640)
        # centroid 변위 탈락 임계. 가까운 사람은 bbox 가 커 흔들림만으로 10px 를 넘기 쉬워 30 으로.
        self.declare_parameter("mover_px", 30.0)
        self.declare_parameter("mover_loose_px", 12.0)
        self.declare_parameter("motion_cooldown_s", 2.0)
        # SAD(프레임 차분) 모션 — centroid 가 못 잡는 국소 동작(팔 흔들기)·정면 접근 감지.
        # bbox 에서 |Δ|>delta 인 픽셀 비율. strict 이상 탈락, loose 이상 미식별 motion flash.
        # SAD 탈락 임계. 거리 의존성(가까울수록 같은 동작이 큰 픽셀 변화)이 있어 단일 값으론
        # 완벽 분리 불가 — 런타임 파라미터 콜백으로 현장 튜닝(아래 _on_set_params). 기본 0.10.
        self.declare_parameter("mover_sad_strict", 0.300)
        self.declare_parameter("mover_sad_loose", 0.120)
        self.declare_parameter("mover_sad_delta", 25)
        # 근접 도달 — 사람이 1.0m 이내로 다가오면 "로봇 도달"(게임 종료 트리거). 전역 proximity
        # 정지와 달리 무궁화는 접근이 게임 목표라 정지 대신 도달 이벤트로 쓴다. aligned depth 의
        # 사람 bbox 거리로 판정, step_debounce 로 occlusion 깜빡임 무시.
        self.declare_parameter("reach_near_mm", 1000)
        self.declare_parameter("reach_on_frames", ON_FRAMES_DEFAULT)
        self.declare_parameter("reach_off_frames", OFF_FRAMES_DEFAULT)
        # median(50) — bbox 에 겹친 로봇 팔/윤곽 노이즈 같은 소수 near 픽셀에 강건. 사람 몸통
        # 실제 거리를 잡아 "멀어도 종료" 오검출 방지.
        self.declare_parameter("reach_person_pctl", REACH_PCTL_DEFAULT)
        # self_floor — 이보다 가까운 픽셀은 로봇 자기 팔로 보고 제외(extrinsic 불필요). 실물
        # 가리기 팔의 카메라 거리에 맞춰 튜닝 (reached 로그의 dist 와 팔 위치 보고 조정).
        self.declare_parameter("reach_self_floor_mm", REACH_SELF_FLOOR_MM_DEFAULT)
        # URDF self-filter — TF 로 팔 link 를 카메라 광학 프레임으로 가져와 캡슐로 팔 픽셀 마스킹.
        # extrinsic(d435_mount_joint) 는 URDF/launch 에 정의됨. arm bringup 의 TF 가 있어야 동작,
        # 없으면 self_floor 만으로 폴백. capsule_radius 는 팔 굵기+마진.
        self.declare_parameter("arm_self_filter", True)
        self.declare_parameter("arm_capsule_radius_m", 0.08)
        self.declare_parameter("camera_optical_frame", CAMERA_OPTICAL_FRAME)

        gp = self.get_parameter
        base = gp("control_url").get_parameter_value().string_value
        self._recognize_url = (
            gp("recognize_base_url").get_parameter_value().string_value + RECOGNIZE_PATH
        )
        self._device_token = gp("device_token").get_parameter_value().string_value
        self._quality = int(gp("jpeg_quality").get_parameter_value().integer_value)
        hz = float(gp("throttle_hz").get_parameter_value().double_value)
        self._min_period = 1.0 / max(0.1, hz)
        self._entry_period = 1.0 / max(0.1, float(
            gp("entry_recognize_hz").get_parameter_value().double_value))
        self._yolo_conf = float(gp("yolo_conf").get_parameter_value().double_value)
        self._yolo_imgsz = int(gp("yolo_imgsz").get_parameter_value().integer_value)
        self._mover_px = float(gp("mover_px").get_parameter_value().double_value)
        self._mover_loose_px = float(gp("mover_loose_px").get_parameter_value().double_value)
        self._cooldown_s = float(gp("motion_cooldown_s").get_parameter_value().double_value)
        self._sad_strict = float(gp("mover_sad_strict").get_parameter_value().double_value)
        self._sad_loose = float(gp("mover_sad_loose").get_parameter_value().double_value)
        self._sad_delta = int(gp("mover_sad_delta").get_parameter_value().integer_value)
        self._reach_near_mm = int(gp("reach_near_mm").get_parameter_value().integer_value)
        self._reach_on = int(gp("reach_on_frames").get_parameter_value().integer_value)
        self._reach_off = int(gp("reach_off_frames").get_parameter_value().integer_value)
        self._reach_pctl = int(gp("reach_person_pctl").get_parameter_value().integer_value)
        self._reach_self_floor = int(gp("reach_self_floor_mm").get_parameter_value().integer_value)
        self._arm_self_filter = bool(gp("arm_self_filter").get_parameter_value().bool_value)
        self._capsule_r = float(gp("arm_capsule_radius_m").get_parameter_value().double_value)
        self._optical_frame = gp("camera_optical_frame").get_parameter_value().string_value

        # 런타임 튜닝 — 재빌드 없이 `ros2 param set` 으로 임계 즉시 반영(현장 캘리브용).
        self.add_on_set_parameters_callback(self._on_set_params)

        # TF — 팔 link → 카메라 광학 프레임. arm bringup(robot_state_publisher) + d435 static_tf
        # 가 떠 있어야 채워진다. 없으면 lookup 실패 → self-filter no-op.
        self._tf_buffer = tf2_ros.Buffer()
        self._tf_listener = tf2_ros.TransformListener(self._tf_buffer, self)
        self._intrinsics: tuple[float, float, float, float] | None = None  # fx,fy,cx,cy

        from ultralytics import YOLO  # lazy — import 비용 큼
        self._yolo = YOLO(gp("yolo_model").get_parameter_value().string_value)

        self._bridge = CvBridge()
        # 아래 timestamp/inflight 플래그는 단일 스레드 executor(rclpy.spin) 전제 — _on_image
        # 가 한 스레드에서만 호출되므로 lock 없이 안전. MultiThreadedExecutor 로 바꾸면 race.
        self._last_send = 0.0
        self._last_entry = 0.0
        self._last_elim = 0.0
        self._last_motion = 0.0
        self._last_judge_log = 0.0

        # 상태: "idle" | "entry" | "observing"
        self._mode = "idle"
        self._tracks: list[dict] = []       # 최신 yolo.track 결과
        self._bindings: dict[int, int] = {}  # track_id → child_id
        self._baseline: dict[int, tuple[float, float]] = {}
        self._state_lock = threading.Lock()
        self._recognize_inflight = False
        # 근접 도달 상태 — 최신 aligned depth + 디바운스. _reach_near 는 디바운스된 근접 여부,
        # rising edge(False→True)에서만 reached 이벤트 1회 emit (멀어지면 자연 re-arm).
        self._latest_depth: np.ndarray | None = None
        self._reach_near = False
        self._reach_streak = 0
        # SAD 모션용 직전 관찰 프레임(grayscale). observe_start 에서 None 으로 리셋 → 첫
        # 관찰 프레임은 seed 만 하고 판정은 다음 프레임부터.
        self._prev_gray: np.ndarray | None = None

        self._events = _WsProducer(base + EVENT_PATH, self.get_logger(),
                                   name="mugunghwa-ws-events", on_message=self._on_command)
        self._video = _WsProducer(base + VIDEO_PATH, self.get_logger(),
                                  name="mugunghwa-ws-video")

        self.create_subscription(Image, "/d435/color/image_raw", self._on_image, 1)
        self.create_subscription(Image, ALIGNED_DEPTH_TOPIC, self._on_depth, 1)
        self.create_subscription(CameraInfo, COLOR_INFO_TOPIC, self._on_camera_info, 1)
        self.get_logger().info("mugunghwa_perception up")

    def _on_depth(self, msg: Image) -> None:
        # 16UC1 aligned-to-color → 최신 프레임만 캐시 (color bbox 를 그대로 인덱싱).
        try:
            self._latest_depth = np.frombuffer(
                msg.data, dtype=np.uint16
            ).reshape(msg.height, msg.width)
        except Exception:  # noqa: BLE001
            pass

    def _on_camera_info(self, msg: CameraInfo) -> None:
        # K = [fx 0 cx; 0 fy cy; 0 0 1] — back-projection intrinsics. msg.k 는 numpy array(9)
        # 라 truthiness 검사 금지(ambiguous) → 길이/값으로 검사.
        k = msg.k
        if len(k) >= 6 and k[0] > 0 and k[4] > 0:
            self._intrinsics = (float(k[0]), float(k[4]), float(k[2]), float(k[5]))

    def _on_set_params(self, params) -> SetParametersResult:
        """런타임 파라미터 변경을 캐시 변수에 즉시 반영 — 재빌드 없이 임계 튜닝."""
        for p in params:
            v = p.value
            if p.name == "mover_sad_strict":
                self._sad_strict = float(v)
            elif p.name == "mover_sad_loose":
                self._sad_loose = float(v)
            elif p.name == "mover_sad_delta":
                self._sad_delta = int(v)
            elif p.name == "mover_px":
                self._mover_px = float(v)
            elif p.name == "mover_loose_px":
                self._mover_loose_px = float(v)
            elif p.name == "motion_cooldown_s":
                self._cooldown_s = float(v)
            elif p.name == "reach_near_mm":
                self._reach_near_mm = int(v)
            elif p.name == "reach_self_floor_mm":
                self._reach_self_floor = int(v)
            elif p.name == "arm_capsule_radius_m":
                self._capsule_r = float(v)
        return SetParametersResult(successful=True)

    # ---- 브라우저 명령 ----
    def _on_command(self, text: str) -> None:
        try:
            msg = json.loads(text)
        except Exception:
            return
        # 모드: idle(YOLO 안 함) | entry(YOLO+recognize) | playing(YOLO 추적만) | observing(YOLO+판정)
        # recognize(InsightFace 호출)는 entry 단계에만. register_start/stop 으로 UI 가 참가자
        # 확인 단계 진입/이탈을 알려, song/종료 중엔 recognize 가 멈춘다.
        t = msg.get("type")
        if t == "register_start":
            with self._state_lock:
                self._mode = "entry"
        elif t == "register_stop":
            with self._state_lock:
                self._mode = "playing"
        elif t == "observe_start":
            with self._state_lock:
                self._baseline = {
                    tk["track_id"]: centroid(tk["bbox"]) for tk in self._tracks
                }
                self._mode = "observing"
            self._prev_gray = None  # SAD seed 리셋 — 첫 관찰 프레임부터 다시 비교
            self.get_logger().info(f"observe_start (baseline n={len(self._baseline)})")
        elif t == "observe_stop":
            with self._state_lock:
                self._mode = "playing"
                self._baseline = {}
        elif t == "reset":
            with self._state_lock:
                self._mode = "playing"
                self._bindings = {}
                self._baseline = {}
        elif t == "idle":
            # 놀이 끝(end) — YOLO/recognize 정지. attendance POST·추론 멈춤.
            with self._state_lock:
                self._mode = "idle"
        elif t == "peer":
            # ui 접속 시 entry 로 진입(초기 참가자 확인 — recognize on). 떠나면 idle.
            with self._state_lock:
                self._mode = "entry" if msg.get("present") else "idle"

    def _emit(self, payload: dict) -> None:
        self._events.send_text(json.dumps(payload))

    # ---- 영상 콜백 ----
    def _on_image(self, msg: Image) -> None:
        try:
            bgr = self._bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except Exception as exc:
            self.get_logger().warn(f"cv_bridge failed: {exc}")
            return
        with self._state_lock:
            mode = self._mode

        # YOLO + ByteTrack (hot loop).
        tracks: list[dict] = []
        if mode != "idle":
            try:
                results = self._yolo.track(
                    bgr, persist=True, classes=[0], conf=self._yolo_conf,
                    imgsz=self._yolo_imgsz, tracker="bytetrack.yaml", verbose=False,
                )
            except Exception as e:
                self.get_logger().warn(f"yolo.track failed: {e}")
                results = None
            if results:
                r = results[0]
                if r.boxes is not None and r.boxes.id is not None:
                    xyxy = r.boxes.xyxy.cpu().numpy()
                    ids = r.boxes.id.cpu().numpy().astype(int)
                    conf = r.boxes.conf.cpu().numpy()
                    for i in range(len(ids)):
                        x1, y1, x2, y2 = (float(v) for v in xyxy[i].tolist())
                        tracks.append({
                            "track_id": int(ids[i]),
                            "bbox": (x1, y1, x2, y2),
                            "conf": float(conf[i]),
                        })
        with self._state_lock:
            self._tracks = tracks

        # recognize 는 entry 뿐 아니라 게임 중(playing/observing)에도 — 단, _maybe_recognize 가
        # "미바인딩 track 이 있을 때만" 호출하므로(전원 바인딩이면 skip), ID 안정 시엔 안 돈다.
        # 화면 밖→재진입으로 새 track_id 가 생기면(미바인딩) 얼굴 재인식해 다시 바인딩 →
        # 탈락 판정이 그 아이를 다시 식별. idle 에선 안 함.
        if mode in ("entry", "playing", "observing"):
            self._maybe_recognize(bgr, tracks)
        if mode == "observing":
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            self._judge_movers(tracks, gray)

        # 근접 도달 — 게임 진행(playing/observing) 중에만. entry/idle 에선 등록차 가까이
        # 와도 도달로 보지 않는다. (브라우저도 단계로 한 번 더 게이팅)
        if mode in ("playing", "observing"):
            self._judge_reach(tracks)
        else:
            self._reach_near = False
            self._reach_streak = 0

        self._maybe_send_video(bgr)

    # ---- entry: recognize-multi (worker thread, blocking) ----
    def _maybe_recognize(self, bgr, tracks: list[dict]) -> None:
        now = time.monotonic()
        if now - self._last_entry < self._entry_period:
            return
        if self._recognize_inflight or not tracks:
            return
        # 이미 모든 track 이 child 에 바인딩됐으면 recognize 불필요 — 미식별 track 이 있을 때만
        # POST. 같은 track_id 가 유지되는 한 재인식 안 함 (서버 InsightFace 부하 ↓). 새 사람이
        # 들어오면 새 track_id(unbound) 가 생겨 즉시 재개.
        with self._state_lock:
            bound = set(self._bindings)
        if all(t["track_id"] in bound for t in tracks):
            return
        self._last_entry = now
        ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, self._quality])
        if not ok:
            return
        jpeg = buf.tobytes()
        snapshot = list(tracks)
        self._recognize_inflight = True
        threading.Thread(
            target=self._recognize_worker, args=(jpeg, snapshot), daemon=True
        ).start()

    def _recognize_worker(self, jpeg: bytes, tracks: list[dict]) -> None:
        try:
            matches = _post_recognize_multi(self._recognize_url, jpeg, self._device_token)
        except Exception as exc:
            self.get_logger().debug(f"recognize failed: {exc}")
            matches = []
        finally:
            self._recognize_inflight = False
        if not matches:
            return
        new_bind = match_recognize_to_tracks(matches, tracks)
        newly_registered: list[int] = []
        with self._state_lock:
            for tid, cid in new_bind.items():
                if self._bindings.get(tid) != cid:
                    self._bindings[tid] = cid
                    newly_registered.append(cid)
        for cid in newly_registered:
            self._emit({"type": "registered", "child_id": cid})

    # ---- observation: 움직임 판정 (centroid 변위 ∪ SAD 프레임 차분) ----
    def _judge_movers(self, tracks: list[dict], gray: np.ndarray) -> None:
        prev = self._prev_gray
        self._prev_gray = gray
        with self._state_lock:
            baseline = dict(self._baseline)
            bindings = dict(self._bindings)

        # SAD — bbox 프레임 차분(팔 흔들기·정면 접근 등 국소/스케일 동작). 첫 관찰 프레임은
        # prev 가 없어 seed 만. 관찰 중 떼기 모션으로 움직이는 로봇 자기 팔은 self-filter
        # 마스크로 제외(거짓 탈락 방지).
        sad_movers: list[int] = []
        sad_max = 0.0
        motion: dict[int, float] = {}
        if prev is not None and prev.shape == gray.shape:
            arm_mask = self._arm_mask_full(gray.shape)
            motion = {
                t["track_id"]: bbox_motion(
                    prev, gray, t["bbox"], delta=self._sad_delta, ignore_mask=arm_mask)
                for t in tracks
            }
            sad_movers = select_movers_sad(motion, bindings, self._sad_strict)
            sad_max = max_motion(motion)

        # centroid 변위(좌우 큰 이동)와 합집합. 둘 다 strict 만으로 탈락(loose fallback 없음).
        cen_movers = select_movers(tracks, baseline, bindings, self._mover_px)
        movers = list(dict.fromkeys([*cen_movers, *sad_movers]))
        max_disp = max_displacement(tracks, baseline)

        now = time.monotonic()
        # 진단 — 왜 탈락/모션이 안 나는지 (tracks/바인딩/SAD/변위). ~1Hz throttle.
        if now - self._last_judge_log > 1.0:
            self._last_judge_log = now
            top_tid = max(motion, key=motion.get) if motion else None
            self.get_logger().info(
                f"movers diag: tracks={len(tracks)} bound={len(bindings)} "
                f"sad_max={sad_max:.3f}(strict={self._sad_strict} loose={self._sad_loose}) "
                f"max_disp={max_disp:.1f} cen={cen_movers} sad={sad_movers} "
                f"bound_ids={sorted(bindings)} cur_ids={sorted(t['track_id'] for t in tracks)} "
                f"top_sad_tid={top_tid}(bound={top_tid in bindings if top_tid is not None else False})"
            )
        # 쿨다운 분리 — motion flash 와 eliminated 가 별도 타임스탬프. flash(미식별)가
        # 진짜 탈락을 막지 않도록. (이전엔 공유 _last_elim 라 flash 직후 탈락이 2초 막혔음.)
        if movers:
            if now - self._last_elim >= self._cooldown_s:
                self._last_elim = now
                # 탈락 트리거 원인 로그 — centroid(cen) 인지 SAD 인지, 값과 함께.
                self.get_logger().info(
                    f"ELIMINATED {movers} — by cen={cen_movers}(max_disp={max_disp:.1f}/"
                    f"strict_px={self._mover_px}) sad={sad_movers}(sad_max={sad_max:.3f}/"
                    f"strict={self._sad_strict})"
                )
                self._emit({"type": "eliminated", "child_ids": movers})
        elif max_disp >= self._mover_loose_px or sad_max >= self._sad_loose:
            if now - self._last_motion >= self._cooldown_s:
                self._last_motion = now
                self._emit({"type": "motion"})  # 미식별 — 브라우저 flash + 교사 ✕

    # ---- 팔 self-filter (URDF + TF) ----
    def _arm_segments(self) -> list:
        """팔 link 들을 카메라 광학 프레임으로 변환해 consecutive 캡슐 세그먼트 목록 생성.

        TF(arm bringup + d435 static_tf)가 없으면 빈 목록 → self-filter no-op.
        """
        if not self._arm_self_filter:
            return []
        segs: list = []
        for side in ("right", "left"):
            pts: list = []
            for link in ARM_LINK_CHAIN:
                frame = f"openarm_{side}_{link}"
                try:
                    tf = self._tf_buffer.lookup_transform(
                        self._optical_frame, frame, Time())
                except Exception:  # noqa: BLE001 — TF 미가동/지연 등 모두 skip
                    pts.append(None)
                    continue
                t = tf.transform.translation
                pts.append(np.array([t.x, t.y, t.z], dtype=np.float64))
            for a, b in zip(pts, pts[1:]):
                if a is not None and b is not None:
                    segs.append((a, b, self._capsule_r))
        return segs

    def _arm_mask_full(self, shape: tuple[int, int]) -> np.ndarray | None:
        """전체 프레임 로봇 팔 마스크(True=팔). depth/intrinsics/TF 없으면 None.

        SAD 가 떼기 모션 중 움직이는 자기 팔을 거짓 탈락으로 잡지 않도록 제외용.
        """
        depth = self._latest_depth
        if (not self._arm_self_filter or self._intrinsics is None
                or depth is None or depth.shape != shape):
            return None
        segments = self._arm_segments()
        if not segments:
            return None
        fx, fy, cx, cy = self._intrinsics
        pts = backproject(depth, 0, 0, fx, fy, cx, cy).reshape(-1, 3)
        return arm_pixel_mask(pts, segments).reshape(depth.shape)

    def _person_distance(self, depth: np.ndarray, bbox, segments: list) -> float | None:
        """bbox depth 에서 팔 픽셀(캡슐 내부)을 0 처리 후 person_distance_mm.

        segments 비었거나 intrinsics 없으면 마스킹 없이 self_floor 만 적용(폴백).
        """
        if segments and self._intrinsics is not None:
            h, w = depth.shape
            x1 = max(0, int(bbox[0])); y1 = max(0, int(bbox[1]))
            x2 = min(w, int(bbox[2])); y2 = min(h, int(bbox[3]))
            if x2 <= x1 or y2 <= y1:
                return None
            crop = depth[y1:y2, x1:x2].copy()
            fx, fy, cx, cy = self._intrinsics
            pts = backproject(crop, x1, y1, fx, fy, cx, cy).reshape(-1, 3)
            mask = arm_pixel_mask(pts, segments).reshape(crop.shape)
            crop[mask] = 0  # 팔 픽셀 → invalid
            return person_distance_mm(
                crop, (0, 0, crop.shape[1], crop.shape[0]),
                percentile=self._reach_pctl, self_floor_mm=self._reach_self_floor,
            )
        return person_distance_mm(
            depth, bbox, percentile=self._reach_pctl, self_floor_mm=self._reach_self_floor,
        )

    # ---- 근접 도달 판정 ----
    def _judge_reach(self, tracks: list[dict]) -> None:
        depth = self._latest_depth
        if depth is None:
            return
        segments = self._arm_segments()
        # 가장 가까운 track 과 그 거리. bbox 영역 depth 가 측정 불가면 그 track 은 건너뜀.
        nearest_tid: int | None = None
        nearest_mm: float | None = None
        for tk in tracks:
            d = self._person_distance(depth, tk["bbox"], segments)
            if d is None:
                continue
            if nearest_mm is None or d < nearest_mm:
                nearest_mm = d
                nearest_tid = tk["track_id"]
        raw = nearest_mm is not None and nearest_mm < self._reach_near_mm
        near, self._reach_streak = step_debounce(
            self._reach_near, raw, self._reach_streak,
            on_frames=self._reach_on, off_frames=self._reach_off,
        )
        if near and not self._reach_near:
            # rising edge — 도달 1회 emit. 바인딩된 child 면 child_id, 아니면 null.
            with self._state_lock:
                child_id = self._bindings.get(nearest_tid) if nearest_tid is not None else None
            self._emit({"type": "reached", "child_id": child_id})
            self.get_logger().info(f"reached — child_id={child_id} dist={nearest_mm:.0f}mm")
        self._reach_near = near

    # ---- 영상 송출 ----
    def _maybe_send_video(self, bgr) -> None:
        now = time.monotonic()
        if now - self._last_send < self._min_period:
            return
        self._last_send = now
        ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, self._quality])
        if ok:
            self._video.send_bytes(buf.tobytes())

    def destroy_node(self) -> bool:
        self._events.stop()
        self._video.stop()
        return super().destroy_node()


def main() -> None:
    rclpy.init()
    node = MugunghwaPerception()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
