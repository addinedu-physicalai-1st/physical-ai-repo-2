# Intent · Chat Capability 아키텍처 — 설계서

- 작성일: 2026-05-20
- 대상 서비스: `service/ai-service/`
- 목적: 로봇별 intent 분류와 chat 에서 호출하는 기능 (DB 조회 등) 을 공통/전용 경계가 명확한 체계로 재구성한다. 현 동작은 1:1 보존하면서 확장과 가독성을 개선한다.

## 1. 배경

현재 [hub.py](../../../service/ai-service/ai_service/hub.py) 의 `voice_intent` 는 150 줄짜리 단일 함수로, 모든 intent 매칭 규칙·DB 조회 fast-path·LLM fallback 이 직렬 if-블록으로 박혀 있다. gogoping 전용 분기는 `if req.robot == "gogoping"` 처럼 함수 본문에 흩뿌려져 있고, DB 조회 함수들은 1,063 줄의 [context.py](../../../service/ai-service/ai_service/context.py) 에 같이 들어 있다. 결과:

- 새 intent 추가는 거대 함수 한복판을 수술하는 작업이 된다.
- "이 로봇이 무엇을 할 수 있는가" 를 한 눈에 보기 어렵다.
- 공통 기능 (DB 조회) 과 로봇 전용 기능의 경계가 코드에 표현돼 있지 않다.

## 2. 목표 / 비-목표

**목표**

- 로봇별 intent 파이프라인을 명시적으로 선언한다 (한 파일에서 "이 로봇이 뭘 하는지" 가 다 보임).
- 공통 핸들러와 로봇 전용 핸들러를 디렉토리 레벨에서 분리한다.
- chat/handler 가 호출하는 부수효과 작업 (DB 조회, LLM 호출, 파일 읽기) 을 `capabilities/` 단일 위치로 모은다.
- 기존 회귀 테스트 [test_hub_responses.py](../../../service/ai-service/ai_service/tests/test_hub_responses.py) 가 매 단계마다 통과한다.

**비-목표 (YAGNI)**

- LLM tool-calling 도입. 구조만 열어두되 이번 작업 범위 밖.
- intent 분류 자체를 LLM 으로 대체. rules-first 동작을 그대로 보존.
- 공통 핸들러의 응답 문구/매칭 토큰/우선순위 변경.
- eduping·noriarm 전용 신규 intent 추가. 빈 디렉토리만 만들고 핸들러는 안 채움.

## 3. 아키텍처

### 3.1 디렉토리 레이아웃

```
service/ai-service/ai_service/
├── intents/
│   ├── __init__.py          # PIPELINES: dict[robot_id, list[IntentHandler]]
│   ├── base.py              # IntentHandler ABC, IntentContext
│   ├── common/              # 전 로봇 공통
│   │   ├── stop.py
│   │   ├── menu.py
│   │   ├── hello.py
│   │   ├── gender.py
│   │   ├── mode_change.py
│   │   ├── emotion_demo.py
│   │   ├── schedule.py
│   │   ├── whereabouts.py
│   │   ├── report.py
│   │   ├── attendance.py
│   │   └── chat_fallback.py
│   └── gogoping/            # 로봇 전용
│       ├── return_.py
│       └── goto_vertex.py
├── capabilities/            # chat/handler 가 호출하는 부수효과 작업
│   ├── __init__.py
│   ├── db_menu.py
│   ├── db_attendance.py
│   ├── db_report.py
│   ├── db_roster.py
│   ├── schedule_file.py
│   └── chat_llm.py
└── hub.py                   # voice_intent = 파이프라인 디스패처
```

`intents/eduping/`, `intents/noriarm/` 은 이번 범위에서 만들지 않는다. 두 로봇이 전용 intent 를 갖게 되는 시점에 추가한다.

### 3.2 핸들러 인터페이스

`intents/base.py`:

```python
class IntentHandler(ABC):
    name: ClassVar[str]   # 로깅·테스트용 고유 식별자 ("stop", "menu", ...)

    @abstractmethod
    async def try_handle(
        self, req: IntentRequest, ctx: IntentContext
    ) -> IntentResponse | None:
        """매치되면 IntentResponse, 아니면 None (다음 핸들러로 패스)."""
```

- `IntentResponse` 는 `hub.py` 가 이미 정의한 `ModeChange | SubCommand | GotoVertex | Chat` union 의 별칭. 응답 모델은 재사용.
- `IntentContext` 는 같은 요청 내 핸들러들이 공유하는 mutable bag — `now: datetime` (KST), lazy-loaded `roster: str | None`, lazy-loaded `chat_ctx: dict[str, str] | None` 등. 같은 데이터를 두 번 조회하지 않도록.
- `try_handle` 이 `None` 을 반환하면 디스패처가 다음 핸들러를 시도한다.
- `name` 클래스 어트리뷰트는 로깅 (`intent.matched=stop`) 과 테스트 (`PIPELINES["eduping"][0].name == "stop"`) 에 쓰인다.

