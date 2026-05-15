import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]
    / "controller/gogoping-controller/src/gogoping/gogoping_navigation/scripts"))

import pytest
import utils_geo as ug


def test_raster_to_map_origin():
    # raster (0, 720) (좌하단 픽셀) → map (-11, -9) (origin)
    mx, my = ug.raster_to_map(0.0, 720.0)
    assert mx == pytest.approx(-11.0, abs=1e-6)
    assert my == pytest.approx(-9.0, abs=1e-6)


def test_raster_to_map_top_right():
    mx, my = ug.raster_to_map(881.0, 0.0)
    assert mx == pytest.approx(-11.0 + 881 * 0.025, abs=1e-6)
    assert my == pytest.approx(-9.0 + 720 * 0.025, abs=1e-6)


def test_map_to_raster_roundtrip():
    for rx, ry in [(0.0, 720.0), (100.5, 200.3), (881.0, 0.0)]:
        mx, my = ug.raster_to_map(rx, ry)
        rx2, ry2 = ug.map_to_raster(mx, my)
        assert rx2 == pytest.approx(rx, abs=1e-6)
        assert ry2 == pytest.approx(ry, abs=1e-6)


def test_map_to_svg_1to1():
    # SVG 가 raster 와 같은 크기이면 픽셀 좌표 동일
    sx, sy = ug.map_to_svg(-11.0, -9.0, 881, 720)
    assert sx == pytest.approx(0.0, abs=1e-3)
    assert sy == pytest.approx(720.0, abs=1e-3)


def test_svg_to_map_roundtrip():
    for mx, my in [(0.0, 0.0), (-5.5, 3.2), (1.0, -7.0)]:
        sx, sy = ug.map_to_svg(mx, my, 881, 720)
        mx2, my2 = ug.svg_to_map(sx, sy, 881, 720)
        assert mx2 == pytest.approx(mx, abs=1e-6)
        assert my2 == pytest.approx(my, abs=1e-6)
