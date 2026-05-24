"""시스템 프롬프트 조립 — Ollama·Hub 없이 prompts 트리만 검증."""

import pytest

from ai_service.prompts import chat_system, display_name


@pytest.mark.parametrize("robot", ["eduping", "gogoping", "noriarm"])
def test_chat_system_includes_shared_child_safe_block(robot: str) -> None:
    out = chat_system(robot, context_block="[지금 알고 있는 사실: 테스트]", emotions_block="basic")
    assert "무거운" in out and "직접 답해" in out
    assert "유치원 친구" in out and "반복하지 말고" in out
    assert "무의미·말장난" in out
    assert "우주·별" in out
    assert f"{display_name(robot)}은 잘 모르겠어요." in out