핸들러 인스턴스는 모듈 로드 시 1회 생성한다. stateless 이므로 재사용 안전. HTTP 클라이언트 등 무거운 의존성은 `IntentContext` 가 lazy-init 으로 보관한다.

### 3.3 파이프라인 선언 & 디스패처

`intents/__init__.py`:

```python
from .common.stop import StopHandler
from .common.menu import MenuHandler
# ... (import 생략)
from .gogoping.return_ import ReturnHandler
from .gogoping.goto_vertex import GotoVertexHandler

_COMMON_PRE_LLM: list[IntentHandler] = [
    StopHandler(),
    MenuHandler(),
    HelloHandler(),
    GenderHandler(),
    ModeChangeHandler(),
    EmotionDemoHandler(),
    ScheduleHandler(),
    WhereaboutsHandler(),
    ReportHandler(),
    AttendanceHandler(),
]

PIPELINES: dict[str, list[IntentHandler]] = {
    "eduping":  [StopHandler(), *_COMMON_PRE_LLM[1:], ChatFallbackHandler()],
    "gogoping": [StopHandler(), ReturnHandler(), GotoVertexHandler(),
                 *_COMMON_PRE_LLM[1:], ChatFallbackHandler()],
    "noriarm":  [StopHandler(), *_COMMON_PRE_LLM[1:], ChatFallbackHandler()],
}
```

- **순서 = 우선순위.** 별도 `priority: int` 필드는 두지 않는다. 리스트 순서가 곧 의도.
- **`StopHandler` 는 모든 로봇에서 첫 번째.** "정지" 는 어떤 로봇이든 무조건 최우선.
- **`ChatFallbackHandler` 는 항상 마지막**이며 `None` 을 반환하지 않는 invariant. LLM 실패 시에도 guard reply 를 반환.
- 로봇별 파이프라인은 공통 리스트를 펼쳐서 명시적으로 적는다. "이 로봇이 뭘 하는지" 를 한 파일에서 다 본다.

디스패처는 `hub.voice_intent` 안에 그대로 둔다:

```python
@app.post("/voice/intent")
async def voice_intent(req: IntentRequest) -> dict:
    if not is_known_robot(req.robot):
        return {"kind": "ignored"}
    ctx = IntentContext(now=_now_kst(), req=req)
    for handler in PIPELINES[req.robot]:
        result = await handler.try_handle(req, ctx)
        if result is not None:
            logger.info("intent.matched", extra={"robot": req.robot,
                                                  "handler": handler.name})
            return result.model_dump()
    raise RuntimeError("no handler matched — ChatFallback missing?")
```

### 3.4 capabilities 모듈 경계

`capabilities/` 는 chat 이 호출하는 기능의 단일 위치.

**경계 규칙**

- capability 는 **부수효과 있는 작업** (DB 조회, 외부 파일 읽기, LLM 호출) 만 담는다.
- 순수 텍스트 파싱·정규화 (날짜 추출, "정지" 토큰 매칭) 는 capability 가 아니라 핸들러 내부 helper 또는 `intents/_text_utils.py` 에 둔다.
- capability 는 **자신을 누가 호출하는지 모른다.** 입력은 도메인 인자 (`day: int`, `child_name: str`), 출력은 도메인 데이터 (`MenuResult`, `list[AttendanceRow]`). 응답 문장 만들기는 핸들러 책임.
- capability 는 **로봇 ID 를 인자로 받지 않는다.** 로봇 차이는 핸들러 레벨에서 흡수. 단, capability 가 로봇별 페르소나 텍스트 (예: `display_name`) 가 필요하면 호출자가 명시적으로 전달.

**모듈 분할**

| 파일 | 함수 | 출처 (현재 위치) |
|---|---|---|
| `db_menu.py` | `search_menu(day, relative) -> MenuResult` | `context.py:get_menu_fast`, `parse_menu_query_calendar_day` |
| `db_attendance.py` | `today_attendance() -> list[AttendanceRow]`, `find_child(name) -> AttendanceRow \| None` | `context.py:try_attendance_first_reply`, `try_whereabouts_first_reply` |
| `db_report.py` | `fetch_report(child_name, date) -> ReportContent \| None` | `context.py:try_report_first_reply` |
| `db_roster.py` | `fetch_registered_children_labels() -> str` | `context.py:fetch_registered_children_labels` |
| `schedule_file.py` | `current_slot(now) -> ScheduleSlot`, `lookup(text) -> str \| None` | `context.py:try_schedule_first_reply`, `load_school_schedule_dict` |
| `chat_llm.py` | `generate_chat(text, robot, ctx) -> ChatReply` | `llm.py:generate_chat` 의 얇은 wrapper (시그니처 통일) |

