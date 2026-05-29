"""STT text → FollowSearch / FollowResume 매칭 단위테스트."""
from ai_service.intents.gogoping import match_follow_voice_intent


def test_match_search():
    r = match_follow_voice_intent("고고핑 추종 위치확인")
    assert r is not None
    assert r.kind == "follow_search"


def test_match_search_with_extra_spaces():
    r = match_follow_voice_intent("추종  위치  확인")
    assert r is not None
    assert r.kind == "follow_search"


def test_match_resume():
    r = match_follow_voice_intent("고고핑 추종 위치이동")
    assert r is not None
    assert r.kind == "follow_resume"


def test_match_resume_with_extra_spaces():
    r = match_follow_voice_intent("추종 위치 이동")
    assert r is not None
    assert r.kind == "follow_resume"


def test_no_match_unrelated_text():
    assert match_follow_voice_intent("안녕") is None
    assert match_follow_voice_intent("정지") is None
    assert match_follow_voice_intent("") is None


def test_no_match_partial_keywords():
    # "추종" 만 / "위치" 만 / "확인" 만 → None
    assert match_follow_voice_intent("고고핑 추종") is None
    assert match_follow_voice_intent("위치 알려줘") is None
