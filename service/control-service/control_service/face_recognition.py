"""InsightFace 기반 얼굴 임베딩 추출 — 싱글톤 lazy init."""
from __future__ import annotations

import io
import threading
from typing import Optional

import numpy as np

_lock = threading.Lock()
_app = None  # type: ignore[var-annotated]


def get_app():
    """InsightFace FaceAnalysis 앱 (CPU). 첫 호출 시 모델 로딩."""
    global _app
    if _app is None:
        with _lock:
            if _app is None:
                from insightface.app import FaceAnalysis  # noqa: WPS433

                app = FaceAnalysis(
                    name="buffalo_l",
                    providers=["CPUExecutionProvider"],
                )
                app.prepare(ctx_id=-1, det_size=(640, 640))
                _app = app
    return _app


def _decode_image(data: bytes) -> np.ndarray:
    import cv2  # noqa: WPS433

    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("이미지 디코딩 실패")
    return img


def extract_embedding(image_bytes: bytes) -> Optional[list[float]]:
    """이미지에서 가장 큰 얼굴의 512-d 임베딩 반환. 디코딩 실패·얼굴 없으면 None."""
    try:
        img = _decode_image(image_bytes)
    except ValueError:
        return None
    faces = get_app().get(img)
    if not faces:
        return None
    # 가장 큰 박스 (면적 기준)
    faces.sort(
        key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]),
        reverse=True,
    )
    emb = faces[0].normed_embedding  # L2-normalized 512-d
    return emb.astype(float).tolist()


def extract_embeddings_all(image_bytes: bytes) -> list[dict]:
    """이미지에 보이는 모든 얼굴의 (embedding, bbox) 리스트.

    각 dict 는 {'embedding': list[float] (512-d, L2-normalized),
                'bbox': [x1, y1, x2, y2] (입력 이미지 pixel 좌표)}.

    SR-PLAY-004 무궁화 진입 단계에서 한 프레임에 여러 명이 동시에 보일 때 사용.
    bbox 는 클라이언트가 같은 프레임에서 얼굴 썸네일을 크롭하기 위한 정보.
    """
    try:
        img = _decode_image(image_bytes)
    except ValueError:
        return []
    faces = get_app().get(img)
    return [
        {
            "embedding": f.normed_embedding.astype(float).tolist(),
            "bbox": [float(x) for x in f.bbox],
        }
        for f in faces
    ]
