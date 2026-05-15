"""yaml_store.py 의 Lane / save_lanes / lane CRUD 테스트."""
from __future__ import annotations

import pytest
from pathlib import Path


@pytest.fixture
def fake_yaml(tmp_path, monkeypatch):
    """waypoints + lanes yaml 을 임시 경로로 잡아 격리."""
    wp = tmp_path / "waypoints.yaml"
    wp.write_text(
        "waypoints:\n"
        "  - {id: 1, name: A, x: 0.0, y: 0.0, yaw: 0.0}\n"
        "  - {id: 2, name: B, x: 1.0, y: 0.0, yaw: 0.0}\n"
        "patrols: {}\n",
        encoding="utf-8",
    )
    lanes = tmp_path / "lanes.yaml"
    lanes.write_text(
        "lanes:\n"
        "  - {from: A, to: B, bidirectional: true}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PINGDER_WAYPOINTS_FILE", str(wp))
    monkeypatch.setenv("PINGDER_LANES_FILE", str(lanes))
    return wp, lanes


def test_load_lanes_returns_lane_objects(fake_yaml):
    from server.control.waypoints import yaml_store as ys
    lanes = ys.load_lanes()
    assert len(lanes) == 1
    assert isinstance(lanes[0], ys.Lane)
    assert lanes[0].from_ == "A"
    assert lanes[0].to == "B"
    assert lanes[0].bidirectional is True


def test_save_lanes_atomic_write(fake_yaml, tmp_path):
    from server.control.waypoints import yaml_store as ys
    new = [ys.Lane(from_="B", to="A", bidirectional=True)]
    ys.save_lanes(new)
    reloaded = ys.load_lanes()
    assert len(reloaded) == 1
    assert reloaded[0].from_ == "B"
    # tmp 파일이 남아있지 않아야 함
    leftover = list(Path(tmp_path).glob(".lanes-*.tmp"))
    assert leftover == []


def test_save_lanes_validates_unknown_waypoint(fake_yaml):
    from server.control.waypoints import yaml_store as ys
    bad = [ys.Lane(from_="A", to="Z", bidirectional=True)]
    with pytest.raises(ys.LaneStoreError):
        ys.save_lanes(bad)
