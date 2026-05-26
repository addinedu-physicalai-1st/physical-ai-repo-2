"""CNN ReID feature extractor for single-target person identification.

Architecture:
    - Primary: lightweight OSNet via torchreid (osnet_x0_25)
    - Secondary: MobileNetV3-Small embedding path (torchvision)
    - Fallback: 6-float colour statistics (mean+std per BGR channel)

Usage::

    engine = ReIDEngine()
    feat = engine.extract_features(roi_bgr)   # np.ndarray shape (D,)
    sim  = engine.compute_similarity(feat1, feat2)  # float in [-1, 1]
"""

from __future__ import annotations

import logging
from typing import List

import numpy as np

logger = logging.getLogger(__name__)

# ── Optional heavy imports ─────────────────────────────────────────────────────

try:
    import torch
    import torch.nn as nn
    import torchvision.models as models
    import torchvision.transforms as T
    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False
    logger.warning('ReIDEngine: torch not available — falling back to colour stats')

try:
    from torchreid.utils import FeatureExtractor as TorchreidFeatureExtractor
    _TORCHREID_AVAILABLE = True
except ImportError:
    _TORCHREID_AVAILABLE = False


class ReIDEngine:
    """Extract L2-normalised CNN features from a BGR ROI image.

    Parameters
    ----------
    device:
        Torch device string ('cpu', 'cuda'). Defaults to 'cuda' if available,
        else 'cpu'.
    """

    def __init__(self, device: str | None = None) -> None:
        self._use_cnn = _TORCH_AVAILABLE
        self._use_osnet = False
        self._device = None
        self._model = None
        self._transform = None
        self._osnet_extractor = None
        self._feat_dim = 6

        if not self._use_cnn:
            logger.info('ReIDEngine: colour-stats fallback mode')
            return

        self._device = torch.device(
            device if device else ('cuda' if torch.cuda.is_available() else 'cpu')
        )

        # 1) Preferred: lightweight OSNet
        if _TORCHREID_AVAILABLE:
            try:
                self._osnet_extractor = TorchreidFeatureExtractor(
                    model_name='osnet_x0_25',
                    model_path='',
                    device=str(self._device),
                )
                self._use_osnet = True
                self._feat_dim = 512
                logger.info('ReIDEngine: OSNet x0.25 loaded on %s', self._device)
                return
            except Exception as e:
                logger.warning('ReIDEngine: OSNet init failed, fallback to MobileNet: %s', e)

        # 2) Secondary: MobileNetV3-Small
        try:
            backbone = models.mobilenet_v3_small(
                weights=models.MobileNet_V3_Small_Weights.IMAGENET1K_V1
            )
            self._model = nn.Sequential(*list(backbone.children())[:-1])
            self._model.to(self._device)
            self._model.eval()
            self._transform = T.Compose([
                T.ToPILImage(),
                T.Resize((224, 224)),
                T.ToTensor(),
                T.Normalize(mean=[0.485, 0.456, 0.406],
                            std=[0.229, 0.224, 0.225]),
            ])
            self._feat_dim = 1024
            logger.info('ReIDEngine: MobileNetV3-Small loaded on %s', self._device)
        except Exception as e:
            self._use_cnn = False
            self._feat_dim = 6
            logger.warning('ReIDEngine: CNN init failed, using colour stats: %s', e)

    @property
    def feat_dim(self) -> int:
        return self._feat_dim

    def extract_features(self, roi_bgr) -> np.ndarray:
        """Extract L2-normalised feature vector from a BGR image ROI.

        Parameters
        ----------
        roi_bgr:
            numpy ndarray (H, W, 3) in BGR colour order (OpenCV convention).

        Returns
        -------
        np.ndarray
            1-D float32 array, L2-normalised.  Shape: (feat_dim,).
        """
        if roi_bgr is None or roi_bgr.size == 0:
            return np.zeros(self._feat_dim, dtype=np.float32)

        if self._use_cnn:
            return self._cnn_features(roi_bgr)
        return self._colour_stats(roi_bgr)

    def compute_similarity(self, feat_a: np.ndarray, feat_b: np.ndarray) -> float:
        """Cosine similarity between two L2-normalised feature vectors.

        Returns float in [-1, 1].  Both inputs must be L2-normalised.
        """
        try:
            return float(np.dot(feat_a, feat_b))
        except Exception:
            return 0.0

    def extract_with_mask(
        self,
        roi_bgr: np.ndarray,
        depth_mm: np.ndarray,
        target_distance_mm: int,
        tolerance_mm: int = 200,
        min_valid_ratio: float = 0.3,
    ) -> np.ndarray:
        """depth-aware embedding 추출.

        depth pixel 중 [target - tolerance, target + tolerance] mm 범위에 속하는
        pixel 만 살린 BGR ROI 로 embedding 계산. 배경 (벽, 가구 등) 제거.

        valid pixel 비율 < min_valid_ratio 면 mask 안 씌우고 full bbox 사용 (fallback).
        """
        if roi_bgr is None or roi_bgr.size == 0:
            return np.zeros(self._feat_dim, dtype=np.float32)
        if depth_mm is None or depth_mm.size == 0 or depth_mm.shape[:2] != roi_bgr.shape[:2]:
            # depth 없음 / shape 불일치 — full bbox fallback
            return self.extract_features(roi_bgr)

        lo = max(0, int(target_distance_mm) - int(tolerance_mm))
        hi = int(target_distance_mm) + int(tolerance_mm)
        mask = (depth_mm >= lo) & (depth_mm <= hi)
        valid_ratio = float(mask.sum()) / float(mask.size) if mask.size else 0.0
        if valid_ratio < min_valid_ratio:
            return self.extract_features(roi_bgr)

        masked = roi_bgr.copy()
        # mask=False 인 pixel 은 검정 (0) 으로 — embedding 시 배경 정보 손실
        masked[~mask] = 0
        return self.extract_features(masked)

    # ── private ───────────────────────────────────────────────────────────────

    def _cnn_features(self, roi_bgr) -> np.ndarray:
        try:
            import cv2
            if self._use_osnet and self._osnet_extractor is not None:
                rgb = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2RGB)
                feat = self._osnet_extractor([rgb])
                feat = np.asarray(feat).reshape(-1).astype(np.float32)
                norm = np.linalg.norm(feat)
                if norm > 1e-8:
                    feat = feat / norm
                return feat

            rgb = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2RGB)
            tensor = self._transform(rgb).unsqueeze(0).to(self._device)
            with torch.no_grad():
                feat = self._model(tensor)
            feat = feat.squeeze().cpu().numpy().astype(np.float32)
            # L2 normalise
            norm = np.linalg.norm(feat)
            if norm > 1e-8:
                feat = feat / norm
            return feat
        except Exception as e:
            logger.debug('ReIDEngine: CNN inference failed: %s', e)
            return np.zeros(self._feat_dim, dtype=np.float32)

    def _colour_stats(self, roi_bgr) -> np.ndarray:
        """6-float fallback: mean + std per BGR channel."""
        try:
            import cv2
            small = cv2.resize(roi_bgr, (32, 64))
            feats: List[float] = []
            for c in range(3):
                ch = small[:, :, c].astype(np.float32) / 255.0
                feats.append(float(np.mean(ch)))
                feats.append(float(np.std(ch)))
            arr = np.array(feats, dtype=np.float32)
            norm = np.linalg.norm(arr)
            if norm > 1e-8:
                arr = arr / norm
            return arr
        except Exception:
            return np.zeros(self._feat_dim, dtype=np.float32)
