"""normalize_text_for_korean_piper — Edge TTS 입력이 한국어가 아닐 때 보정."""

from ai_service.edge_tts_synth import normalize_text_for_korean_piper


def test_korean_reply_unchanged() -> None:
    t = "오늘 점심 메뉴는 김치찌개, 쌀밥이에요!"
    assert normalize_text_for_korean_piper(t) == t


def test_english_only_replaced_with_korean_fallback() -> None:
    t = "Hello, I am an English reply from the model."
    out = normalize_text_for_korean_piper(t)
    assert "한국어" in out
    assert "Hello" not in out


def test_short_ascii_unchanged() -> None:
    assert normalize_text_for_korean_piper("OK") == "OK"


def test_mostly_digits_and_commas_with_some_hangul_unchanged() -> None:
    t = "오늘은 5월 11일이에요. 12시 30분에 점심이에요."
    assert normalize_text_for_korean_piper(t) == t


def test_strips_bidi_and_zero_width() -> None:
    # RLO (U+202E) + ZWSP — 남기면 음성 엔진이 글자 순서를 뒤섞는 경우가 있음
    t = "\u202e\u200b안녕하세요\u200c"
    assert normalize_text_for_korean_piper(t) == "안녕하세요"
