from gogoping_perception.yolo_runner import YoloRunner

class FakeModel:
    def __init__(self):
        self.calls = []          # [("predict"|"track", kwargs), ...]
        self.to_device = None
    def to(self, d):
        self.to_device = d; return self
    def predict(self, frame, **kw):
        self.calls.append(("predict", kw)); return ["pred"]
    def track(self, frame, **kw):
        self.calls.append(("track", kw)); return ["trk"]

def _make(model, **over):
    kw = dict(device="cuda:0", imgsz=640, conf=0.2, person_class=0,
              tracker_name="bytetrack.yaml", half=False, warmup_iters=0)
    kw.update(over)
    return YoloRunner(model, **kw)

def test_device_pinned_at_load():
    m = FakeModel(); _make(m)
    assert m.to_device == "cuda:0"

def test_warmup_runs_n_predicts():
    m = FakeModel(); _make(m, warmup_iters=2)
    assert sum(1 for c in m.calls if c[0] == "predict") == 2

def test_infer_track_true_calls_track():
    m = FakeModel(); r = _make(m)
    out = r.infer("frame", track=True)
    assert out == ["trk"] and m.calls[-1][0] == "track"
    assert m.calls[-1][1]["persist"] is True

def test_infer_track_false_calls_predict():
    m = FakeModel(); r = _make(m)
    out = r.infer("frame", track=False)
    assert out == ["pred"] and m.calls[-1][0] == "predict"

def test_infer_passes_conf_imgsz_device_classes():
    m = FakeModel(); r = _make(m)
    r.infer("frame", track=False)
    kw = m.calls[-1][1]
    assert kw["conf"] == 0.2 and kw["imgsz"] == 640
    assert kw["device"] == "cuda:0" and kw["classes"] == [0]
