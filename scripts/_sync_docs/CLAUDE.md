# _sync_docs/

Confluence ↔ `docs/` 동기화 모듈. 두 진입점이 source 한다.

| 파일 | 방향 | 역할 |
|---|---|---|
| [sync_one_page.py](sync_one_page.py) | pull | URL 1개 → `docs/<name>.md` + `.assets/` |
| [push_page.py](push_page.py) | push | `docs/<name>.md` → Confluence 페이지 갱신 |
| [html_md_converter.py](html_md_converter.py) | pull 보조 | Confluence storage HTML → Markdown |
| [md_to_confluence.py](md_to_confluence.py) | push 보조 | Markdown → Confluence storage HTML (mistune 기반) |
| [drawio_utils.py](drawio_utils.py) | pull 보조 | Confluence storage HTML 의 drawio 매크로 파싱 / 첨부 매칭 |
| [pages.sh](pages.sh) | 공유 | 페이지 목록 (`PAGES` 배열) |

## 주의

- **Pull**: 매 실행마다 `<name>.md` 와 `<name>.assets/` 를 덮어쓴다 — 로컬 수정은 사라진다. push 가 끝난 뒤에만 다시 pull.
- **Push**: frontmatter 의 `confluence_version` 과 서버 버전이 다르면 abort (`--force` 로 무시 가능). 서버 변경사항 손실 방지.
- **drawio 라운드트립**: pull 시 매크로 storage XML 을 `<base>.macro.xml` sidecar 로 저장하고, push 시 (이미지 + drawio 링크) 블록 자리에 그대로 splice. ADF UUID 재생성 없이 안전. sidecar 가 없으면 본문에 매크로가 없는 채로 push 된다.
- **Push 미지원 / TODO**: Confluence 매크로(info/warning 등)는 라운드트립 안 됨, 첨부 이미지·drawio 업로드는 본문에서 직접 참조하는 파일만.
- 다이어그램 편집은 원본 `.drawio` 를 [diagrams.net](https://app.diagrams.net) 에서.

## 의존성

```bash
pip install -r ../../requirements.txt    # requests, python-dotenv, mistune
```

`pull_docs.sh` / `push_docs.sh` 는 `.venv/bin/python` 이 있으면 자동으로 사용한다.

## 직접 호출

```bash
cd scripts/_sync_docs

# pull
python sync_one_page.py <Confluence 페이지 URL>

# push (dry-run)
python push_page.py ../../docs/system-requirements.md

# push (실제 PUT)
python push_page.py ../../docs/system-requirements.md --apply
```

토큰은 프로젝트 루트 `.env` 에서 읽는다 (`ATLASSIAN_EMAIL`, `ATLASSIAN_API_TOKEN`).
