"""세 로봇이 같은 BASE 를 공유하면서 PERSONA_HINT 만 다른지 확인."""
from ai_service.prompts import chat_system


def _ctx_emo() -> tuple[str, str]:
    return ("[지금 알고 있는 사실]\n- 현재 시각: 테스트\n", "- happy: 기쁨\n- sad: 슬픔")


def test_chat_system_contains_persona_per_robot() -> None:
    ctx, emo = _ctx_emo()
    out_e = chat_system("eduping", context_block=ctx, emotions_block=emo)
    out_g = chat_system("gogoping", context_block=ctx, emotions_block=emo)
    out_n = chat_system("noriarm", context_block=ctx, emotions_block=emo)

    assert "에듀핑" in out_e and "활기찬 친구" in out_e
    assert "고고핑" in out_g and "큰형아 톤" in out_g
    assert "노리암" in out_n and "책상친구" in out_n


def test_chat_system_shares_base_rules() -> None:
    ctx, emo = _ctx_emo()
    outs = [chat_system(r, context_block=ctx, emotions_block=emo)
            for r in ("eduping", "gogoping", "noriarm")]
    # 모든 로봇이 base 규칙을 동일하게 포함
    for o in outs:
        assert "자기 호칭 규칙 (반드시 지킬 것):" in o
        assert "말투 규칙 (반드시 지킬 것):" in o
        assert "사실 처리 규칙 (가장 중요):" in o
