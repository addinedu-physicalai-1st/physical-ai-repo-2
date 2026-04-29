#!/usr/bin/env python3
"""
로컬 docs/<name>.md 의 본문을 Confluence 페이지에 push 한다.

흐름:
  1. 로컬 md 의 frontmatter 에서 page_id / title / confluence_version 추출
  2. Confluence 에서 현재 서버 버전 GET 후 frontmatter 와 비교
     - 서버 버전 > frontmatter 버전 이면 abort (누군가 Confluence 에서 편집함)
  3. 본문(첫 H1 + frontmatter 제외) → storage HTML 로 변환
  4. 본문에서 참조하는 로컬 이미지·drawio 본체를 서버 첨부와 동기화
     - 서버에 없으면 새 첨부로 업로드
     - 있고 파일 크기가 다르면 새 버전으로 업데이트 (변경된 .drawio 가 매크로 렌더링에 반영됨)
  5. PUT /wiki/rest/api/content/{id} 로 페이지 갱신 (version+1)
  6. 로컬 md 의 frontmatter 에서 confluence_version / last_synced 갱신

사용법:
  python push_page.py docs/system-requirements.md          # dry-run
  python push_page.py docs/system-requirements.md --apply  # 실제 push
  python push_page.py docs/system-requirements.md --apply --force  # 버전 mismatch 무시

프리커밋 안전장치:
  --apply 가 없으면 변환 결과 미리보기만 출력하고 실제 PUT 은 하지 않는다.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

from md_to_confluence import (
    extract_local_drawio_filenames,
    extract_local_image_filenames,
    markdown_to_storage_html,
)

SCRIPT_DIR = Path(__file__).parent.resolve()
WS_ROOT = SCRIPT_DIR.parent.parent
DOCS_DIR = WS_ROOT / "docs"
ENV_FILE = WS_ROOT / ".env"


# ─── frontmatter 처리 ───────────────────────────────────────────────

_FM_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
_FM_LINE_RE = re.compile(r"^(\w[\w-]*)\s*:\s*(.*)$")


def read_local_md(path: Path) -> tuple[dict[str, str], str]:
    """frontmatter (dict) 와 본문 (str) 를 반환. frontmatter 가 없으면 dict 는 빈 dict."""
    text = path.read_text(encoding="utf-8")
    m = _FM_RE.match(text)
    if not m:
        return {}, text

    meta: dict[str, str] = {}
    for line in m.group(1).split("\n"):
        lm = _FM_LINE_RE.match(line)
        if not lm:
            continue
        key, raw = lm.groups()
        val = raw.strip()
        if (val.startswith('"') and val.endswith('"')) or (
            val.startswith("'") and val.endswith("'")
        ):
            val = val[1:-1]
        meta[key] = val

    body = m.group(2).lstrip("\n")
    # 첫 번째 H1 제거 (제목은 frontmatter / Confluence 페이지 메타에 있음)
    body = re.sub(r"^#\s+.+\n+", "", body, count=1)
    return meta, body.strip()


def update_frontmatter(path: Path, updates: dict[str, str]) -> None:
    """frontmatter 의 특정 키만 in-place 로 갱신. 다른 라인의 포맷은 보존."""
    text = path.read_text(encoding="utf-8")
    m = _FM_RE.match(text)
    if not m:
        raise RuntimeError(f"frontmatter 가 없습니다: {path}")

    new_lines: list[str] = []
    seen: set[str] = set()
    for line in m.group(1).split("\n"):
        lm = _FM_LINE_RE.match(line)
        if lm and lm.group(1) in updates:
            key = lm.group(1)
            new_lines.append(f"{key}: {updates[key]}")
            seen.add(key)
        else:
            new_lines.append(line)
    for k, v in updates.items():
        if k not in seen:
            new_lines.append(f"{k}: {v}")

    rebuilt = "---\n" + "\n".join(new_lines) + "\n---\n" + m.group(2)
    path.write_text(rebuilt, encoding="utf-8")


# ─── 인증 ───────────────────────────────────────────────────────────

def load_credentials() -> tuple[str, str]:
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE)
    email = os.environ.get("ATLASSIAN_EMAIL", "").strip()
    token = os.environ.get("ATLASSIAN_API_TOKEN", "").strip()
    if not email or not token:
        print("❌ ATLASSIAN_EMAIL / ATLASSIAN_API_TOKEN 가 .env 에 없습니다.")
        print(f"   {ENV_FILE.relative_to(WS_ROOT)} 참고.")
        sys.exit(1)
    return email, token


def base_url_from_meta(meta: dict[str, str]) -> str:
    url = meta.get("confluence_url", "")
    if not url:
        raise RuntimeError("frontmatter 에 confluence_url 이 없습니다.")
    # https://woolimi.atlassian.net/wiki/spaces/FN/pages/40763414/...
    m = re.match(r"^(https?://[^/]+)", url)
    if not m:
        raise RuntimeError(f"confluence_url 형식이 올바르지 않습니다: {url}")
    return m.group(1)


# ─── Confluence API ─────────────────────────────────────────────────

def get_page(session: requests.Session, base: str, page_id: str) -> dict:
    url = f"{base}/wiki/rest/api/content/{page_id}"
    r = session.get(url, params={"expand": "version,space,body.storage"})
    if r.status_code == 404:
        print(f"❌ 페이지 {page_id} 를 찾을 수 없습니다 (404).")
        sys.exit(1)
    r.raise_for_status()
    return r.json()


def list_attachments(session: requests.Session, base: str, page_id: str) -> dict[str, dict]:
    """{filename: {"id": attachment_id, "size": int|None}}."""
    out: dict[str, dict] = {}
    start, limit = 0, 50
    while True:
        url = f"{base}/wiki/rest/api/content/{page_id}/child/attachment"
        r = session.get(url, params={"start": start, "limit": limit, "expand": "extensions"})
        if r.status_code == 404:
            return {}
        r.raise_for_status()
        data = r.json()
        for a in data.get("results", []):
            out[a["title"]] = {
                "id": a["id"],
                "size": a.get("extensions", {}).get("fileSize"),
            }
        if data.get("size", 0) < limit:
            break
        start += limit
    return out


def upload_attachment(
    session: requests.Session, base: str, page_id: str, filepath: Path
) -> None:
    """새 첨부 생성."""
    url = f"{base}/wiki/rest/api/content/{page_id}/child/attachment"
    headers = {"X-Atlassian-Token": "nocheck"}
    with open(filepath, "rb") as f:
        files = {"file": (filepath.name, f)}
        data = {"minorEdit": "true"}
        r = session.post(url, headers=headers, files=files, data=data)
    r.raise_for_status()


def update_attachment(
    session: requests.Session, base: str, page_id: str,
    attachment_id: str, filepath: Path,
) -> None:
    """기존 첨부에 새 버전 업로드."""
    url = f"{base}/wiki/rest/api/content/{page_id}/child/attachment/{attachment_id}/data"
    headers = {"X-Atlassian-Token": "nocheck"}
    with open(filepath, "rb") as f:
        files = {"file": (filepath.name, f)}
        data = {"minorEdit": "true"}
        r = session.post(url, headers=headers, files=files, data=data)
    r.raise_for_status()


def delete_attachment(
    session: requests.Session, base: str, attachment_id: str,
) -> bool:
    """첨부 삭제 (휴지통). 이미 없거나 권한 문제면 False."""
    url = f"{base}/wiki/rest/api/content/{attachment_id}"
    r = session.delete(url)
    if r.status_code in (200, 204):
        return True
    if r.status_code == 404:
        return False
    print(f"   ⚠ 첨부 삭제 실패 {attachment_id}: {r.status_code} {r.text[:200]}")
    return False


# ─── drawio 매크로 cust-content 캐시 무효화 ──────────────────────────
#
# Forge drawio 매크로는 매크로 XML 의 `revision`/`content-ver` 와 cust-content 의
# `revision` 이 일치하는 동안 캐시된 렌더링을 그대로 사용한다. 따라서 첨부 .drawio
# 본체를 새 버전으로 올려도 매크로의 revision 이 그대로면 새 다이어그램이 보이지
# 않는다. 이 함수는 두 곳을 모두 +1 하여 캐시를 무효화한다.

_CUST_CONTENT_ID_RE = re.compile(
    r'<ac:adf-parameter key="cust-content-id">(\d+)</ac:adf-parameter>'
)
_MACRO_REV_RE = re.compile(
    r'(<ac:adf-parameter key="revision" type="integer">)\d+(</ac:adf-parameter>)'
)
_MACRO_CONTENT_VER_RE = re.compile(
    r'(<ac:adf-parameter key="content-ver" type="integer">)\d+(</ac:adf-parameter>)'
)


def _macro_cust_content_id(macro_xml: str) -> str | None:
    m = _CUST_CONTENT_ID_RE.search(macro_xml)
    return m.group(1) if m else None


def _bump_macro_xml_revisions(macro_xml: str, new_rev: int) -> str:
    """매크로 XML 의 revision 과 content-ver 를 동일한 새 값으로 교체."""
    macro_xml = _MACRO_REV_RE.sub(rf"\g<1>{new_rev}\g<2>", macro_xml)
    macro_xml = _MACRO_CONTENT_VER_RE.sub(rf"\g<1>{new_rev}\g<2>", macro_xml)
    return macro_xml


def bump_drawio_cust_content(
    session: requests.Session,
    base: str,
    page_id: str,
    macro_path: Path,
) -> bool:
    """매크로 sidecar (.macro.xml) 와 그것이 가리키는 cust-content 의 revision 을
    동기화해서 +1 한다.

    Returns: True 면 성공, False 면 cust-content-id 가 없거나 실패해서 skip.
    """
    macro_text = macro_path.read_text(encoding="utf-8")
    cid = _macro_cust_content_id(macro_text)
    if not cid:
        return False

    r = session.get(
        f"{base}/wiki/rest/api/content/{cid}",
        params={"expand": "body.raw,version,container,space"},
    )
    if not r.ok:
        print(f"   ❌ cust-content {cid} GET 실패: {r.status_code} {r.text[:200]}")
        return False
    d = r.json()
    try:
        raw = json.loads(d["body"]["raw"]["value"])
    except Exception as e:
        print(f"   ❌ cust-content {cid} body.raw 파싱 실패: {e}")
        return False

    new_rev = int(raw.get("revision", 0)) + 1
    raw["revision"] = new_rev
    new_raw_json = json.dumps(raw, ensure_ascii=False)
    new_version = int(d["version"]["number"]) + 1

    payload = {
        "id": cid,
        "type": d["type"],
        "title": d["title"],
        "space": {"key": d["space"]["key"]},
        "container": {
            "id": d["container"]["id"],
            "type": d["container"]["type"],
        },
        "version": {"number": new_version, "minorEdit": False},
        "body": {"raw": {"value": new_raw_json, "representation": "raw"}},
    }
    p = session.put(f"{base}/wiki/rest/api/content/{cid}", json=payload)
    if not p.ok:
        print(f"   ❌ cust-content {cid} PUT 실패: {p.status_code} {p.text[:200]}")
        return False

    new_macro = _bump_macro_xml_revisions(macro_text, new_rev)
    if new_macro != macro_text:
        macro_path.write_text(new_macro, encoding="utf-8")

    print(f"   ⏫ cust-content {cid} revision → {new_rev} (page-version v{new_version})")
    return True


def update_page(
    session: requests.Session,
    base: str,
    page_id: str,
    title: str,
    storage_html: str,
    new_version: int,
) -> dict:
    url = f"{base}/wiki/rest/api/content/{page_id}"
    payload = {
        "id": page_id,
        "type": "page",
        "title": title,
        "version": {"number": new_version, "minorEdit": False},
        "body": {"storage": {"value": storage_html, "representation": "storage"}},
    }
    r = session.put(url, json=payload)
    if r.status_code >= 400:
        print(f"❌ 페이지 업데이트 실패: {r.status_code}")
        print(f"   {r.text[:500]}")
        r.raise_for_status()
    return r.json()


# ─── push 본체 ──────────────────────────────────────────────────────

def push(
    md_path: Path,
    *,
    apply: bool,
    force: bool,
    show_html: bool,
) -> int:
    if not md_path.exists():
        print(f"❌ 파일 없음: {md_path}")
        return 1

    meta, body = read_local_md(md_path)
    page_id = meta.get("confluence_page_id", "")
    title = meta.get("title", "")
    local_version_str = meta.get("confluence_version", "")
    if not page_id or not title or not local_version_str:
        print("❌ frontmatter 에 confluence_page_id / title / confluence_version 가 필요합니다.")
        return 1
    try:
        local_version = int(local_version_str)
    except ValueError:
        print(f"❌ confluence_version 이 정수가 아닙니다: {local_version_str!r}")
        return 1

    print(f"📄 {md_path.relative_to(WS_ROOT)}")
    print(f"   page_id : {page_id}")
    print(f"   title   : {title}")
    print(f"   version : v{local_version} (local frontmatter)")

    assets_dir = md_path.parent / f"{md_path.stem}.assets"
    storage_html = markdown_to_storage_html(
        body, assets_dir=assets_dir if assets_dir.exists() else None,
    )
    referenced_imgs = extract_local_image_filenames(body)
    referenced_drawio = extract_local_drawio_filenames(body)

    if show_html:
        print("\n--- storage HTML preview (앞 1500자) ---")
        print(storage_html[:1500])
        if len(storage_html) > 1500:
            print(f"... ({len(storage_html) - 1500}자 더)")
        print("--- end preview ---\n")

    if not apply:
        print(f"\n[dry-run] 참조 이미지: {referenced_imgs or '(없음)'}")
        print(f"[dry-run] 참조 drawio: {referenced_drawio or '(없음)'}")
        print(f"[dry-run] storage HTML 길이: {len(storage_html)}자")
        print("[dry-run] --apply 로 실제 push.")
        return 0

    base = base_url_from_meta(meta)
    email, token = load_credentials()
    session = requests.Session()
    session.auth = (email, token)
    session.headers.update({"Accept": "application/json"})

    print(f"\n📡 GET 현재 서버 버전 ({base})...")
    page = get_page(session, base, page_id)
    server_version = page["version"]["number"]
    server_title = page["title"]
    print(f"   서버 버전: v{server_version}")

    if server_version != local_version and not force:
        print(
            f"\n❌ 버전 불일치: local frontmatter v{local_version} ≠ 서버 v{server_version}.\n"
            "   누군가 Confluence 에서 편집했을 수 있습니다.\n"
            "   먼저 'scripts/pull_docs.sh' 로 pull 한 뒤 변경사항을 머지하거나,\n"
            "   --force 로 덮어쓸 수 있습니다 (서버 변경사항 손실)."
        )
        return 2
    if server_title != title:
        print(f"⚠ 제목 차이 — local: {title!r}, server: {server_title!r}. local 값으로 push 합니다.")

    # 첨부 동기화 — 본문에서 참조하는 이미지와 drawio 본체 모두.
    # 서버에 없으면 새로 업로드, 있고 파일 크기가 다르면 새 버전으로 업데이트.
    changed_drawio: list[str] = []
    referenced_files = list(dict.fromkeys(referenced_imgs + referenced_drawio))
    if referenced_files:
        server_atts = list_attachments(session, base, page_id)
        for fn in referenced_files:
            local_file = assets_dir / fn
            if not local_file.exists():
                if fn not in server_atts:
                    print(f"   ⚠ 본문에서 참조하지만 로컬·서버 어디에도 없음: {fn}")
                continue
            local_size = local_file.stat().st_size
            srv = server_atts.get(fn)
            if srv is None:
                try:
                    upload_attachment(session, base, page_id, local_file)
                    print(f"   📎 업로드: {fn}")
                except requests.HTTPError as e:
                    print(f"   ❌ 업로드 실패 {fn}: {e.response.status_code} {e.response.text[:200]}")
                    return 3
                if fn.endswith(".drawio"):
                    changed_drawio.append(fn)
                continue
            srv_size = srv["size"]
            if srv_size is not None and srv_size == local_size:
                continue  # 동일 크기 — 변경 없다고 가정 (false negative 가능, 시급하면 첨부를 직접 갱신)
            try:
                update_attachment(session, base, page_id, srv["id"], local_file)
                print(f"   ♻ 업데이트: {fn} ({srv_size}B → {local_size}B)")
            except requests.HTTPError as e:
                print(f"   ❌ 업데이트 실패 {fn}: {e.response.status_code} {e.response.text[:200]}")
                return 3
            if fn.endswith(".drawio"):
                changed_drawio.append(fn)

    # 변경된 .drawio 가 있으면 매크로 cust-content + .macro.xml revision 을 +1 해서
    # Forge drawio 매크로의 캐시를 무효화 → 새 다이어그램이 렌더링되도록 함.
    if changed_drawio:
        for fn in changed_drawio:
            base_name = fn[:-7] if fn.endswith(".drawio") else fn
            macro_path = assets_dir / f"{base_name}.macro.xml"
            if not macro_path.exists():
                continue
            bump_drawio_cust_content(session, base, page_id, macro_path)
        # .macro.xml 이 갱신됐으니 storage HTML 을 새 매크로 XML 로 다시 합성.
        storage_html = markdown_to_storage_html(
            body, assets_dir=assets_dir if assets_dir.exists() else None,
        )

    # Forge drawio 편집기는 ~<name>.drawio.tmp (autosave) 가 있으면 그걸 우선
    # 로드한다. 정식 .drawio 만 갱신하면 프리뷰는 새 버전이지만 편집기는
    # 옛날 .tmp 를 보여주는 디싱크가 생긴다. push 의 의미는 "로컬이 정답"
    # 이므로 본문에서 참조하는 .drawio 의 stale .tmp 는 매 push 마다 청소한다.
    # (동시 편집자 보호는 frontmatter 버전 비교가 이미 담당.)
    if referenced_drawio:
        for fn in referenced_drawio:
            tmp_name = f"~{fn}.tmp"
            srv = server_atts.get(tmp_name)
            if not srv:
                continue
            if delete_attachment(session, base, srv["id"]):
                print(f"   🗑  stale autosave 삭제: {tmp_name}")

    target_version = server_version + 1
    print(f"\n📤 PUT 페이지 업데이트 (v{server_version} → v{target_version})...")
    update_page(session, base, page_id, title, storage_html, target_version)

    # PUT 응답이 새 버전을 echo 해도 Confluence 가 동일 콘텐츠라고 판단하면
    # 실제로는 새 버전을 만들지 않는 경우가 있다. 한 번 더 GET 으로 실제 버전 확인.
    final_page = get_page(session, base, page_id)
    actual_version = final_page["version"]["number"]
    if actual_version == target_version:
        print(f"   ✅ 성공: v{actual_version}")
    else:
        print(
            f"   ✅ PUT 성공했지만 실제 저장된 버전은 v{actual_version} "
            f"(목표 v{target_version}) — Confluence 가 동일 콘텐츠로 판단해 dedup."
        )

    # frontmatter 갱신
    now_iso = datetime.datetime.now().isoformat(timespec="seconds")
    update_frontmatter(
        md_path,
        {
            "confluence_version": str(actual_version),
            "last_synced": f'"{now_iso}"',
        },
    )
    print(f"   📝 frontmatter 갱신: confluence_version={actual_version}, last_synced={now_iso}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="로컬 docs/<name>.md → Confluence 페이지 push",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("md_path", help="docs/ 안의 markdown 파일 경로")
    parser.add_argument(
        "--apply", action="store_true",
        help="실제로 PUT 한다 (없으면 dry-run).",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="서버 버전이 frontmatter 버전과 다를 때도 강제로 덮어쓴다.",
    )
    parser.add_argument(
        "--show-html", action="store_true",
        help="변환된 storage HTML 앞부분을 미리보기로 출력.",
    )
    args = parser.parse_args()

    return push(
        Path(args.md_path).resolve(),
        apply=args.apply,
        force=args.force,
        show_html=args.show_html,
    )


if __name__ == "__main__":
    sys.exit(main())
