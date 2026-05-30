"""ultralytics YOLO 추론 캡슐화 — load·device 고정·warm-up·track/predict 분기.

ultralytics 의존성을 이 한 곳에 가둔다 (다른 모듈은 Results 만 안다).
근거: ultralytics 공식 문서 — model.to(device) 로 load 시 고정, warm-up runs 권장,
stream=True 는 source 제너레이터용이라 단일 프레임 수동 루프엔 비해당.
"""
from __future__ import annotations

import numpy as np


class YoloRunner:
    def __init__(self, model, device, imgsz, conf, person_class,
                 tracker_name, half=False, warmup_iters=2):
        self._model = model
        self._model.to(device)          # load 시 device 고정 — 매 호출 device 재해석 방지
        self._device = device
        self._imgsz = imgsz
        self._conf = conf
        self._classes = [person_class]
        self._tracker = tracker_name
        self._half = half
        self._warmup(warmup_iters)

    @classmethod
    def load(cls, model_name, **kw):
        from ultralytics import YOLO   # lazy — 무거운 import 격리
        return cls(YOLO(model_name), **kw)

    def _warmup(self, n):
        if n <= 0:
            return
        dummy = np.zeros((480, 640, 3), np.uint8)   # 카메라 해상도 (shm color 640×480)
        for _ in range(n):
            self._model.predict(dummy, imgsz=self._imgsz, conf=self._conf,
                                 classes=self._classes, device=self._device,
                                 half=self._half, verbose=False)

    def infer(self, frame, *, track: bool):
        """track=True → ByteTrack(track_id) 유지(FOLLOW). False → predict(주행 proximity)."""
        if track:
            return self._model.track(
                frame, persist=True, tracker=self._tracker,
                imgsz=self._imgsz, conf=self._conf, classes=self._classes,
                device=self._device, half=self._half, verbose=False)
        return self._model.predict(
            frame, imgsz=self._imgsz, conf=self._conf, classes=self._classes,
            device=self._device, half=self._half, verbose=False)

    @property
    def device(self):
        return self._device
