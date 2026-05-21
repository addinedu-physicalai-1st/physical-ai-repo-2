"""Settings 의 env override 동작 검증.

`AI_HUB_URL` 은 분리 운영(run_control.sh) 시 robot 박스가 backend 박스 주소를
주입하는 통로. default 동작이 깨지지 않는 것 + override 가 먹는 것 둘 다 확인.
"""
from __future__ import annotations

import importlib

import pytest


def _reload_settings():
    """config 모듈을 다시 임포트해 환경변수 재반영."""
    import control_service.config as cfg
    return importlib.reload(cfg).settings


def test_ai_hub_url_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AI_HUB_URL", raising=False)
    s = _reload_settings()
    assert s.ai_hub_url == "http://localhost:8001"


def test_ai_hub_url_env_override(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AI_HUB_URL", "http://192.168.0.142:8001")
    s = _reload_settings()
    assert s.ai_hub_url == "http://192.168.0.142:8001"
