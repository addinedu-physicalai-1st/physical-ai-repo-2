# docs/

Confluence 와 양방향 동기화되는 설계 문서.

## 문서 목록

| 문서 | 내용 |
|---|---|
| [folder-structure.md](folder-structure.md) | 폴더 구조 / 개발 명령어 |
| [user-requirements.md](user-requirements.md) | 사용자 요구사항 (UR) |
| [system-requirements.md](system-requirements.md) | 시스템 요구사항 (SR) |
| [system-architecture.md](system-architecture.md) | 시스템 아키텍처 |
| [implementation-plan.md](implementation-plan.md) | 구현 명세 — 각 SR 의 무엇을 어떻게 (구현 완료 시 implemented.md 로 이동, 규칙은 루트 [CLAUDE.md](../CLAUDE.md)) |
| [implemented.md](implemented.md) | 구현 완료된 SR 모음 (Confluence 미연동) |
| [erd.md](erd.md) | DB ERD — PostgreSQL 스키마 (엔티티·관계·draw.io) |
| [tech-stack.md](tech-stack.md) | 추상 동사 → 라이브러리·모델 매핑 |
| [robots/openarm.md](robots/openarm.md) | OpenArm — EduPing 하드웨어 사양 |
| [robots/vic-pinky.md](robots/vic-pinky.md) | Vic Pinky — GogoPing 하드웨어 사양 |
| [robots/omx-ai.md](robots/omx-ai.md) | OMX-AI — GogoArm·NoriArm 하드웨어 사양 |

## 동기화 규칙

- 상단 frontmatter(`confluence_page_id` 등)는 동기화 메타데이터 — **직접 편집 금지** (`scripts/pull_docs.sh` / `scripts/push_docs.sh` 가 갱신).
- 본문을 로컬에서 고쳐도 다음 pull 시 덮어쓰일 수 있다. 영속 변경은 Confluence 에서 하거나 push 스크립트로 올린다.
- `.assets/` 디렉토리(이미지·drawio)는 매 동기화마다 재생성 — 수기로 파일을 추가하지 않는다.

새 문서 등록·동기화 명령은 [../scripts/CLAUDE.md](../scripts/CLAUDE.md), 모듈 동작 상세는 [../scripts/_sync_docs/CLAUDE.md](../scripts/_sync_docs/CLAUDE.md).
