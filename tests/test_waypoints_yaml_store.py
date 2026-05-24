import math
import os
import pytest
from pathlib import Path


@pytest.fixture
def tmp_yaml(tmp_path, monkeypatch):
    p = tmp_path / "waypoints.yaml"
    monkeypatch.setenv("PINGDER_WAYPOINTS_FILE", str(p))
    import importlib
    import control_service.waypoints.yaml_store as ys
    importlib.reload(ys)
    return p, ys


# ---- Task 5: load ----
def test_load_missing_file_returns_empty(tmp_yaml):
    _, ys = tmp_yaml
    wps, patrols = ys.load()
    assert wps == []
    assert patrols == {}


def test_load_empty_yaml_returns_empty(tmp_yaml):
    p, ys = tmp_yaml
    p.write_text("", encoding="utf-8")
    wps, patrols = ys.load()
    assert wps == []
    assert patrols == {}


# ---- Task 6: save ----
def test_save_roundtrip(tmp_yaml):
    _, ys = tmp_yaml
    wps = [ys.Waypoint(name="수면실", x=-3.05, y=3.40, yaw=1.5708)]
    patrols = {"hide_and_seek_search": ["수면실"]}
    ys.save(wps, patrols)
    wps2, patrols2 = ys.load()
    assert wps2 == wps
    assert patrols2 == patrols


def test_save_atomic_no_tmp_leftover(tmp_yaml):
    p, ys = tmp_yaml
    ys.save([ys.Waypoint("a", 0, 0, 0)], {})
    leftovers = [f for f in p.parent.iterdir()
                 if f.name.startswith(".") and f.suffix == ".tmp"]
    assert leftovers == []


# ---- Task 7: add/remove/get/get_patrol ----
def test_add_appends(tmp_yaml):
    _, ys = tmp_yaml
    ys.save([], {})
    wp = ys.add("수면실", -3.05, 3.40, 1.57)
    assert wp.name == "수면실"
    wps, _ = ys.load()
    assert [w.name for w in wps] == ["수면실"]


def test_add_rejects_duplicate(tmp_yaml):
    _, ys = tmp_yaml
    ys.save([ys.Waypoint("수면실", 0, 0, 0)], {})
    with pytest.raises(ys.WaypointStoreError, match="중복"):
        ys.add("수면실", 1, 1, 1)


def test_add_rejects_nan(tmp_yaml):
    _, ys = tmp_yaml
    ys.save([], {})
    with pytest.raises(ys.WaypointStoreError, match="NaN/Inf"):
        ys.add("bad", float("nan"), 0, 0)


def test_add_rejects_empty_name(tmp_yaml):
    _, ys = tmp_yaml
    ys.save([], {})
    with pytest.raises(ys.WaypointStoreError):
        ys.add("   ", 0, 0, 0)


def test_remove_removes(tmp_yaml):
    _, ys = tmp_yaml
    ys.save([ys.Waypoint("수면실", 0, 0, 0)], {})
    ys.remove("수면실")
    wps, _ = ys.load()
    assert wps == []


def test_remove_rejects_patrol_reference(tmp_yaml):
    _, ys = tmp_yaml
    ys.save(
        [ys.Waypoint("수면실", 0, 0, 0)],
        {"hide_and_seek_search": ["수면실"]},
    )
    with pytest.raises(ys.WaypointStoreError, match="patrol"):
        ys.remove("수면실")


def test_get_returns_waypoint(tmp_yaml):
    _, ys = tmp_yaml
    ys.save([ys.Waypoint("수면실", -3.05, 3.40, 1.57)], {})
    wp = ys.get("수면실")
    assert wp.x == pytest.approx(-3.05)


def test_get_raises_for_missing(tmp_yaml):
    _, ys = tmp_yaml
    ys.save([], {})
    with pytest.raises(KeyError):
        ys.get("없는이름")


def test_get_patrol_resolves(tmp_yaml):
    _, ys = tmp_yaml
    ys.save(
        [ys.Waypoint("a", 1, 2, 0), ys.Waypoint("b", 3, 4, 0)],
        {"p1": ["a", "b"]},
    )
    members = ys.get_patrol("p1")
    assert [m.name for m in members] == ["a", "b"]


# ---- Task 3: update (노드 이동) ----
def test_update_moves_existing_waypoint(tmp_yaml):
    _, ys = tmp_yaml
    ys.save([ys.Waypoint("A", 0.0, 0.0, 0.0)], {})
    updated = ys.update("A", 3.0, 4.0, 1.57)
    assert updated.x == 3.0 and updated.y == 4.0 and updated.yaw == 1.57
    reloaded = ys.get("A")
    assert reloaded.x == 3.0


def test_update_unknown_raises(tmp_yaml):
    _, ys = tmp_yaml
    ys.save([], {})
    with pytest.raises(KeyError):
        ys.update("Z", 0.0, 0.0, 0.0)


# ---- multi-step undo (snapshot stack) ----
def test_undo_restores_previous_state(tmp_yaml):
    _, ys = tmp_yaml
    ys.clear_undo_stack()
    ys.save([], {})  # 빈 상태
    ys.push_snapshot()
    ys.add("X", 0.0, 0.0, 0.0)
    assert len(ys.load()[0]) == 1
    snap = ys.undo()
    assert snap is not None
    assert ys.load()[0] == []


def test_undo_multi_step(tmp_yaml):
    """순서 add A → add B → undo → undo 시 빈 상태로 복원."""
    _, ys = tmp_yaml
    ys.clear_undo_stack()
    ys.save([], {})
    ys.push_snapshot(); ys.add("A", 1.0, 0.0, 0.0)
    ys.push_snapshot(); ys.add("B", 2.0, 0.0, 0.0)
    assert len(ys.load()[0]) == 2
    ys.undo()
    names = [w.name for w in ys.load()[0]]
    assert names == ["A"]
    ys.undo()
    assert ys.load()[0] == []


def test_undo_returns_none_when_empty(tmp_yaml):
    _, ys = tmp_yaml
    ys.clear_undo_stack()
    assert ys.undo() is None


# ---- group 필드 ----
def test_save_roundtrip_with_group(tmp_yaml):
    """group 필드 (선택) 저장/로드 라운드트립."""
    _, ys = tmp_yaml
    wps = [
        ys.Waypoint(name="놀이방", x=0.0, y=0.0, yaw=0.0, group="놀이방"),
        ys.Waypoint(name="복도1", x=0.5, y=2.0, yaw=0.0, group=None),  # 그룹 없음
    ]
    ys.save(wps, {})
    wps2, _ = ys.load()
    assert wps2[0].group == "놀이방"
    assert wps2[1].group is None


def test_validate_rejects_empty_group_string(tmp_yaml):
    """group="" 같은 빈 문자열은 거부 (null 만 허용)."""
    _, ys = tmp_yaml
    with pytest.raises(ys.WaypointStoreError):
        ys.validate({
            "waypoints": [
                {"name": "x", "x": 0.0, "y": 0.0, "yaw": 0.0, "group": ""},
            ],
            "patrols": {},
        })


def test_load_yaml_without_group_field_ok(tmp_yaml):
    """기존 yaml (group 필드 없는) 로드 회귀 — group=None 으로 통과."""
    p, ys = tmp_yaml
    p.write_text(
        "waypoints:\n- name: a\n  x: 0.0\n  y: 0.0\n  yaw: 0.0\npatrols: {}\n",
        encoding="utf-8",
    )
    wps, _ = ys.load()
    assert wps[0].group is None
