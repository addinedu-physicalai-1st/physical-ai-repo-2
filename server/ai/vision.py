"""AI Hub vision 추론 — task 기반 stateless 서비스.

브라우저 → Control Server → AI Hub 로 JPEG 프레임이 forward 되면 해당 task 의 YOLO
모델로 추론해 bbox JSON 으로 응답한다. 새 task 추가 = `VisionTask` 서브클래스 한 개 +
`hub.py` 에서 `register()` 한 줄.

각 task 는 자기 모델 인스턴스를 lazy load 해 보유 (CLIP txt_feats 캐시 분리).

현재 등록 task:
- ox-board : 단일 클래스 ("printed red blue OX sign board") + 좌우 색 분할 (O/X)
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

import cv2
import numpy as np

if TYPE_CHECKING:
    from ultralytics import YOLO  # noqa: F401

logger = logging.getLogger(__name__)

# 가중치는 AI Hub 옆 `server/ai/models/` 에 둠 (gitignored — 첫 실행 시 ultralytics 가
# 자동 다운로드). 절대 경로로 넘겨 cwd 와 무관하게 같은 파일을 쓴다.
_AI_DIR = Path(__file__).resolve().parent
DEFAULT_MODEL = str(_AI_DIR / "models" / "yolov8s-worldv2.pt")


class VisionTask:
    """Base — task 별로 서브클래싱 (classes, conf, postprocess override).

    `infer()` 가 모델 lazy load + 예측 + postprocess 를 수행한다. 모델 인스턴스는 task
    별로 분리되어 있어 set_classes 로 인한 CLIP txt_feats 캐시 충돌 없음.
    """

    name: str = ""                        # URL slug, 예: "ox-board"
    model_name: str = DEFAULT_MODEL
    classes: tuple[str, ...] = ()
    conf: float = 0.5

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._model: "YOLO | None" = None
        self._device: str = "cpu"

    def infer(self, jpeg_bytes: bytes) -> dict:
        """JPEG → 검출 결과 dict (boxes, inference_ms, frame_size)."""
        self._ensure_loaded()
        arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("invalid jpeg payload")
        t0 = time.perf_counter()
        with self._lock:
            assert self._model is not None
            results = self._model.predict(frame, conf=self.conf, verbose=False)[0]
        ms = (time.perf_counter() - t0) * 1000
        h, w = frame.shape[:2]
        return {
            "task": self.name,
            "boxes": self.postprocess(frame, results),
            "inference_ms": round(ms, 2),
            "frame_size": [w, h],
        }

    def postprocess(self, frame: np.ndarray, results) -> list[dict]:
        """Default — raw bbox + label. Override for task-specific logic (예: OX 색 분할)."""
        out: list[dict] = []
        for box in results.boxes:
            x1, y1, x2, y2 = box.xyxy[0].int().tolist()
            cls_id = int(box.cls[0])
            label = self.classes[cls_id] if cls_id < len(self.classes) else str(cls_id)
            out.append({
                "score": round(float(box.conf[0]), 4),
                "bbox": [x1, y1, x2, y2],
                "label": label,
            })
        return out

    # --- 내부 ---

    def _ensure_loaded(self) -> None:
        with self._lock:
            if self._model is not None:
                return
            import torch
            from ultralytics import YOLO

            self._device = "cuda" if torch.cuda.is_available() else "cpu"
            logger.info(
                "vision[%s]: %s 로드 (device=%s)",
                self.name, self.model_name, self._device,
            )
            self._model = YOLO(self.model_name)
            self._set_classes_locked(list(self.classes))

    def _set_classes_locked(self, classes: list[str]) -> None:
        """ultralytics+CLIP CUDA mismatch 워크어라운드 — 호출자가 lock 보유 가정."""
        import torch

        assert self._model is not None
        self._model.to("cpu")
        self._model.set_classes(classes)
        if self._device == "cpu":
            return
        self._model.to(self._device)
        for sub in self._model.model.modules():
            feats = getattr(sub, "txt_feats", None)
            if isinstance(feats, torch.Tensor):
                sub.txt_feats = feats.to(self._device)


class OXBoardTask(VisionTask):
    """OX 보드 단일 클래스 검출 + bbox 좌우 색 평균으로 O/X 분할."""

    name = "ox-board"
    classes = ("printed red blue OX sign board",)
    # 인쇄된 색 채움 보드가 시각적으로 매우 강한 신호 — false positive 줄이려 0.9 로 높게.
    # 손이 일부 가려서 일시 미검출 되어도 UI 측 freeze (손이 bbox 안에 있으면 갱신 X) 가
    # 깜빡임 방지.
    conf = 0.9

    def postprocess(self, frame: np.ndarray, results) -> list[dict]:
        out: list[dict] = []
        for box in results.boxes:
            x1, y1, x2, y2 = box.xyxy[0].int().tolist()
            o_box, x_box = _split_by_color(frame, x1, y1, x2, y2)
            out.append({
                "score": round(float(box.conf[0]), 4),
                "bbox": [x1, y1, x2, y2],
                "parts": {"O": list(o_box), "X": list(x_box)},
            })
        return out


def _split_by_color(
    frame: np.ndarray, x1: int, y1: int, x2: int, y2: int,
) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:
    """보드 bbox 가운데 세로 분할 → 더 파란 쪽 = O, 더 빨간 쪽 = X."""
    cx = (x1 + x2) // 2
    left = frame[y1:y2, x1:cx]
    right = frame[y1:y2, cx:x2]
    if left.size == 0 or right.size == 0:
        return (x1, y1, cx, y2), (cx, y1, x2, y2)
    l_b, _, l_r = left.reshape(-1, 3).mean(axis=0)
    r_b, _, r_r = right.reshape(-1, 3).mean(axis=0)
    if (l_b - l_r) > (r_b - r_r):
        return (x1, y1, cx, y2), (cx, y1, x2, y2)
    return (cx, y1, x2, y2), (x1, y1, cx, y2)


class VisionRegistry:
    """싱글톤 — 등록된 task 들을 name 으로 lookup. AI Hub 시작 시 register."""

    def __init__(self) -> None:
        self._tasks: dict[str, VisionTask] = {}

    def register(self, task: VisionTask) -> None:
        if not task.name:
            raise ValueError(f"task name 필수: {task!r}")
        if task.name in self._tasks:
            raise ValueError(f"중복 task name: {task.name}")
        self._tasks[task.name] = task
        logger.info("vision: task '%s' 등록", task.name)

    def get(self, name: str) -> VisionTask | None:
        return self._tasks.get(name)

    def names(self) -> list[str]:
        return list(self._tasks)

    def list_tasks(self) -> list[dict]:
        return [
            {
                "name": t.name,
                "model": t.model_name,
                "classes": list(t.classes),
                "conf": t.conf,
            }
            for t in self._tasks.values()
        ]

    def shutdown(self) -> None:
        """현재는 cleanup 할 백그라운드 자원 없음 (stateless). 후속 확장 hook."""
        return


# AI Hub 가 import 시점에 만들어 사용. hub.py 가 register 함.
default_registry = VisionRegistry()
