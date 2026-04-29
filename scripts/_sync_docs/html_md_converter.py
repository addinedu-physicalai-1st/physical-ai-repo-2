"""Confluence storage HTML → 일반 HTML → Markdown 변환 헬퍼.

sync_one_page.py 가 import 해서 사용한다.
"""

import html as html_lib
import re
from html.parser import HTMLParser


_DRAWIO_PLACEHOLDER = "<!--DRAWIO_PLACEHOLDER_{n}-->"


# ─── 1) Confluence storage HTML → 일반 HTML ───────────────────────────

def transform_storage_html(storage_html: str, attachment_map: dict, missing: set) -> str:
    """ac:* / ri:* 태그를 일반 HTML로 치환."""
    html = storage_html

    # ac:image (paired) → <img>
    def repl_image(m):
        attrs = m.group(1)
        inner = m.group(2)
        fn_m = re.search(r'ri:filename="([^"]+)"', inner)
        ri_url_m = re.search(r'<ri:url\s+ri:value="([^"]+)"', inner)

        alt_m = re.search(r'ac:alt="([^"]+)"', attrs)
        alt = html_lib.escape(alt_m.group(1)) if alt_m else ""

        w_m = re.search(r'ac:width="([^"]+)"', attrs)
        width_attr = f' width="{w_m.group(1)}"' if w_m else ""

        align_m = re.search(r'ac:align="([^"]+)"', attrs)
        align = align_m.group(1) if align_m else None

        if fn_m:
            filename = fn_m.group(1)
            if filename in attachment_map:
                src = attachment_map[filename]
                tag = f'<img src="{src}" alt="{alt}"{width_attr} />'
            else:
                missing.add(filename)
                tag = (f'<span class="attachment-missing">📎 {html_lib.escape(filename)} '
                       f'(첨부 다운로드 필요)</span>')
        elif ri_url_m:
            tag = f'<img src="{ri_url_m.group(1)}" alt="{alt}"{width_attr} />'
        else:
            return ""

        if align in ("center", "right", "left"):
            return f'<div style="text-align:{align}">{tag}</div>'
        return tag

    html = re.sub(r"<ac:image([^>]*?)(?<!/)>(.*?)</ac:image>",
                  repl_image, html, flags=re.DOTALL)
    html = re.sub(r"<ac:image[^>]*/>", "", html)

    # ac:link with ri:attachment / ri:page → <a>
    def repl_link(m):
        inner = m.group(1)
        fn_m = re.search(r'ri:filename="([^"]+)"', inner)
        page_m = re.search(r'<ri:page[^>]*ri:content-title="([^"]+)"', inner)
        body_m = re.search(
            r"<ac:plain-text-link-body><!\[CDATA\[(.*?)\]\]></ac:plain-text-link-body>",
            inner, re.DOTALL,
        )
        rich_m = re.search(r"<ac:link-body>(.*?)</ac:link-body>", inner, re.DOTALL)
        text = body_m.group(1) if body_m else (rich_m.group(1) if rich_m else "")

        if fn_m:
            filename = fn_m.group(1)
            if filename in attachment_map:
                href = attachment_map[filename]
            else:
                missing.add(filename)
                href = f"attachments/{filename}"
            return f'<a href="{href}">{html_lib.escape(text or filename)}</a>'
        if page_m:
            title = page_m.group(1)
            return f'<a href="#{html_lib.escape(title)}">{html_lib.escape(text or title)}</a>'
        return text

    html = re.sub(r"<ac:link[^>]*>(.*?)</ac:link>",
                  repl_link, html, flags=re.DOTALL)

    # ac:structured-macro: code → <pre><code>
    def repl_code(m):
        block = m.group(0)
        lang_m = re.search(r'<ac:parameter ac:name="language">([^<]*)</ac:parameter>', block)
        body_m = re.search(
            r"<ac:plain-text-body><!\[CDATA\[(.*?)\]\]></ac:plain-text-body>",
            block, re.DOTALL,
        )
        lang = lang_m.group(1) if lang_m else ""
        body = body_m.group(1) if body_m else ""
        body_esc = body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        cls = f' class="language-{lang}"' if lang else ""
        return f"<pre><code{cls}>{body_esc}</code></pre>"

    html = re.sub(
        r'<ac:structured-macro\s+ac:name="code"[^>]*>.*?</ac:structured-macro>',
        repl_code, html, flags=re.DOTALL,
    )

    # info / note / warning / tip / panel → <div class="...">
    for name in ("info", "note", "warning", "tip", "panel"):
        def make_repl(n):
            def repl(m):
                rich = re.search(r"<ac:rich-text-body>(.*?)</ac:rich-text-body>",
                                 m.group(0), re.DOTALL)
                body = rich.group(1) if rich else ""
                return f'<div class="{n}">{body}</div>'
            return repl
        html = re.sub(
            rf'<ac:structured-macro\s+ac:name="{name}"[^>]*>.*?</ac:structured-macro>',
            make_repl(name), html, flags=re.DOTALL,
        )

    # 그 외 매크로는 rich/plain body 만 살리고 껍데기 제거
    def repl_macro(m):
        block = m.group(0)
        rich = re.search(r"<ac:rich-text-body>(.*?)</ac:rich-text-body>",
                         block, re.DOTALL)
        if rich:
            return rich.group(1)
        plain = re.search(r"<ac:plain-text-body><!\[CDATA\[(.*?)\]\]></ac:plain-text-body>",
                          block, re.DOTALL)
        if plain:
            esc = plain.group(1).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            return f"<pre>{esc}</pre>"
        return ""

    html = re.sub(
        r"<ac:structured-macro[^>]*>.*?</ac:structured-macro>",
        repl_macro, html, flags=re.DOTALL,
    )
    html = re.sub(r"<ac:structured-macro[^>]*/>", "", html)

    # 인라인 ac:* / ri:* 잔여 제거
    html = re.sub(r"<ac:[a-z-]+[^>]*/>", "", html)
    html = re.sub(r"<ac:[a-z-]+[^>]*>(.*?)</ac:[a-z-]+>", r"\1", html, flags=re.DOTALL)
    html = re.sub(r"<ri:[^>]*/>", "", html)
    html = re.sub(r"</?ri:[^>]+>", "", html)

    # Confluence 전용 속성 제거
    html = re.sub(
        r'\s+(?:local-id|ac:[\w-]+|ri:[\w-]+|data-(?:layout|highlight-colour|card-appearance))="[^"]*"',
        "", html,
    )

    # 빈 self-closing <p /> 같은 것들 정리
    html = re.sub(r"<p\s*/>", "", html)
    html = re.sub(r"<p>\s*</p>", "", html)

    return html.strip()


