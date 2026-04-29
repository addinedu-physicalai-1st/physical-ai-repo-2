"""classify_intent 통합 테스트 — 실제 Ollama 서버 필요."""
import pytest

from server.ai.llm import classify_intent

pytestmark = pytest.mark.anyio


# ── 모드 전환 ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,mode", [
    ("자장가 시작해줘",      "자장가"),
    ("숨바꼭질 하자",        "숨바꼭질"),
    ("보조 모드로 해줘",     "보조"),
])
async def test_gogoping_mode_change(text: str, mode: str) -> None:
    result = await classify_intent(text, "gogoping")
    assert result.get("kind") == "mode_change", f"expected mode_change, got {result}"
    assert result.get("mode") == mode, f"expected mode={mode!r}, got {result}"


@pytest.mark.parametrize("text,mode", [
    ("등원 모드로 바꿔줘",            "등원"),
    ("하원 시작",                     "하원"),
    ("율동 모드로 해줘",              "율동"),
    ("가게놀이 시작해줘",             "가게놀이"),
    ("정리정돈 해줘",                 "정리정돈"),
    ("무궁화꽃이 피었습니다 놀자",    "무궁화꽃이 피었습니다"),
])
async def test_eduping_mode_change(text: str, mode: str) -> None:
    result = await classify_intent(text, "eduping")
    assert result.get("kind") == "mode_change", f"expected mode_change, got {result}"
    assert result.get("mode") == mode, f"expected mode={mode!r}, got {result}"


@pytest.mark.parametrize("text,mode", [
    ("블럭쌓기 하자", "블럭쌓기"),
    ("정리해줘",      "정리"),
])
async def test_noriarm_mode_change(text: str, mode: str) -> None:
    result = await classify_intent(text, "noriarm")
    assert result.get("kind") == "mode_change", f"expected mode_change, got {result}"
    assert result.get("mode") == mode, f"expected mode={mode!r}, got {result}"


# ── 정지 명령 ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", ["그만해", "멈춰", "정지", "스톱"])
async def test_stop_command(text: str) -> None:
    result = await classify_intent(text, "gogoping")
    assert result.get("kind") == "sub_command", f"got {result}"
    assert result.get("action") == "stop", f"got {result}"


# ── 분류 안 됨 ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", ["오늘 점심 뭐야", "하이", "안녕", "배고파"])
async def test_ignored(text: str) -> None:
    result = await classify_intent(text, "gogoping")
    assert result.get("kind") == "ignored", f"expected ignored, got {result}"


# ── 로봇이 가진 적 없는 기능 요청은 ignored (다른 모드로 임의 매핑 금지) ──

@pytest.mark.parametrize("text,robot", [
    # eduping 에는 '자장가' 모드가 없음 — '율동' 등으로 매핑되면 안 됨
    ("자장가 불러줘", "eduping"),
    ("자장가 틀어줘", "eduping"),
    # 어느 로봇에도 '노래' 모드는 없음
    ("노래 불러줘", "eduping"),
    ("노래 불러줘", "gogoping"),
    # gogoping 에는 '율동' 모드가 없음
    ("율동 해줘", "gogoping"),
    # noriarm 에는 '숨바꼭질' 모드가 없음
    ("숨바꼭질 하자", "noriarm"),
])
async def test_unsupported_function_is_ignored(text: str, robot: str) -> None:
    result = await classify_intent(text, robot)
    assert result.get("kind") == "ignored", (
        f"{robot} 에 없는 기능 '{text}' 가 임의로 매핑됨: {result}"
    )
