"""phase5 ROI masking — 학습 시 omx_store_play/scripts/gen_roi_masked_videos_phase5.py
와 동일 로직을 inference 시점에 재현.

학습 데이터 (minssuung/store_play_v2_en_phase5_roi) 가 다음 절차로 만들어졌으므로,
추론 시 같은 처리 안 하면 ACT 가 학습 분포 밖 입력을 받게 됨.

흐름:
  1) prompt → target fruit 추출 (e.g. "give me strawberry" → "strawberry")
  2) 각 카메라 frame 에 YOLO R8 (7-class) inference
  3) cam 별 정책에 따라 bbox 선택:
       top:         target fruit + plate (top-2)
       wrist_left:  plate only (top-2)
       wrist_right: target fruit + bell_button
  4) bbox 외부 = 검정, bbox + pad(20px) 안만 원본 → masked image

학습 코드 (gen_roi_masked_videos_phase5.py) 와 1:1 로직. 매개변수 (conf, iou, pad,
class 순서) 도 그대로. YOLO R8 모델 경로는 build_roi_masker 인자로 받음.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

# 학습 코드의 7-class 순서 — index 그대로 사용.
YOLO_CLASSES: tuple[str, ...] = (
    "strawberry", "broccoli", "grape", "kiwi", "pineapple", "bell_button", "plate",
)
FRUITS: tuple[str, ...] = ("strawberry", "broccoli", "grape", "kiwi", "pineapple")

# plate 2번째 인스턴스는 이 conf 이상일 때만 keep — 학습(gen_roi_masked_videos_phase5.py)
# / 추론(roi_inference.py) 의 PLATE_CONF_2ND 와 동일. 1번째는 기본 conf(0.25).
PLATE_CONF_2ND: float = 0.55

# 카메라별 keep 정책 — 학습 코드와 동일.
CAM_POLICY: dict[str, dict[str, Any]] = {
    "top":         {"keep_target_fruit": True,  "always_keep": ["plate"]},
    "wrist_left":  {"keep_target_fruit": False, "always_keep": ["plate"]},
    "wrist_right": {"keep_target_fruit": True,  "always_keep": ["bell_button"]},
}


def prompt_to_target(prompt: str) -> str | None:
    """학습 시 동일 매핑: 'give me strawberry' → 'strawberry'.
    길이순 정렬로 'pineapple' 이 'apple' 같은 substring 충돌 회피.
    """
    p = (prompt or "").lower().strip()
    for c in sorted(FRUITS, key=len, reverse=True):
        if c in p:
            return c
    return None


def _select_bboxes(result: Any, always_keep: list[str], target_fruit: str | None) -> list[tuple]:
    """학습 코드 select_bboxes_phase5 1:1 재현.
    - plate: 1번째 기본 conf, 2번째는 PLATE_CONF_2ND(0.55) 이상만 (dual threshold)
    - bell_button + 그 외 always_keep: top-1
    - target fruit: top-1
    """
    bboxes: list[tuple] = []
    if result.boxes is None or len(result.boxes) == 0:
        return bboxes
    boxes = result.boxes.xyxy.cpu().numpy()
    cls_ids = result.boxes.cls.cpu().numpy().astype(int)
    confs = result.boxes.conf.cpu().numpy()

    def box_tuple(i: int) -> tuple:
        x1, y1, x2, y2 = boxes[i]
        return (float(x1), float(y1), float(x2), float(y2))

    # plate: dual conf threshold (1번째 기본 conf, 2번째 ≥0.55) — 학습/roi_inference 와 동일.
    if "plate" in always_keep:
        plate_id = YOLO_CLASSES.index("plate")
        plate_idxs = [i for i, c in enumerate(cls_ids) if int(c) == plate_id]
        plate_idxs.sort(key=lambda i: -confs[i])
        if plate_idxs:
            bboxes.append(box_tuple(plate_idxs[0]))
        if len(plate_idxs) >= 2 and confs[plate_idxs[1]] >= PLATE_CONF_2ND:
            bboxes.append(box_tuple(plate_idxs[1]))
    # bell_button (및 plate 아닌 always_keep): best 1
    for cls in always_keep:
        if cls == "plate":
            continue
        cid_target = YOLO_CLASSES.index(cls)
        best_conf, best_i = -1.0, None
        for i, cid in enumerate(cls_ids):
            if int(cid) == cid_target and confs[i] > best_conf:
                best_conf = confs[i]
                best_i = i
        if best_i is not None:
            bboxes.append(box_tuple(best_i))
    # target fruit: best 1
    if target_fruit is not None:
        target_id = YOLO_CLASSES.index(target_fruit)
        best_conf, best_i = -1.0, None
        for i, cid in enumerate(cls_ids):
            if int(cid) == target_id and confs[i] > best_conf:
                best_conf = confs[i]
                best_i = i
        if best_i is not None:
            bboxes.append(box_tuple(best_i))
    return bboxes


def _apply_roi_mask(
    img_bgr_or_rgb: np.ndarray,
    bboxes_pixel: list[tuple],
    *,
    pad: int,
    W: int,
    H: int,
) -> np.ndarray:
    """bbox 외부 = 검정, bbox + pad 안만 원본. 학습 코드 apply_roi_mask 1:1.

    Color order (BGR/RGB) 는 보존 — img.copy 안 하고 zeros_like 로 동일 shape 새 array.
    """
    out = np.zeros_like(img_bgr_or_rgb)
    for bbox in bboxes_pixel:
        if bbox is None:
            continue
        x1, y1, x2, y2 = bbox
        x1 = max(0, int(x1) - pad)
        y1 = max(0, int(y1) - pad)
        x2 = min(W, int(x2) + pad)
        y2 = min(H, int(y2) + pad)
        if x2 <= x1 or y2 <= y1:
            continue
        out[y1:y2, x1:x2] = img_bgr_or_rgb[y1:y2, x1:x2]
    return out


@dataclass
class RoiMasker:
    """YOLO 1회 로드 + 매 frame 호출.

    `mask_images(images, task)` 가 cam 별 mask 적용된 dict 반환.
    """
    yolo: Any
    conf: float
    iou: float
    pad: int
    cam_policy: dict[str, dict[str, Any]]
    last_detected: set = field(default_factory=set)  # 직전 mask_images 검출 class.

    def mask_images(
        self,
        images: dict[str, np.ndarray],
        task: str,
    ) -> dict[str, np.ndarray]:
        """images: {hw_cam_key: HWC uint8 **RGB** ndarray (lerobot OpenCVCamera 기본)}.
        ROI masked RGB 반환 (모델 입력용, 색공간 유지).

        ⚠️ YOLO(ultralytics) 는 입력을 BGR 로 가정한다. lerobot 카메라는 RGB 를 주므로
        detect 전에 RGB→BGR 변환 필수 (안 하면 빨간 딸기가 파랑으로 보여 conf 0).
        roi_inference.py / gen_roi_masked_videos_phase5.py 와 동일 — 거기도 cvtColor 함.
        mask 자체는 원본 RGB 에 적용 (모델은 RGB 학습).

        hw_cam_key 는 cam_policy 키 (top/wrist_left/wrist_right) — image_key_map 으로
        외부에서 매핑된 결과를 받는다고 가정.
        """
        import cv2  # lazy — ultralytics 의존이라 이미 설치됨.

        target = prompt_to_target(task)
        out: dict[str, np.ndarray] = {}
        detected: set[str] = set()  # 이번 호출에서 검출된 class (전체 cam 합집합) — 객체없음 감지용.
        for cam_key, img in images.items():
            policy = self.cam_policy.get(cam_key)
            if policy is None:
                # 정책 모르면 mask 안 함 — 그대로 통과 (안전 디폴트).
                out[cam_key] = img
                continue
            H, W = img.shape[:2]
            img_bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)  # YOLO 용 BGR
            results = self.yolo.predict(img_bgr, conf=self.conf, iou=self.iou, verbose=False)
            r = results[0]
            if r.boxes is not None and len(r.boxes):
                for cid in r.boxes.cls.cpu().numpy().astype(int):
                    detected.add(YOLO_CLASSES[int(cid)])
            target_fruit = target if policy["keep_target_fruit"] else None
            bboxes = _select_bboxes(r, policy["always_keep"], target_fruit)
            out[cam_key] = _apply_roi_mask(img, bboxes, pad=self.pad, W=W, H=H)  # mask 는 원본 RGB
        self.last_detected = detected  # runner 가 읽어 target/plate 미검출 판단.
        return out


def build_roi_masker(
    *,
    yolo_weights: str,
    conf: float = 0.25,
    iou: float = 0.5,
    pad: int = 20,
    cam_policy: dict[str, dict[str, Any]] | None = None,
) -> RoiMasker:
    """YOLO 가중치 load (1회). 결과 RoiMasker 는 thread-safe 아님 — 단일 thread 호출."""
    from ultralytics import YOLO  # type: ignore[import-not-found]

    yolo = YOLO(yolo_weights)
    return RoiMasker(
        yolo=yolo,
        conf=float(conf),
        iou=float(iou),
        pad=int(pad),
        cam_policy=cam_policy or CAM_POLICY,
    )


__all__ = [
    "YOLO_CLASSES", "FRUITS", "CAM_POLICY",
    "prompt_to_target", "RoiMasker", "build_roi_masker",
]
