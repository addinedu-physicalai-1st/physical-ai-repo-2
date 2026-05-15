import json
import sys
from pathlib import Path

import pytest
import httpx
from unittest.mock import patch, MagicMock

# 모듈 경로 PYTHONPATH 추가
_GOGOPING_MODES = (Path(__file__).resolve().parents[1]
                   / "controller/gogoping-controller/src/gogoping/gogoping_modes")
sys.path.insert(0, str(_GOGOPING_MODES))


@pytest.fixture
def client_mod(tmp_path, monkeypatch):
    monkeypatch.setenv("PINGDER_BT_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("PINGDER_CONTROL_URL", "http://mock")
    import importlib
    from gogoping_modes.utils import waypoints_client as wc
    importlib.reload(wc)
    return wc


def test_fetch_uses_response_and_writes_cache(client_mod, tmp_path):
    fake = {"waypoints": [{"name": "a", "x": 1, "y": 2, "yaw": 0.5}]}
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = fake
    with patch("httpx.get", return_value=mock_resp):
        wps = client_mod.fetch_patrol("hide_and_seek_search")
    assert wps == [(1.0, 2.0, 0.5)]
    cache = tmp_path / "hide_and_seek_search.json"
    assert cache.exists()


def test_fetch_falls_back_to_cache(client_mod, tmp_path):
    cache = tmp_path / "hide_and_seek_search.json"
    cache.write_text(json.dumps([[3.0, 4.0, 0.0]]))
    with patch("httpx.get", side_effect=httpx.ConnectError("down")):
        wps = client_mod.fetch_patrol("hide_and_seek_search")
    assert wps == [(3.0, 4.0, 0.0)]


def test_fetch_raises_when_no_cache(client_mod):
    with patch("httpx.get", side_effect=httpx.ConnectError("down")):
        with pytest.raises(RuntimeError, match="캐시"):
            client_mod.fetch_patrol("hide_and_seek_search")
