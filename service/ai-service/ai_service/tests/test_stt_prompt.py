"""STT initial_prompt biasing — robot 별 동적 키워드 주입."""
from types import SimpleNamespace
from unittest.mock import patch

from ai_service import stt


def _wp(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name)


def test_gogoping_waypoint_keywords_drops_internal_nodes() -> None:
    """사람이 부르는 방 이름만 — hyphen 포함 내부 경로 노드는 제외."""
    fake = [
        _wp("놀이방"), _wp("수면실"), _wp("충전소"), _wp("복도"), _wp("출입구"),
        _wp("놀-1"), _wp("수-3"), _wp("복-4-1"), _wp("놀이방입구-상"), _wp("놀-상-회"),
    ]
    with patch("control_service.waypoints.yaml_store.load", return_value=(fake, None)):
        kw = stt._gogoping_waypoint_keywords()
    assert kw == "놀이방, 수면실, 충전소, 복도, 출입구"


def test_gogoping_prompt_injects_room_names() -> None:
    """gogoping prompt 에 방 이름 + mode 단어가 함께 들어간다."""
    with patch.object(stt, "_gogoping_waypoint_keywords", return_value="놀이방, 수면실, 충전소"):
        prompt = stt._ko_prompt_for("gogoping")
    assert "놀이방" in prompt
    assert "수면실" in prompt
    # gogoping mode 단어 (이동/자장가/복귀/숨바꼭질) 도 여전히 포함.
    assert "이동" in prompt
    assert "자장가" in prompt
    assert "복귀" in prompt


def test_non_gogoping_prompt_has_no_waypoints() -> None:
    """다른 robot prompt 에는 gogoping 방 이름이 새지 않는다."""
    with patch.object(stt, "_gogoping_waypoint_keywords", return_value="놀이방, 수면실") as m:
        prompt = stt._ko_prompt_for("eduping")
    m.assert_not_called()
    assert "놀이방" not in prompt
