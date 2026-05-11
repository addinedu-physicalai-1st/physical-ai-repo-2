"""선생님 안내 문구 — LLM 타임아웃 등에서 허브가 재사용한다."""


def teacher_idk_line(display_name: str) -> str:
    return f"{display_name}은 잘 모르겠어요. 선생님께 여쭤보는 게 좋을 것 같아요."
