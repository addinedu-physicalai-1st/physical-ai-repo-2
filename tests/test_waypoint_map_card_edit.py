"""WaypointMapCard 편집 모드 + 상태머신 + hover + endpoint 호출 검증."""
from __future__ import annotations

import pytest
from pathlib import Path

pytest.importorskip("pytestqt")
pytest.importorskip("PyQt5")


@pytest.fixture
def card(qtbot, tmp_path, monkeypatch):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ui/admin-ui"))
    svg = tmp_path / "admin_map.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 881 720" '
        'width="881" height="720"></svg>',
        encoding="utf-8",
    )
    monkeypatch.setenv("PINGDER_ADMIN_MAP_SVG", str(svg))
    from widgets.waypoint_map_card import WaypointMapCard
    c = WaypointMapCard()
    qtbot.addWidget(c)
    return c


# ---- Task 19: 편집 모드 토글 ----
def test_edit_mode_initially_off(card):
    assert card._map._edit_mode is False
    assert card._map._edit_state == "ready"


def test_edit_mode_toggle_on_when_nav_idle(card, monkeypatch):
    import httpx
    class StubResp:
        status_code = 200
        def json(self): return {"nav_active": False}
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: StubResp())

    card._btn_edit.setChecked(True)
    card._on_edit_toggle()
    assert card._map._edit_mode is True


def test_edit_mode_refuses_when_nav_active(card, monkeypatch):
    import httpx
    class StubResp:
        status_code = 200
        def json(self): return {"nav_active": True}
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: StubResp())
    # QMessageBox 우회
    from PyQt5.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **kw: None))

    card._btn_edit.setChecked(True)
    card._on_edit_toggle()
    assert card._map._edit_mode is False
    assert card._btn_edit.isChecked() is False


def test_edit_mode_off_resets_state(card, monkeypatch):
    card._map._edit_mode = True
    card._map._edit_state = "link_pending"
    card._map._selected_node = "A"
    card._btn_edit.setChecked(False)
    card._on_edit_toggle()
    assert card._map._edit_mode is False
    assert card._map._edit_state == "ready"
    assert card._map._selected_node is None
