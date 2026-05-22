"""follow API 스키마 형상 — payload 는 teacher_id only (embedding 은 backend lookup)."""
import pytest
from uuid import uuid4

from control_service.schemas import (
    FollowStartPayload,
    FollowStopPayload,
    FollowStateOut,
)


def test_follow_start_payload_requires_only_teacher_id():
    obj = FollowStartPayload(teacher_id=uuid4())
    assert obj.teacher_id is not None


def test_follow_start_payload_rejects_missing_teacher_id():
    with pytest.raises(ValueError):
        FollowStartPayload()


def test_follow_stop_payload_empty_ok():
    FollowStopPayload()


def test_follow_state_out_default_idle():
    obj = FollowStateOut(active=False)
    assert obj.active is False
    assert obj.teacher_id is None
    assert obj.matched is False


def test_follow_state_out_includes_bbox_and_track_fields():
    obj = FollowStateOut(
        active=True,
        bbox_x1=100, bbox_y1=120, bbox_x2=300, bbox_y2=400,
        track_id=7, reid_sim=0.92,
    )
    assert obj.bbox_x1 == 100
    assert obj.track_id == 7
    assert obj.reid_sim == 0.92