### 3.5 향후 LLM tool-calling 확장 포인트 (참고)

각 capability 가 명확한 도메인 함수이므로 추후 LLM tool spec 노출 시:

- 한 capability 함수 = 한 tool entry. name·description·JSON schema 자동 생성 가능.
- 로봇별 tool 노출은 prompts 모듈 (예: `prompts/eduping.py`) 에 `ALLOWED_TOOLS: list[str]` 로 선언.

이번 범위에서는 도입하지 않는다. capability 분리만 해둔다.

## 4. 마이그레이션 순서

각 step 끝마다 `test_hub_responses.py` 가 통과해야 한다. step 은 개별 커밋으로 — 회귀 시 bisect 가능.

1. **scaffold.** `intents/base.py`, `intents/__init__.py` (빈 `PIPELINES`), `capabilities/__init__.py` 생성. `hub.py` 는 그대로. 테스트 영향 없음.

2. **capabilities 이전.** `context.py` 의 menu/attendance/report/schedule/roster 함수를 `capabilities/` 로 이동. `context.py` 와 `hub.py` 의 import 경로 갱신. **로직 변경 없음.** 회귀 테스트로 검증.

3. **공통 핸들러 단계 이전.** 한 번에 하나씩, 다음 순서로:
   `stop → menu → hello → gender → mode_change → emotion_demo → schedule → whereabouts → report → attendance → chat_fallback`.
   각 핸들러 추가 시:
   - `intents/common/<name>.py` 작성
   - 3개 로봇 파이프라인에 같은 위치에 끼움
   - `hub.voice_intent` 의 해당 if-블록 삭제
   - `test_hub_responses.py` 통과 확인
   - 핸들러별 unit test 추가 (`tests/intents/test_<name>.py`)

4. **gogoping 전용 이전.** `ReturnHandler`, `GotoVertexHandler` 를 `intents/gogoping/` 로. gogoping 파이프라인에만 추가.

5. **디스패처 단순화.** `hub.voice_intent` 가 파이프라인 루프 한 덩어리로 축소. 이 시점에 `if req.robot == "..."` 분기가 hub.py 에서 모두 사라짐.

6. **`context.py` 정리.** 더 이상 호출되지 않는 `try_*_first_reply` 함수 삭제. `build_chat_context` 만 남기고 capabilities 호출의 얇은 조립자가 됨.

step 3 은 핸들러 수만큼 커밋이 쪼개진다 (약 11 커밋).

## 5. 테스트 전략

- **회귀 안전망.** [test_hub_responses.py](../../../service/ai-service/ai_service/tests/test_hub_responses.py) 의 12 케이스 — 손대지 않는다. 매 step 마다 통과 확인.
- **핸들러 unit test.** `tests/intents/test_<name>.py` 에 핸들러당 최소 2 케이스: 매치되는 입력 → 기대 응답, 매치되지 않는 입력 → `None`.

  ```python
  async def test_stop_matches_stop_token():
      req = _req("멈춰")
      ctx = IntentContext(now=_now_kst(), req=req)
      r = await StopHandler().try_handle(req, ctx)
      assert r == SubCommand(action="stop")

  async def test_stop_passes_through_normal_text():
      req = _req("점심 메뉴")
      ctx = IntentContext(now=_now_kst(), req=req)
      r = await StopHandler().try_handle(req, ctx)
      assert r is None
  ```

- **capability unit test.** `tests/capabilities/test_<name>.py` — DB fixture 또는 `monkeypatch` 로 stub.
- **`scripts/test.sh` 갱신.** 새 테스트 경로를 entry script 에 추가 ([CLAUDE.md](../../../CLAUDE.md) 규칙).

## 6. 위험 / 완화

- **DB 조회 함수 시그니처 변경 시 `context.build_chat_context` 가 깨질 수 있음.** 완화: step 2 에서 함수만 옮기고 시그니처는 유지. 시그니처 변경은 별도 step 으로 분리.
- **핸들러 간 순서 의존성 (e.g., MenuHandler 가 HelloHandler 보다 앞이어야 "점심 안녕" 같은 트릭 입력에서 같은 응답).** 완화: 마이그레이션 step 3 은 한 핸들러씩 옮기고 매번 회귀 테스트. 기존 if-블록 순서를 그대로 보존하면 자연히 같은 우선순위가 유지된다.
- **`IntentContext` 의 lazy-init 데이터가 race 되거나 중복 호출.** 완화: lazy-init 은 동기 캐시 패턴 (`if self._roster is None: self._roster = await fetch(...)`). 같은 요청은 단일 코루틴이므로 race 없음.
