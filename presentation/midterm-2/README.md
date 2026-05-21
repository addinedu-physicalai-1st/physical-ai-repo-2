# pingdergarten — 발표 슬라이드

사랑의 에듀핑 팀의 최종 발표 슬라이드. 파스텔 유치원 톤으로 제작.

## 스택

- [Reveal.js 5.1.0](https://revealjs.com/) (CDN)
- [Tailwind CSS](https://tailwindcss.com/) (CDN, 인라인 config 로 파스텔 팔레트)
- Google Fonts — Jua, Gaegu, Material Icons Round
- 빌드 단계 없음. 정적 HTML/CSS/JS.

## 실행

프로젝트 루트가 아니라 `presentation/` 안에서 실행해야 슬라이드가 로드됩니다.

```bash
cd presentation
python3 -m http.server 8000
```

브라우저에서 <http://localhost:8000> 열기.

또는 VS Code Live Server, `npx serve`, `caddy file-server` 등 임의의 정적 서버 사용 가능.

## 키바인딩

| 키 | 동작 |
| --- | --- |
| `→` / `↓` / `Space` | 다음 슬라이드 |
| `←` / `↑` | 이전 슬라이드 |
| `F` | 풀스크린 토글 |
| `P` | 현재 슬라이드의 데모 영상 재생/일시정지 |
| `W` | 웹캠 오버레이 토글 (데모 시 발표자 얼굴) |
| `C` | 그리기 모드 토글 (강조 표시) |
| `X` | 그리기 지우기 |
| `S` | 발표자 노트 (Reveal.js 기본) |
| `Esc` | 슬라이드 패널/풀스크린 닫기 |
| 우하단 슬라이드 번호 클릭 | 썸네일 패널 열기 |

## 슬라이드 추가하기

1. `slides/NN-name.html` 에 `<section>` 하나로 슬라이드 작성
2. `js/main.js` 의 `SLIDES` 배열과 `SLIDE_TITLES` 배열에 한 줄씩 추가
3. 새로고침

```js
// js/main.js
var SLIDES = [
  '01-title.html',
  '02-team.html',
  // ↓ 여기에 추가
  '12-newslide.html',
];
var SLIDE_TITLES = [
  '사랑의 에듀핑',
  '팀 소개',
  '새 슬라이드 제목',
];
```

## 디자인 토큰

`tailwind.config` 와 `css/main.css` 양쪽에 같은 변수가 정의되어 있음.

| 이름 | 값 | 용도 |
| --- | --- | --- |
| `cream` | `#FFF8F2` | 슬라이드 배경 |
| `surface` | `#FFFFFF` | 카드 배경 |
| `babypink` | `#F8B4C4` | 1차 강조 |
| `mint` | `#B5E6D8` | 2차 강조 |
| `butter` | `#FFE5A8` | 3차 강조 |
| `lavender` | `#C9B6E4` | 4차 강조 |
| `sky` | `#B5DEFF` | 5차 강조 |
| `ink` | `#5D4037` | 본문 텍스트 (warm dark brown) |
| `inkSoft` | `#8D6E63` | 보조 텍스트 |

각 색마다 `*Soft` 변형 (`babypinkSoft` 등) 이 카드 배경/배지용으로 정의됨.

## 헬퍼 클래스

- `.pastel-card` — 둥근 모서리, 보더, 그림자가 있는 카드
- `.chip`, `.chip-mint`, `.chip-butter`, `.chip-lavender`, `.chip-sky` — 라운드 배지
- `.wavy` — 글자 아래 물결선

## 폴더 구조

```
presentation/
├── index.html       # Reveal 부트스트랩, Tailwind config, 오버레이 마크업
├── README.md
├── css/main.css     # 파스텔 변수, 패널/캔버스 스타일
├── js/main.js       # SLIDES 배열, 슬라이드 로더, 키바인딩
└── slides/
    ├── 01-title.html
    ├── 02-team.html
    └── ...
```
