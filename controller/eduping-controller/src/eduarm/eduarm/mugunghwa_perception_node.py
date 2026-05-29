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
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from sensor_msgs.msg import Image
from websockets.sync.client import connect as ws_connect

from eduarm.mugunghwa_motion import (
    centroid,
    match_recognize_to_tracks,
    max_displacement,
    select_movers,
)

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
        self.declare_parameter("mover_px", 10.0)
        self.declare_parameter("mover_loose_px", 4.0)
        self.declare_parameter("motion_cooldown_s", 2.0)

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

        from ultralytics import YOLO  # lazy — import 비용 큼
        self._yolo = YOLO(gp("yolo_model").get_parameter_value().string_value)

        self._bridge = CvBridge()
        # 아래 timestamp/inflight 플래그는 단일 스레드 executor(rclpy.spin) 전제 — _on_image
        # 가 한 스레드에서만 호출되므로 lock 없이 안전. MultiThreadedExecutor 로 바꾸면 race.
        self._last_send = 0.0
        self._last_entry = 0.0
        self._last_elim = 0.0

        # 상태: "idle" | "entry" | "observing"
        self._mode = "idle"
        self._tracks: list[dict] = []       # 최신 yolo.track 결과
        self._bindings: dict[int, int] = {}  # track_id → child_id
        self._baseline: dict[int, tuple[float, float]] = {}
        self._state_lock = threading.Lock()
        self._recognize_inflight = False

        self._events = _WsProducer(base + EVENT_PATH, self.get_logger(),
                                   name="mugunghwa-ws-events", on_message=self._on_command)
        self._video = _WsProducer(base + VIDEO_PATH, self.get_logger(),
                                  name="mugunghwa-ws-video")

        self.create_subscription(Image, "/d435/color/image_raw", self._on_image, 1)
        self.get_logger().info("mugunghwa_perception up")

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

        if mode == "entry":
            self._maybe_recognize(bgr, tracks)
        elif mode == "observing":
            self._judge_movers(tracks)

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

    # ---- observation: 변위 판정 ----
    def _judge_movers(self, tracks: list[dict]) -> None:
        with self._state_lock:
            baseline = dict(self._baseline)
            bindings = dict(self._bindings)
        movers = select_movers(tracks, baseline, bindings,
                               self._mover_px, self._mover_loose_px)
        max_disp = max_displacement(tracks, baseline)
        now = time.monotonic()
        if now - self._last_elim < self._cooldown_s:
            return
        if movers:
            self._last_elim = now
            self._emit({"type": "eliminated", "child_ids": movers})
        elif max_disp >= self._mover_loose_px:
            self._last_elim = now
            self._emit({"type": "motion"})  # 미식별 — 브라우저 flash + 교사 ✕

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
