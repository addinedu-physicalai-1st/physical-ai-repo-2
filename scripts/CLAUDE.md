# scripts/

Confluence ↔ `docs/` 동기화 도구. 진입점 두 개:

| 스크립트 | 방향 | 비고 |
|---|---|---|
| [pull_docs.sh](pull_docs.sh) | Confluence → 로컬 (pull) | 로컬 `<name>.md` 와 `<name>.assets/` 덮어씀 |
| [push_docs.sh](push_docs.sh) | 로컬 → Confluence (push) | 기본 dry-run, `--apply` 로 실제 PUT |

```bash
# Pull
scripts/pull_docs.sh              # 대화형 메뉴
scripts/pull_docs.sh 1,3,5        # 다중 선택
scripts/pull_docs.sh a            # 등록 페이지 전체
scripts/pull_docs.sh 0 <URL>      # 등록 안 된 URL 일회성

# Push (기본 dry-run)
scripts/push_docs.sh                       # 대화형 메뉴
scripts/push_docs.sh 2 --show-html         # 변환 결과 미리보기
scripts/push_docs.sh 2 --apply             # 실제 push
scripts/push_docs.sh 2 --apply --force     # 서버 버전 mismatch 무시 (위험)
scripts/push_docs.sh --file docs/x.md      # PAGES 외 임의 파일 dry-run
```

페이지 목록은 [_sync_docs/pages.sh](_sync_docs/pages.sh) — 두 스크립트가 공유. `page_id|URL+slug|출력파일명|표시라벨` 형식.

토큰은 프로젝트 루트의 [.env](../.env) 에만 두고 절대 커밋하지 않는다 (`ATLASSIAN_EMAIL`, `ATLASSIAN_API_TOKEN`). 템플릿: [../.env.example](../.env.example).

자세한 동작: [_sync_docs/CLAUDE.md](_sync_docs/CLAUDE.md).
