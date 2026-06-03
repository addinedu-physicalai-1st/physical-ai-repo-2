"""AI Hub settings — 모두 코드 기본값.

env override 를 받지 않는다. 모델 교체·레이턴시 튜닝·음성 옵션 변경은 이 파일을
직접 수정해서 한다 (`.env` 에 노브를 흩뿌리지 않기 위함).
"""
from dataclasses import dataclass


@dataclass
class Settings:
    ollama_host: str = "http://localhost:11434"
    # 잡담(chat) 전용. 의도 분류는 규칙 기반 핸들러(intents/)가 처리하므로 별도 LLM 불필요. `ollama pull qwen2.5:3b` 필요.
    ollama_chat_model: str = "qwen2.5:3b"
    # 일과 보고서 JSON 전용 — 타임라인·규칙 준수에 3b 보다 유리. `ollama pull qwen2.5:7b` 필요.
    # VRAM 이 빠듯하면 `qwen2.5:3b` 로 낮춰도 됨(잡담과 동일 모델).
    ollama_report_model: str = "qwen2.5:7b"
    # 보고서 2차 검수 — 기본은 별도 호출이지만 동일 태그(qwen2.5:7b)를 쓰면 생성과 같은 가중치를 공유.
    ollama_report_validate_enabled: bool = True
    ollama_report_validate_model: str = "qwen2.5:7b"
    ollama_report_validate_timeout_s: float = 90.0
    ollama_report_validate_num_predict: int = 2048
    ollama_report_validate_num_ctx: int = 8192
    ollama_report_validate_temperature: float = 0.12
    # 생성 상한 — 짧은 JSON 답은 EOS 로 일찍 끝나고, 상한만 너무 크면 최악 지연만 커짐.
    ollama_chat_num_predict: int = 156
    # 프롬프트 프리필 비용 줄이기(512 로도 시스템 프롬프트는 통상 충분).
    ollama_chat_num_ctx: int = 512
    ollama_chat_use_few_shot: bool = False
    # 샘플링 — 약간 보수적으로 두면 디코딩이 가벼워지는 경우가 많음.
    ollama_chat_temperature: float = 0.4
    ollama_chat_top_p: float = 0.88
    # Ollama options.top_k — 후보 토큰을 줄여 체감 지연을 줄이기(0 이하이면 전송 안 함).
    ollama_chat_top_k: int = 40
    # 읽기 타임아웃 — 실패 시 곧바로 짧은 repair 경로로 넘어가므로 한 번만 길게 잡지 않음.
    ollama_chat_timeout_s: float = 4.15
    # 일과 보고서 JSON 생성 — 긴 타임라인·큰 num_predict 시 Ollama 지연이 길어질 수 있음.
    ollama_report_timeout_s: float = 120.0
    # Ollama API: 모델을 메모리에 유지하는 시간 — 매 요청마다 갱신 (기본 5m 보다 길게 두면 재로드 감소)
    ollama_keep_alive: str = "30m"
    # true 이면 Hub 기동 시 백그라운드로 모델 프리로드(첫 발화 체감 단축, Ollama 가 떠 있어야 함)
    ollama_warmup_on_start: bool = False
    # 음성 잡담: `generate_chat` 최대 대기(초). 초과 시 선생님 안내 문구로 응답(체감 지연 상한). 0 이면 미적용.
    voice_chat_llm_max_wait_s: float = 2.0
    # 원아 부름명 목록 DB 조회 TTL(초). 0 이면 매번 조회. 잡담 연속 시 레이턴시 절감.
    roster_labels_cache_ttl_s: float = 120.0
    request_timeout_s: float = 30.0
    ai_port: int = 8001

    # Edge neural — 한국어 남성: InJoon / Hyunsu(Multilingual). 아동 전용 화자는 없음.
    edge_tts_voice: str = "ko-KR-InJoonNeural"
    # edge-tts 는 `Communicate(..., pitch=)` 만 SSML 안쪽에 반영된다. `+NNHz` / `+N.Nst` / `+N%`.
    edge_tts_pitch_pct: str = "+3.5st"
    # 말 속도(밝기) — `^[+-]\\d+%$` 만.
    edge_tts_rate: str = "+14%"


settings = Settings()


# --- 임베딩 (RAG 용 텍스트 → 벡터) ---
EMBED_MODEL = "bge-m3"
EMBED_DIM = 1024


# --- run_server.sh 가 기동 전에 ollama pull 로 보장하는 모델 목록 ---
# 셸 스크립트가 `python -m ai_service.config` 로 한 줄당 한 모델씩 받아간다.
REQUIRED_OLLAMA_MODELS: tuple[str, ...] = tuple(
    dict.fromkeys(
        (
            settings.ollama_chat_model,
            settings.ollama_report_model,
            settings.ollama_report_validate_model,
            EMBED_MODEL,
        )
    )
)


if __name__ == "__main__":
    for _m in REQUIRED_OLLAMA_MODELS:
        print(_m)
