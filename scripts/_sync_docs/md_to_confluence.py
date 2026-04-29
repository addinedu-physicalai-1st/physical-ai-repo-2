"""
Markdown → Confluence storage format HTML 변환기.

mistune 3 의 HTMLRenderer 를 상속해서, Confluence 가 storage format 으로 받아주는
형태로 약간의 element 를 커스터마이즈한다.

지원 범위:
  - H1~H6, 단락, hr
  - bold/italic/inline code/링크
  - ul / ol / li (중첩 포함)
  - table (GFM)
  - fenced code block → ac:structured-macro (code)
  - 이미지 → ac:image (외부 URL 또는 ri:attachment)
  - drawio 매크로 라운드트립: pull 시 .assets/<base>.macro.xml 로 보존된 원본
    storage XML 을, push 시 (이미지 + drawio 링크) 블록 위치에 그대로 splice.
    ADF extension UUID 를 재생성하지 않으므로 안전.

미지원 / TODO:
  - sidecar 가 없는 새 drawio 다이어그램은 본문에 매크로가 없는 채로 push 됨.
  - Confluence 매크로 (info, warning, expand 등) → 후속 작업.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

import mistune

# 이미지 마크업이 가리키는 첨부 파일명 (URL 이 아닌 것) — push 단계에서 업로드 필요한 목록.
_LOCAL_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
# drawio 본체 링크 — 마크다운 일반 링크 `[label](path/to/foo.drawio[ "title"])` 형태.
_LOCAL_DRAWIO_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+\.drawio[^)]*)\)")
# `path "title"` 또는 `path 'title'` 끝의 제목 부분 분리.
_TITLE_SUFFIX_RE = re.compile(r'^(.+?)\s+(["\']).*?\2\s*$')


def _md_url_filename(url_part: str) -> str | None:
    """마크다운 링크 URL 부분에서 첨부 파일명을 추출.

    `<path>`, `path "title"`, 공백 포함 경로 모두 처리. 외부 URL 은 None.
    """
    s = url_part.strip()
    if s.startswith("<"):
        end = s.find(">")
        if end == -1:
            return None
        path = s[1:end]
    else:
        m = _TITLE_SUFFIX_RE.match(s)
        path = m.group(1).strip() if m else s
    if path.startswith(("http://", "https://", "mailto:", "data:")):
        return None
    return path.rsplit("/", 1)[-1] or None


def extract_local_image_filenames(md_body: str) -> list[str]:
    """본문에서 외부 URL 이 아닌 이미지 참조의 파일명 목록을 반환한다."""
    out: list[str] = []
    seen: set[str] = set()
    for m in _LOCAL_IMAGE_RE.finditer(md_body):
        fn = _md_url_filename(m.group(1))
        if fn and fn not in seen:
            seen.add(fn)
            out.append(fn)
    return out


def extract_local_drawio_filenames(md_body: str) -> list[str]:
    """본문의 일반 링크 중 .drawio 본체를 가리키는 첨부 파일명 목록."""
    out: list[str] = []
    seen: set[str] = set()
    for m in _LOCAL_DRAWIO_LINK_RE.finditer(md_body):
        fn = _md_url_filename(m.group(1))
        if fn and fn not in seen:
            seen.add(fn)
            out.append(fn)
    return out


def _xml_attr(s: str) -> str:
    return html.escape(s, quote=True)


def _wrap_cdata(text: str) -> str:
    """CDATA 안에 ']]>' 가 들어가지 않도록 split."""
    return text.replace("]]>", "]]]]><![CDATA[>")


class ConfluenceRenderer(mistune.HTMLRenderer):
    """mistune 기본 HTML 출력에서 code block / image 만 Confluence 매크로로 교체."""

    def block_code(self, code: str, info: str | None = None, **_kwargs) -> str:
        lang = ""
        if info:
            lang = info.strip().split(None, 1)[0]
        return (
            '<ac:structured-macro ac:name="code" ac:schema-version="1">'
            f'<ac:parameter ac:name="language">{_xml_attr(lang)}</ac:parameter>'
            f"<ac:plain-text-body><![CDATA[{_wrap_cdata(code)}]]></ac:plain-text-body>"
            "</ac:structured-macro>"
        )

    def image(self, text: str, url: str, title: str | None = None) -> str:
        alt = text or ""
        if url.startswith(("http://", "https://")):
            return (
                f'<ac:image ac:alt="{_xml_attr(alt)}">'
                f'<ri:url ri:value="{_xml_attr(url)}" />'
                f"</ac:image>"
            )
        # 로컬 첨부: 파일명만 추출 (서브디렉토리 무시)
        filename = url.rsplit("/", 1)[-1]
        return (
            f'<ac:image ac:alt="{_xml_attr(alt)}">'
            f'<ri:attachment ri:filename="{_xml_attr(filename)}" />'
            f"</ac:image>"
        )


def _build_markdown_parser() -> mistune.Markdown:
    return mistune.create_markdown(
        renderer=ConfluenceRenderer(escape=True),
        plugins=["table", "strikethrough", "url", "task_lists"],
    )


_PARSER = _build_markdown_parser()


# drawio 블록: pull 이 매크로 1개를 (이미지 또는 프리뷰 없음 fallback) +
# (📐 라벨 + drawio 링크 또는 "원본 없음") 두 요소로 펼친 형태.
# `{base}` 로 drawio 파일의 베이스 이름 (확장자 제외) 을 잡고, 같은 이름의
# `<base>.macro.xml` sidecar 가 있으면 매크로 XML 으로 치환한다.
_TRIPLET_TEMPLATE = r"""
(?:!\[[^\]]*\]\([^)]*?{base}\.(?:png|drawio)\)
   |_\(프리뷰\s*없음[^)]*\)_)
