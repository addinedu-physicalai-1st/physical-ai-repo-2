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


def test_add_lane_new_pair(tmp_path, monkeypatch):
    from server.control.waypoints import yaml_store as ys
    wp = tmp_path / "waypoints.yaml"
    wp.write_text(
        "waypoints:\n"
        "  - {id: 1, name: A, x: 0.0, y: 0.0, yaw: 0.0}\n"
        "  - {id: 2, name: B, x: 1.0, y: 0.0, yaw: 0.0}\n"
        "patrols: {}\n", encoding="utf-8",
    )
    lanes = tmp_path / "lanes.yaml"
    lanes.write_text("lanes: []\n", encoding="utf-8")
    monkeypatch.setenv("PINGDER_WAYPOINTS_FILE", str(wp))
    monkeypatch.setenv("PINGDER_LANES_FILE", str(lanes))

    ln = ys.add_lane("A", "B")
    assert ln.from_ == "A" and ln.to == "B"
    assert len(ys.load_lanes()) == 1


def test_add_lane_raises_lane_exists(fake_yaml):
    from server.control.waypoints import yaml_store as ys
    # fake_yaml fixture 가 이미 A↔B 양방향 lane 을 가짐
    with pytest.raises(ys.LaneStoreError, match="lane_exists"):
        ys.add_lane("B", "A")
    with pytest.raises(ys.LaneStoreError, match="lane_exists"):
        ys.add_lane("A", "B")


def test_add_lane_unknown_waypoint(fake_yaml):
    from server.control.waypoints import yaml_store as ys
    with pytest.raises(ys.LaneStoreError):
        ys.add_lane("A", "Z")


def test_remove_lane_bidirectional_either_direction(fake_yaml):
    from server.control.waypoints import yaml_store as ys
    # 양방향 A↔B 있으므로 B→A 입력해도 매칭
    ys.remove_lane("B", "A")
    assert ys.load_lanes() == []


def test_remove_lane_missing_raises_keyerror(fake_yaml):
    from server.control.waypoints import yaml_store as ys
    with pytest.raises(KeyError):
        ys.remove_lane("A", "Z")


def test_remove_cascades_lanes(tmp_path, monkeypatch):
    from server.control.waypoints import yaml_store as ys
    wp = tmp_path / "waypoints.yaml"
    wp.write_text(
        "waypoints:\n"
        "  - {id: 1, name: A, x: 0.0, y: 0.0, yaw: 0.0}\n"
        "  - {id: 2, name: B, x: 1.0, y: 0.0, yaw: 0.0}\n"
        "  - {id: 3, name: C, x: 2.0, y: 0.0, yaw: 0.0}\n"
        "patrols: {}\n", encoding="utf-8",
    )
    lanes = tmp_path / "lanes.yaml"
    lanes.write_text(
        "lanes:\n"
        "  - {from: A, to: B, bidirectional: true}\n"
        "  - {from: B, to: C, bidirectional: true}\n"
        "  - {from: A, to: C, bidirectional: true}\n", encoding="utf-8",
    )
    monkeypatch.setenv("PINGDER_WAYPOINTS_FILE", str(wp))
    monkeypatch.setenv("PINGDER_LANES_FILE", str(lanes))

    cascaded = ys.remove("B")
    # B 관련 lane 2개 자동 제거 (A↔B, B↔C). A↔C 보존
    assert len(cascaded) == 2
    remaining = ys.load_lanes()
    assert len(remaining) == 1
    assert remaining[0].from_ == "A" and remaining[0].to == "C"
