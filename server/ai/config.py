"""AI Hub settings — 모두 코드 기본값.

env override 를 받지 않는다. 모델 교체·레이턴시 튜닝·음성 옵션 변경은 이 파일을
직접 수정해서 한다 (`.env` 에 노브를 흩뿌리지 않기 위함).
"""
from dataclasses import dataclass


@dataclass
class Settings:
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:0.5b"
    # 잡담(chat) 전용 — 의도 분류(ollama_model)보다 크게 둘 수 있음. `ollama pull qwen2.5:3b` 필요.
    ollama_chat_model: str = "qwen2.5:3b"
    ollama_classify_num_predict: int = 28
    ollama_classify_num_ctx: int = 768
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
# 셸 스크립트가 `python -m server.ai.config` 로 한 줄당 한 모델씩 받아간다.
REQUIRED_OLLAMA_MODELS: tuple[str, ...] = (
    settings.ollama_model,
    settings.ollama_chat_model,
    EMBED_MODEL,
)


if __name__ == "__main__":
    for _m in REQUIRED_OLLAMA_MODELS:
        print(_m)
