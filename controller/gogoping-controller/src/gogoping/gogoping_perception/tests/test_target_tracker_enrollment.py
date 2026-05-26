"""enrollment FSM unit tests — set_face_template, start_enrollment, accumulate_body, finalize_enrollment."""
import numpy as np
import pytest

from gogoping_perception.target_tracker import TargetTracker


class _FakeReID:
    """ReIDEngine stub — cosine similarity 만 수행."""
    def compute_similarity(self, a, b):
        return float(np.dot(a, b))


def _emb(seed: int, dim: int = 512) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float32)
    return v / max(np.linalg.norm(v), 1e-8)


def test_initial_state_is_idle():
    t = TargetTracker(_FakeReID())
    assert t.state == "IDLE"
    assert t.has_target() is False


def test_set_face_template_keeps_idle():
    t = TargetTracker(_FakeReID())
    face_emb = _emb(1)
    t.set_face_template(face_emb)
    # face emb 저장은 됐지만 enrollment 시작 전엔 IDLE
    assert t.state == "IDLE"
    assert t.has_target() is False


def test_start_enrollment_transitions_to_enrolling():
    t = TargetTracker(_FakeReID())
    t.set_face_template(_emb(1))
    t.start_enrollment(target_n=15)
    assert t.state == "ENROLLING"
    assert t.has_target() is True  # enrollment 중에도 target 있는 걸로 본다 (face emb fallback)


def test_accumulate_and_finalize_avg_normalized():
    t = TargetTracker(_FakeReID())
    t.set_face_template(_emb(1))
    t.start_enrollment(target_n=3)
    # 3개 body emb 누적
    e1, e2, e3 = _emb(10), _emb(20), _emb(30)
    t.accumulate_body(e1)
    assert t.state == "ENROLLING"
    t.accumulate_body(e2)
    assert t.state == "ENROLLING"
    t.accumulate_body(e3)
    # N=3 도달 → finalize 자동 호출 후 ACTIVE
    assert t.state == "ACTIVE"
    # body_template 은 (e1+e2+e3)/3 의 L2-normalized
    expected = (e1 + e2 + e3) / 3.0
    expected = expected / np.linalg.norm(expected)
    assert np.allclose(t._body_template, expected, atol=1e-6)


def test_finalize_with_no_accumulated_falls_back_to_face():
    t = TargetTracker(_FakeReID())
    face_emb = _emb(1)
    t.set_face_template(face_emb)
    t.start_enrollment(target_n=15)
    # accumulate 없이 timeout 흉내 — finalize_enrollment(force=True)
    t.finalize_enrollment(force=True)
    # body emb 없으므로 face emb 로 fallback. state 는 ACTIVE 지만 body_template = face_template.
    assert t.state == "ACTIVE"
    assert np.allclose(t._body_template, face_emb, atol=1e-6)


def test_clear_target_resets_to_idle():
    t = TargetTracker(_FakeReID())
    t.set_face_template(_emb(1))
    t.start_enrollment(target_n=3)
    t.accumulate_body(_emb(10))
    t.clear_target()
    assert t.state == "IDLE"
    assert t.has_target() is False