# ─── 2) 일반 HTML → Markdown ─────────────────────────────────────────

class HTMLToMarkdown(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out = []
        self.list_stack = []
        self.list_counters = []
        self.heading_level = 0
        self.heading_text = ""
        self.in_link = False
        self.link_href = ""
        self.link_text = ""
        self.in_pre = False
        self.pre_text = ""
        self.in_pre_code_lang = ""
        self.in_table = False
        self.table_rows = []
        self.current_row = []
        self.current_cell = ""
        self.in_cell = False

    def _emit(self, s):
        if self.in_pre:
            self.pre_text += s
        elif self.heading_level > 0:
            self.heading_text += s
        elif self.in_link:
            self.link_text += s
        elif self.in_cell:
            self.current_cell += s
        else:
            self.out.append(s)

    def handle_starttag(self, tag, attrs):
        ad = dict(attrs)
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.heading_level = int(tag[1]); self.heading_text = ""
        elif tag in ("strong", "b"): self._emit("**")
        elif tag in ("em", "i"): self._emit("*")
        elif tag == "code" and not self.in_pre: self._emit("`")
        elif tag == "pre":
            self.in_pre = True; self.pre_text = ""; self.in_pre_code_lang = ""
        elif tag == "a":
            self.in_link = True
            self.link_href = ad.get("href", ""); self.link_text = ""
        elif tag == "ul":
            self.list_stack.append("ul"); self.list_counters.append(0)
        elif tag == "ol":
            self.list_stack.append("ol"); self.list_counters.append(0)
        elif tag == "li":
            if self.in_cell:
                # 표 셀 안의 리스트는 마커 없이 텍스트만 셀에 누적.
                # Confluence 가 셀의 "-" 한 글자를 <ul><li></li></ul> 로 변환해 저장하는 경우가 있어,
                # 셀 바깥(self.out)으로 빈 "- " 가 새지 않도록 한다.
                if self.current_cell and not self.current_cell.endswith(" "):
                    self.current_cell += " "
            else:
                indent = "  " * max(0, len(self.list_stack) - 1)
                if self.list_stack and self.list_stack[-1] == "ol":
                    self.list_counters[-1] += 1
                    self.out.append(f"\n{indent}{self.list_counters[-1]}. ")
                else:
                    self.out.append(f"\n{indent}- ")
        elif tag == "br": self._emit("  \n")
        elif tag == "table":
            self.in_table = True; self.table_rows = []
        elif tag in ("td", "th"):
            self.in_cell = True; self.current_cell = ""
        elif tag == "tr": self.current_row = []
        elif tag == "img":
            src = ad.get("src", ""); alt = ad.get("alt", "")
            self._emit(f"![{alt}]({src})")
        elif tag == "video":
            src = ad.get("src", "")
            self._emit(f"\n\n[📹 video: {src}]({src})\n\n")
        elif tag == "div":
            cls = ad.get("class", "")
            if cls in ("info", "note", "warning", "tip", "panel"):
                self.out.append(f"\n\n> **[{cls.upper()}]** ")
        elif tag == "p":
            pass

    def handle_endtag(self, tag):
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.out.append(f'\n\n{"#" * self.heading_level} {self.heading_text.strip()}\n')
            self.heading_level = 0
        elif tag == "p": self.out.append("\n\n")
        elif tag in ("strong", "b"): self._emit("**")
        elif tag in ("em", "i"): self._emit("*")
        elif tag == "code" and not self.in_pre: self._emit("`")
        elif tag == "pre":
            lang = self.in_pre_code_lang or ""
            self.out.append(f"\n```{lang}\n{self.pre_text}\n```\n\n")
            self.in_pre = False; self.pre_text = ""; self.in_pre_code_lang = ""
        elif tag == "a":
            self.in_link = False
            if self.link_href:
                self._emit(f"[{self.link_text}]({self.link_href})")
            else:
                self._emit(self.link_text)
        elif tag in ("ul", "ol"):
            if self.list_stack: self.list_stack.pop()
            if self.list_counters: self.list_counters.pop()
            if not self.list_stack and not self.in_cell: self.out.append("\n")
        elif tag in ("td", "th"):
            self.in_cell = False
            self.current_row.append(self.current_cell.strip().replace("\n", " "))
        elif tag == "tr": self.table_rows.append(self.current_row)
        elif tag == "table":
            self.in_table = False; self._render_table()
        elif tag == "div":
            self.out.append("\n\n")

    def handle_startendtag(self, tag, attrs):
        ad = dict(attrs)
        if tag == "img":
            src = ad.get("src", ""); alt = ad.get("alt", "")
            self._emit(f"![{alt}]({src})")
        elif tag == "br":
            self._emit("  \n")

    def handle_data(self, data):
        clean = data.replace("‍", "").replace("​", "")
        self._emit(clean)

    def handle_entityref(self, name):
        ents = {"amp": "&", "lt": "<", "gt": ">", "quot": '"',
                "apos": "'", "nbsp": " ", "zwj": ""}
        self._emit(ents.get(name, f"&{name};"))

    def handle_charref(self, name):
        try:
            n = int(name[1:], 16) if name.startswith(("x", "X")) else int(name)
            self._emit(chr(n))
        except Exception:
            self._emit(f"&#{name};")

    def _render_table(self):
        if not self.table_rows: return
        max_cols = max(len(r) for r in self.table_rows)
        self.out.append("\n\n")
        for i, row in enumerate(self.table_rows):
            while len(row) < max_cols: row.append("")
            self.out.append("| " + " | ".join(row) + " |\n")
            if i == 0:
                self.out.append("| " + " | ".join(["---"] * max_cols) + " |\n")
        self.out.append("\n")

    def get_md(self):
        text = "".join(self.out)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def html_to_md(plain_html: str) -> str:
    parser = HTMLToMarkdown()
    parser.feed(plain_html)
    return parser.get_md()
