import numpy as np
from gogoping_perception.proximity import nearest_person_distance_m, ProximityCfg

CFG = ProximityCfg(fx=615.0, cx=320.0, forward_m=0.6, lateral_m=0.5)

class _Tensor:
    def __init__(self, a): self._a = np.array(a, dtype=float)
    def cpu(self): return self
    def numpy(self): return self._a
    def __len__(self): return len(self._a)
class _Boxes:
    def __init__(self, xyxy): self.xyxy = _Tensor(xyxy)
class _Result:
    def __init__(self, xyxy): self.boxes = _Boxes(xyxy) if xyxy is not None else None

def test_no_results_returns_inf():
    assert nearest_person_distance_m([], np.ones((480,640),np.uint16)*1500, CFG) == float("inf")

def test_no_boxes_returns_inf():
    assert nearest_person_distance_m([_Result(None)], np.ones((480,640),np.uint16)*1500, CFG) == float("inf")

def test_person_far_outside_box_returns_inf():
    # 8m 거리 박스 (forward_m=0.6 박스 밖) → inf
    depth = np.ones((480,640), np.uint16) * 8000
    res = [_Result([[300,200,340,400]])]
    assert nearest_person_distance_m(res, depth, CFG) == float("inf")

def test_person_inside_box_returns_finite():
    # 정면 중앙 0.5m → 박스 안 → 유한값
    depth = np.ones((480,640), np.uint16) * 500
    res = [_Result([[300,200,340,400]])]
    d = nearest_person_distance_m(res, depth, CFG)
    assert np.isfinite(d) and d > 0
