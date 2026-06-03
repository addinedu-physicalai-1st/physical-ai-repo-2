# presentation/final-v3 — 최종 발표 덱 (Q&A 보고서)

Reveal.js 정적 덱. 구조·실행·키바인딩은 [README.md](README.md) 참조.
이 문서는 **Q&A 인덱스 + 담당자 보고서** 규칙만 다룬다.

## Q&A 구조

- 마지막 슬라이드 `slides/24-ending.html` (`id="qna"`) 가 **Q&A 인덱스** — 12개 항목 그리드.
- 각 항목 클릭 → `js/main.js` 의 `openReport()` 가 크림 페이드 후 같은 탭에서
  `reports/<NN-slug>/index.html` (담당자 보고서) 로 이동한다.
- 보고서 → Q&A 복귀는 보고서의 `← Q&A` 버튼 (`backToQna()`) → `../../index.html#/qna`.
  양쪽 모두 같은 배경(`#16131F`)·0.3s 페이드라 슬라이드처럼 끊김 없이 이어진다.

| # | 폴더 | 주제 | 담당 |
|---|------|------|------|
| 01 | `reports/01-eduping-commute` | 등/하원 | 이정우 |
| 02 | `reports/02-eduping-mugunghwa` | 무궁화 꽃이 피었습니다 | 이정우 |
| 03 | `reports/03-eduping-dance` | 율동 기능 | 박우림 |
| 04 | `reports/04-eduping-doctor` | 원격진찰 기능 | 박우림 |
| 05 | `reports/05-voice-stt-tts` | 호출어와 STT·TTS | 박우림 |
| 06 | `reports/06-nlu` | 자연어 처리 | 박우림 |
| 07 | `reports/07-gogoping-nav` | 자율주행 이동 | 이강택 |
| 08 | `reports/08-gogoping-follow` | 추종 기능 | 노영주 |
| 09 | `reports/09-noriarm-shop` | 가게놀이 기능 | 최민성 |
| 10 | `reports/10-noriarm-oxquiz` | OX 퀴즈 | 이지수 |
| 11 | `reports/11-noriarm-blocks` | 블럭쌓기 게임 | 이지수 |
| 12 | `reports/12-gogoping-hideseek` | 숨바꼭질 | 이강택 |

## 보고서 작성 규칙 (담당자 필독)

각 `reports/<NN-slug>/index.html` 는 "준비 중" 스타터다. 자기 보고서로 자유롭게 교체하되:

1. **뒤로가기 버튼 필수.** 모든 보고서(및 하위 페이지)는 **반드시 Q&A 인덱스로 돌아오는
   `← Q&A` 뒤로가기 버튼**을 포함한다. 스타터의 `.back` 버튼 + `backToQna()` 를 그대로
   유지하면 된다. 발표 중 길을 잃지 않게 하는 안전장치이므로 절대 제거하지 않는다.

2. **Asset 은 Prismic CDN URL 만 사용.** 이미지·동영상 등 무거운 asset 은
   **저장소에 커밋하지 말고** 각자 [Prismic](https://prismic.io/) 에 업로드한 뒤
   그 CDN URL 을 보고서에 박는다. 로컬 파일 경로(`./img/foo.png`)로 참조하지 않는다.

   ```bash
   # ~/Downloads 에서 골라 업로드 → CDN URL 출력
   scripts/prismic/upload.sh
   ```
   ```html
   <img src="https://images.prismic.io/.../foo.png" alt="..." />
   ```

3. (권장) 스타터의 디자인 토큰 (`--accent`, `--surface`, `--ink`, `--bg`) 을 그대로 쓰면
   덱과 톤이 맞는다. 폰트는 Jua(제목) + Pretendard(본문).

## 슬라이드에서 항목 추가/수정

- 인덱스 타일: `slides/24-ending.html` 의 그리드에 `<div onclick="openReport('reports/<slug>/index.html')">` 추가.
- 새 보고서 폴더: `reports/<NN-slug>/index.html` 생성 (기존 스타터 복사 → 위 규칙 준수).