\s*\n\s*\n\s*
📐\s+\*\*[^*\n]+\*\*\s+(?:—|--)\s+
(?:\[📐\s+{base}\.drawio\]\([^)]*\)|\(원본\s*없음\))
"""

_DRAWIO_TOKEN = "DRAWIO_MACRO_TOKEN_{n}_END"


def _splice_drawio_macros(
    md_body: str, assets_dir: Path | None
) -> tuple[str, list[tuple[str, str]]]:
    """drawio sidecar (.macro.xml) 가 있으면 트리플렛을 토큰으로 치환.

    Returns: (token 으로 치환된 markdown, [(token, macro_xml), ...])
    """
    triplets: list[tuple[str, str]] = []
    if assets_dir is None or not assets_dir.exists():
        return md_body, triplets

    for macro_file in sorted(assets_dir.glob("*.macro.xml")):
        if not macro_file.stem.endswith(".macro"):
            continue
        base = macro_file.stem[: -len(".macro")]
        macro_xml = macro_file.read_text(encoding="utf-8").strip()
        if not macro_xml:
            continue
        pattern = re.compile(
            _TRIPLET_TEMPLATE.format(base=re.escape(base)),
            re.DOTALL | re.VERBOSE,
        )
        token = _DRAWIO_TOKEN.format(n=len(triplets))
        new_body, n = pattern.subn(token, md_body, count=1)
        if n == 0:
            continue
        triplets.append((token, macro_xml))
        md_body = new_body
    return md_body, triplets


def markdown_to_storage_html(
    md_body: str, *, assets_dir: Path | None = None
) -> str:
    """frontmatter 가 제거된 본문 markdown 을 Confluence storage HTML 로 변환한다.

    `assets_dir` 가 주어지면 그 안의 `<base>.macro.xml` sidecar 들로 drawio
    트리플렛 자리에 원본 매크로 storage XML 을 splice 한다.
    """
    md_body, triplets = _splice_drawio_macros(md_body, assets_dir)
    storage_html = _PARSER(md_body).strip()
    for token, macro_xml in triplets:
        # mistune 가 토큰을 단락으로 감쌀 수 있어 두 형태 모두 시도.
        storage_html = storage_html.replace(f"<p>{token}</p>", macro_xml)
        storage_html = storage_html.replace(token, macro_xml)
    return storage_html
