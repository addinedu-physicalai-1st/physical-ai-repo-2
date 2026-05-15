from ai_service.guard_replies import teacher_idk_line


def test_teacher_idk_line_contains_prompt_phrases() -> None:
    s = teacher_idk_line("고고핑")
    assert "모르겠" in s and "선생님" in s
