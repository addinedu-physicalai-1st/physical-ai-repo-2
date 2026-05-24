"""선생님 안내 문구 — LLM 타임아웃 등에서 허브가 재사용한다."""


def teacher_idk_line(display_name: str) -> str:
    return f"{display_name}은 잘 모르겠어요."
