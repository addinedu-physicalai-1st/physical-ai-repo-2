"""UIPublisher.publish_event 단위 테스트.

Fake node + publisher 주입으로 ROS 의존성 없이 검증.
- 신규 'ui_event' 토픽 publisher 생성
- publish_event(dict) → JSON 직렬화 후 publish
- 한국어 보존 (ensure_ascii=False)
- 기존 publish_state 와 분리 (state 토픽 영향 없음)

interfaces/__init__.py 우회 — ui_publisher.py 만 직접 로드해
std_srvs / std_msgs 등 ROS 의존성 회피 (pose_override 테스트와 동일 패턴).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

_REPO = Path(__file__).resolve().parents[1]
_GOGOPING_MODES_SRC = (
    _REPO / "controller" / "gogoping-controller" / "src" / "gogoping"
    / "gogoping_modes"
)
sys.path.insert(0, str(_GOGOPING_MODES_SRC))

# std_msgs.msg.String 이 없는 환경에서도 import 가능하게 stub
try:
    from std_msgs.msg import String  # noqa: F401
except ImportError:
    _fake_string_cls = type("String", (), {"data": ""})
    _fake_msg = ModuleType("std_msgs.msg")
    _fake_msg.String = _fake_string_cls  # type: ignore[attr-defined]
    _fake_pkg = ModuleType("std_msgs")
    _fake_pkg.msg = _fake_msg  # type: ignore[attr-defined]
    sys.modules["std_msgs"] = _fake_pkg
    sys.modules["std_msgs.msg"] = _fake_msg

# ui_publisher.py 파일만 직접 로드해 __init__.py 우회
_ui_pub_path = _GOGOPING_MODES_SRC / "gogoping_modes" / "interfaces" / "ui_publisher.py"
_spec = importlib.util.spec_from_file_location(
    "gogoping_modes.interfaces.ui_publisher_test_module", _ui_pub_path
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)  # type: ignore[union-attr]
UIPublisher = _module.UIPublisher


class _FakePublisher:
    def __init__(self) -> None:
        self.published: list[str] = []

    def publish(self, msg) -> None:
        # std_msgs/String 호환 — msg.data 만 저장
        self.published.append(msg.data)


class _FakeNode:
    def __init__(self) -> None:
        self.publishers: dict[str, _FakePublisher] = {}

    def create_publisher(self, msg_type, topic, depth):  # noqa: ARG002
        pub = _FakePublisher()
        self.publishers[topic] = pub
        return pub


def test_publish_event_creates_ui_event_publisher():
    """생성 시 'state' 와 'ui_event' 두 publisher 모두 생성."""
    node = _FakeNode()
    UIPublisher(node)
    assert "state" in node.publishers
    assert "ui_event" in node.publishers


def test_publish_event_writes_json_to_ui_event_topic():
    """publish_event(dict) → 'ui_event' 에 JSON 1회 publish."""
    node = _FakeNode()
    ui = UIPublisher(node)
    ui.publish_event(
        {"event": "lullaby_play", "src": "lullaby.mp3", "loop": True}
    )
    assert len(node.publishers["ui_event"].published) == 1
    payload = json.loads(node.publishers["ui_event"].published[0])
    assert payload == {
        "event": "lullaby_play", "src": "lullaby.mp3", "loop": True,
    }


def test_publish_event_preserves_korean_text():
    """ensure_ascii=False — 한국어 announce 텍스트 그대로 전달."""
    node = _FakeNode()
    ui = UIPublisher(node)
    ui.publish_event({"event": "announce", "text": "찾았다!"})
    raw = node.publishers["ui_event"].published[0]
    assert "찾았다!" in raw  # JSON escape 안 됨
    assert json.loads(raw)["text"] == "찾았다!"


def test_publish_event_does_not_touch_state_topic():
    """publish_event 는 state 토픽에 publish 안 함 (분리 보장)."""
    node = _FakeNode()
    ui = UIPublisher(node)
    ui.publish_event({"event": "x"})
    assert node.publishers["state"].published == []


def test_publish_state_still_works():
    """기존 publish_state 동작 회귀 — state 토픽에 정상 publish."""
    node = _FakeNode()
    ui = UIPublisher(node)
    ui.publish_state({"robot_id": "gogoping", "fsm_state": "IDLE"})
    assert len(node.publishers["state"].published) == 1
    assert "fsm_state" in node.publishers["state"].published[0]
