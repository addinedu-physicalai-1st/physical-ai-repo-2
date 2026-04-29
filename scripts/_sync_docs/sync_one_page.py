#!/usr/bin/env python3
"""
단일 Confluence 페이지를 docs/ 디렉토리에 마크다운으로 동기화한다.

URL → page_id 추출 → REST API 로 페이지 1건만 가져와서:
  - docs/<sanitized-title>.md          (frontmatter + 본문)
  - docs/<sanitized-title>.assets/     (이미지 / drawio 리소스)

첨부 다운로드는 임시 디렉토리에서 진행하고 종료 시 자동 삭제.
파일이 이미 존재하면 덮어쓴다 (frontmatter 의 confluence_version 으로 추적).

사용법:
  python sync_one_page.py <Confluence 페이지 URL> [--output-name NAME]

예:
  python sync_one_page.py \\
      https://woolimi.atlassian.net/wiki/spaces/FN/pages/41058328/User+Requirements
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import shutil
import sys
import tempfile
import urllib.parse
from pathlib import Path

import requests
from dotenv import load_dotenv

from html_md_converter import (
    transform_storage_html,
    html_to_md,
    _DRAWIO_PLACEHOLDER,
)
from drawio_utils import (
    find_drawio_macros,
    find_drawio_source,
    find_drawio_preview,
)

SCRIPT_DIR = Path(__file__).parent.resolve()
WS_ROOT = SCRIPT_DIR.parent.parent
DOCS_DIR = WS_ROOT / "docs"
ENV_FILE = WS_ROOT / ".env"


# ─── URL 파싱 ────────────────────────────────────────────────────────

_PAGE_PATH_RE = re.compile(
    r"^/wiki/spaces/(?P<space>[^/]+)/pages/(?P<page_id>\d+)(?:/(?P<slug>[^/?#]+))?"
)


def parse_url(url: str) -> tuple[str, str, str, str]:
    """Confluence 페이지 URL → (base_url, space_key, page_id, url_slug)."""
    parsed = urllib.parse.urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"URL 형식이 올바르지 않습니다: {url}")
    base = f"{parsed.scheme}://{parsed.netloc}"
    m = _PAGE_PATH_RE.match(parsed.path)
    if not m:
        raise ValueError(
            f"Confluence 페이지 URL 이 아닙니다: {url}\n"
            f"  기대 형식: https://<host>/wiki/spaces/<KEY>/pages/<ID>/<slug>"
        )
    slug = urllib.parse.unquote(m.group("slug") or "").replace("+", " ")
    return base, m.group("space"), m.group("page_id"), slug


# ─── 인증 ────────────────────────────────────────────────────────────

def load_credentials() -> tuple[str, str]:
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE)
    email = os.environ.get("ATLASSIAN_EMAIL", "").strip()
    token = os.environ.get("ATLASSIAN_API_TOKEN", "").strip()
    if not email or not token:
        print("❌ ATLASSIAN_EMAIL / ATLASSIAN_API_TOKEN 가 .env 에 없습니다.")
        print(f"   {WS_ROOT / '.env.example'} 참고.")
        sys.exit(1)
    return email, token


# ─── 파일명 정리 ─────────────────────────────────────────────────────

_FN_BAD = re.compile(r'[\\/:*?"<>|]+')
_FN_WS = re.compile(r"\s+")


def sanitize_filename(s: str) -> str:
    """OS 안전 + 마크다운 경로에서 인코딩 불필요한 파일명."""
    s = _FN_BAD.sub("_", s).strip().strip(".")
    s = _FN_WS.sub("-", s)
    return s or "untitled"


# ─── Confluence API ─────────────────────────────────────────────────

def fetch_page(session: requests.Session, base: str, page_id: str) -> dict:
    url = f"{base}/wiki/api/v2/pages/{page_id}"
    r = session.get(url, params={"body-format": "storage"})
    if r.status_code == 404:
        print(f"❌ 페이지 {page_id} 를 찾을 수 없습니다 (404).")
        sys.exit(1)
    r.raise_for_status()
    return r.json()


def list_attachments(session: requests.Session, base: str, page_id: str) -> list[dict]:
    out: list[dict] = []
    start, limit = 0, 50
    while True:
        url = f"{base}/wiki/rest/api/content/{page_id}/child/attachment"
        r = session.get(url, params={"start": start, "limit": limit, "expand": "version"})
        if r.status_code == 404:
            return []
        r.raise_for_status()
        data = r.json()
        out.extend(data.get("results", []))
        if data.get("size", 0) < limit:
            break
        start += limit
    return out


def download_attachment(
    session: requests.Session, base: str, att: dict, dest_dir: Path,
) -> Path | None:
    download_path = att["_links"]["download"]
    if not download_path.startswith("/wiki/"):
        download_path = "/wiki" + download_path
    url = f"{base}{download_path}"

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / att["title"]
    try:
        r = session.get(url, stream=True)
        r.raise_for_status()
    except requests.HTTPError as e:
        print(f"   ⚠ {att['title']}: {e.response.status_code}")
        return None

    with open(dest, "wb") as f:
        for chunk in r.iter_content(chunk_size=64 * 1024):
            if chunk:
                f.write(chunk)
    return dest


# ─── 메인 변환 로직 ─────────────────────────────────────────────────

def _drawio_base(name: str) -> str:
    """drawio 파일의 베이스 이름 — 매크로 안의 `diagram-name` 과 어긋나지 않도록
    sanitize 하지 않고 원본 이름 (공백 포함) 을 그대로 보존."""
    return name[:-7] if name.endswith(".drawio") else name


def build_markdown(
    page: dict,
    page_id: str,
    raw_attach_dir: Path,
    assets_dir: Path,
    assets_rel: str,
) -> tuple[str, set[str]]:
    """페이지 dict + 첨부 디렉토리 → (markdown 본문, 누락 첨부 파일명 set)."""
    storage_html = page.get("body", {}).get("storage", {}).get("value", "") or ""

    # 1) 첨부 파일 목록 → 마크다운 경로 매핑
    attachment_map: dict[str, str] = {}
    if raw_attach_dir.exists():
        for f in sorted(raw_attach_dir.iterdir()):
            if f.is_file():
                attachment_map[f.name] = f"{assets_rel}/{f.name}"

    # 2) drawio 매크로 → 리소스 저장, storage HTML 의 매크로 블록은 placeholder 로 치환
    macros = find_drawio_macros(storage_html)
    diagrams: list[dict] = []
    modified_html = storage_html
    for idx, mac in enumerate(macros):
        base_name = _drawio_base(mac.diagram_name)
        # 첨부 탐색은 실제 Confluence 파일명(attachment_name)으로, 출력은 diagram_name(표시명)으로.
        src = find_drawio_source(raw_attach_dir, mac.attachment_name)
        preview = find_drawio_preview(raw_attach_dir, mac.attachment_name)

        assets_dir.mkdir(parents=True, exist_ok=True)
        if src:
            shutil.copy2(src, assets_dir / f"{base_name}.drawio")
        if preview:
            shutil.copy2(preview, assets_dir / f"{base_name}.png")
        # 원본 매크로 storage XML 을 sidecar 로 보존 — push 시 그대로 splice 해서
        # ADF extension UUID 등을 재생성하지 않아도 라운드트립이 가능.
        (assets_dir / f"{base_name}.macro.xml").write_text(
            mac.raw_block, encoding="utf-8"
        )

        ph = _DRAWIO_PLACEHOLDER.format(n=idx)
        modified_html = modified_html.replace(mac.raw_block, ph, 1)
        diagrams.append({
            "idx": idx,
            "name": mac.diagram_name,
            "base": base_name,
            "has_preview": preview is not None,
            "has_source": src is not None,
        })

    # 3) storage HTML → 일반 HTML
    missing: set[str] = set()
    plain_html = transform_storage_html(modified_html, attachment_map, missing)

    # 4) drawio placeholder 를 토큰으로 치환 (HTMLParser 가 코멘트를 무시하므로)
    md_tokens: dict[int, str] = {}
    for idx in range(len(diagrams)):
        ph = _DRAWIO_PLACEHOLDER.format(n=idx)
        tok = f"DRAWIO_TOKEN_{idx}_END"
        md_tokens[idx] = tok
        plain_html = plain_html.replace(ph, f"<p>{tok}</p>")

    md_body = html_to_md(plain_html)

    # 5) 토큰 자리에 이미지 + drawio 링크 블록 삽입
    for d in diagrams:
        idx = d["idx"]
        base_name = d["base"]
        name = d["name"]
        if d["has_preview"]:
            img_line = f"![{name}]({assets_rel}/{base_name}.png)"
        else:
            img_line = f"_(프리뷰 없음: {name})_"
        drawio_ref = (
            f"[📐 {base_name}.drawio]({assets_rel}/{base_name}.drawio)"
            if d["has_source"] else "(원본 없음)"
        )
        block = (
            f"\n\n{img_line}\n\n"
            f"📐 **{name}** — {drawio_ref}\n\n"
        )
        md_body = md_body.replace(md_tokens[idx], block)

    return md_body, missing


def main():
    parser = argparse.ArgumentParser(
        description="Confluence 페이지 1개 → docs/ 마크다운 동기화",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("url", help="Confluence 페이지 URL")
    parser.add_argument(
        "--output-name", "-o", default=None,
        help="저장 파일명 (확장자 제외). 미지정 시 페이지 제목 sanitize 결과 사용.",
    )
    parser.add_argument(
        "--output-dir", default=str(DOCS_DIR),
        help=f"출력 디렉토리 (기본: {DOCS_DIR.relative_to(WS_ROOT)})",
    )
    args = parser.parse_args()

    base, space_key, page_id, url_slug = parse_url(args.url)
    print(f"\n🎯 Target: {base}")
    print(f"   space={space_key}  page={page_id}  slug={url_slug or '(없음)'}")

    email, token = load_credentials()
    session = requests.Session()
    session.auth = (email, token)
    session.headers.update({"Accept": "application/json"})

    print(f"\n📥 페이지 메타 + storage HTML 가져오는 중...")
    page = fetch_page(session, base, page_id)
    title = page["title"]
    version = page.get("version", {}).get("number", 1)
    print(f"   - 제목: {title}")
    print(f"   - 버전: v{version}")

    name = args.output_name or sanitize_filename(title)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / f"{name}.md"
    assets_dir = output_dir / f"{name}.assets"
    assets_rel = f"{name}.assets"

    # 기존 assets 정리 (stale 리소스 잔존 방지)
    if assets_dir.exists():
        shutil.rmtree(assets_dir)

    with tempfile.TemporaryDirectory(prefix="confluence_sync_") as tmp:
        raw_attach = Path(tmp) / "attachments"

        print(f"\n📎 첨부 다운로드...")
        atts = list_attachments(session, base, page_id)
        if not atts:
            print("   - 첨부 없음")
        for att in atts:
            saved = download_attachment(session, base, att, raw_attach)
            if saved:
                print(f"   - {att['title']}")

        print(f"\n🔄 storage HTML → Markdown 변환...")
        md_body, missing = build_markdown(
            page, page_id, raw_attach, assets_dir, assets_rel,
        )

    # body 가 이미 H1 으로 시작하면 페이지 제목 H1 을 추가하지 않는다 (중복 제목 방지).
    title_h1 = "" if md_body.lstrip().startswith("# ") else f"# {title}\n\n"

    # frontmatter
    md_full = (
        "---\n"
        f'confluence_page_id: "{page_id}"\n'
        f'confluence_url: "{args.url}"\n'
        f'title: "{title}"\n'
        f"confluence_version: {version}\n"
        f'last_synced: "{datetime.datetime.now().isoformat(timespec="seconds")}"\n'
        "---\n\n"
        f"{title_h1}"
        f"{md_body.rstrip()}\n"
    )
    md_path.write_text(md_full, encoding="utf-8")

    print(f"\n✅ 저장 완료")
    print(f"   📄 {md_path.relative_to(WS_ROOT)}")
    if assets_dir.exists() and any(assets_dir.iterdir()):
        n = sum(1 for _ in assets_dir.iterdir())
        print(f"   📂 {assets_dir.relative_to(WS_ROOT)}/  ({n}개 리소스)")
    if missing:
        print(f"\n⚠ 본문에서 참조하지만 첨부 다운로드되지 않은 파일:")
        for fn in sorted(missing):
            print(f"   - {fn}")
    print()


if __name__ == "__main__":
    main()
