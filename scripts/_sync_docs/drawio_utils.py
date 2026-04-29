"""
Confluence storage HTML 안에서 drawio 매크로를 검출하고, 페이지 첨부 디렉토리에서
diagram 본체 (.drawio) 와 PNG 프리뷰를 찾는 유틸.

지원 매크로 종류:
  - static/inc-drawio  (Embed draw.io Diagram)  — `diagram-display-name`
  - static/drawio      (draw.io Diagram)        — `diagram-name`
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


# ─── 1) Confluence storage HTML 안에서 drawio 매크로 추출 ─────────────

@dataclass
class DrawioMacro:
    """페이지 안의 drawio 임베드 한 개."""
    kind: str               # "drawio" | "inc-drawio"
    diagram_name: str       # 출력 파일 베이스명 (display-name 우선)
    attachment_name: str    # Confluence 실제 첨부 파일명 — 첨부 탐색에 사용
    width: str | None = None
    height: str | None = None
    raw_block: str = ""     # 매크로 블록 원본 — replace 시 사용


_PARAM_RE = re.compile(
    r'<ac:adf-parameter\s+key="([^"]+)"(?:\s+type="[^"]+")?>(.*?)</ac:adf-parameter>',
    re.DOTALL,
)
_EXT_BLOCK_RE = re.compile(r"<ac:adf-extension\b.*?</ac:adf-extension>", re.DOTALL)
# guest-params 중첩 구조 안의 diagram-name 을 직접 추출 — _extract_params 의 비탐욕 매칭이
# 중첩 태그를 삼켜 diagram-name 키가 params 에 들어오지 않는 문제를 우회한다.
_DIAGRAM_NAME_RE = re.compile(r'key="diagram-name">([^<]+)</ac:adf-parameter>')


def _extract_params(block: str) -> dict[str, str]:
    """adf-parameter 들을 평탄화. 중첩 태그는 텍스트만 살린다."""
    out: dict[str, str] = {}
    for m in _PARAM_RE.finditer(block):
        k = m.group(1)
        v_raw = m.group(2)
        # 중첩 태그 제거
        v = re.sub(r"<[^>]+>", " ", v_raw).strip()
        # 첫번째 값을 우선 (Confluence 가 fallback 으로 같은 블록을 한 번 더 넣어둠)
        out.setdefault(k, v)
    return out


def find_drawio_macros(storage_html: str) -> list[DrawioMacro]:
    """storage HTML 에서 drawio 임베드를 모두 찾는다."""
    out: list[DrawioMacro] = []
    seen_local_ids: set[str] = set()  # ADF 가 fallback 으로 두 번 들어있어 중복 제거
    for m in _EXT_BLOCK_RE.finditer(storage_html):
        block = m.group(0)
        if "drawio" not in block:
            continue
        params = _extract_params(block)
        # extension-id 는 adf-parameter 또는 adf-attribute(extension-key) 어느 쪽에도 올 수 있음.
        ext_marker = params.get("extension-id", "")
        if not ext_marker:
            m_attr = re.search(
                r'<ac:adf-attribute key="extension-key">([^<]+)</ac:adf-attribute>', block
            )
            if m_attr:
                ext_marker = m_attr.group(1).strip()

        # guest-params 안의 실제 첨부 파일명 (diagram-name) 을 직접 추출.
        # _extract_params 의 비탐욕 매칭은 중첩 구조 탓에 이 키를 꺼내지 못한다.
        dn_match = _DIAGRAM_NAME_RE.search(block)
        raw_attach_name = dn_match.group(1).strip() if dn_match else None

        if "inc-drawio" in ext_marker:
            kind = "inc-drawio"
            name = (params.get("diagram-display-name")
                    or params.get("guest-params") or "").strip()
        elif "drawio" in ext_marker:
            kind = "drawio"
            # diagram-display-name = 사용자가 변경한 표시명, diagram-name = 실제 첨부명.
            # 출력 파일명은 표시명 우선, 없으면 실제 첨부명으로 fallback.
            name = (params.get("diagram-display-name")
                    or raw_attach_name or "").strip()
        else:
            continue

        if not name:
            continue

        local_id = params.get("local-id", "")
        # local-id 없으면 name+block_pos 로 dedupe
        dedupe_key = local_id or f"{name}@{m.start()}"
        if dedupe_key in seen_local_ids:
            continue
        seen_local_ids.add(dedupe_key)

        out.append(DrawioMacro(
            kind=kind,
            diagram_name=name,
            attachment_name=raw_attach_name or name,
            width=params.get("width"),
            height=params.get("height"),
            raw_block=block,
        ))
    return out


# ─── 2) 파일 헬퍼 ───────────────────────────────────────────────────

def find_drawio_source(attach_dir: Path, diagram_name: str) -> Path | None:
    """페이지 첨부 디렉토리에서 diagram 의 본체 (mxfile) 파일을 찾는다.

    drawio 본체는 다음 형태로 저장됨:
      - "<name>"                (확장자 없음, inc-drawio)
      - "<name>.drawio"         (drawio)
    프리뷰 png 와 임시 ~tmp 는 제외한다.
    """
    if not attach_dir.exists():
        return None

    candidates: list[Path] = []
    direct = attach_dir / diagram_name
    if direct.exists() and direct.is_file():
        candidates.append(direct)

    # mxfile 인지 검증 → 첫 줄 확인
    for p in candidates:
        try:
            head = p.read_bytes()[:200]
            if b"<mxfile" in head or b"<mxGraphModel" in head:
                return p
        except Exception:
            continue
    return None


def find_drawio_preview(attach_dir: Path, diagram_name: str) -> Path | None:
    """diagram 의 PNG 프리뷰 파일.

    drawio 첨부 패턴:
      - <base>.png            — 종종 88B placeholder
      - <base>-<hash>.png     — 실제 렌더링된 PNG
      - <name>.png            — drawio 원본이 .drawio 로 끝날 때
    크기가 가장 큰 것을 진짜 프리뷰로 선택한다.
    """
    if not attach_dir.exists():
        return None
    base = diagram_name
    if base.endswith(".drawio"):
        base = base[: -len(".drawio")]

    candidates: list[Path] = []
    # 정확 매치
    for c in (attach_dir / f"{base}.png", attach_dir / f"{diagram_name}.png"):
        if c.exists() and c.is_file():
            candidates.append(c)
    # 해시 접미사
    for p in attach_dir.glob(f"{base}-*.png"):
        candidates.append(p)
    if base != diagram_name:
        for p in attach_dir.glob(f"{diagram_name}-*.png"):
            candidates.append(p)

    if not candidates:
        return None
    # 동일한 파일이 중복으로 들어갈 수 있음 → 경로로 dedupe
    seen, uniq = set(), []
    for c in candidates:
        rp = c.resolve()
        if rp in seen:
            continue
        seen.add(rp)
        uniq.append(c)
    # 100B 미만은 placeholder 로 간주하고 후보에서 제외 (모두 placeholder 면 fallback)
    real = [c for c in uniq if c.stat().st_size > 200]
    pool = real or uniq
    return max(pool, key=lambda p: p.stat().st_size)
