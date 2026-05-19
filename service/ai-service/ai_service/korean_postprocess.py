"""한국어 후처리 — 모델 출력에서 흔한 형태 오류만 최소로 교정."""

import json
import re
from typing import Any

try:
    from es_hangul import disassemble as _es_hangul_disassemble
    from es_hangul import josa as _es_hangul_josa
except ImportError:
    _es_hangul_josa = None  # type: ignore[misc, assignment]
    _es_hangul_disassemble = None  # type: ignore[misc, assignment]


def report_address_name(registered_full_name: str) -> str:
    """DB `child.name`(보통 성+이름)에서 보고서 호칭용 이름 추정.

    - `given_name` 컬럼이 있으면 Control 쪽에서 그걸 쓰고, 여기는 비어 있을 때만 호출.
    - 한글 3글자 이상: 앞 1글자를 성으로 보고 나머지를 호칭.
    - 한글 2글자: 성+이름(각 1글자)으로 보고 통째로 유지.
    - 비한글 등: 공백 제거 원문 유지.
    """
    n = (registered_full_name or "").strip()
    if len(n) < 2:
        return n
    if all("\uac00" <= c <= "\ud7a3" for c in n):
        if len(n) == 2:
            return n
        return n[1:]
    return n


def scrub_registered_name_in_report_text(text: str, registered_full: str, address: str) -> str:
    """모델이 등록 전체 이름을 썼을 때 호칭으로 치환."""
    r, a = registered_full.strip(), address.strip()
    if not text or not r or r == a:
        return text
    return text.replace(r, a)


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    la, lb = len(a), len(b)
    dp = list(range(lb + 1))
    for i in range(1, la + 1):
        prev, dp[0] = dp[0], i
        for j in range(1, lb + 1):
            cur = min(dp[j] + 1, dp[j - 1] + 1, prev + (a[i - 1] != b[j - 1]))
            prev, dp[j] = dp[j], cur
    return dp[lb]


def _hangul_syllable_triplet(ch: str) -> tuple[int, int, int] | None:
    if len(ch) != 1 or not ("\uac00" <= ch <= "\ud7a3"):
        return None
    o = ord(ch) - 0xAC00
    jong = o % 28
    jung = (o // 28) % 21
    cho = o // 28 // 21
    return cho, jung, jong


def _triplet_hamming_syllables(a: str, b: str) -> int | None:
    ta = _hangul_syllable_triplet(a)
    tb = _hangul_syllable_triplet(b)
    if ta is None or tb is None:
        return None
    return sum(1 for x, y in zip(ta, tb) if x != y)


def _near_miss_address_spelling(address: str, chunk: str) -> bool:
    """호칭과 길이가 같은 한글 덩어리가 음절 하나만 다르고, 그 음절은 자모 기준 근접 오타인 경우."""
    if len(address) != len(chunk) or len(address) < 2:
        return False
    if not all("\uac00" <= c <= "\ud7a3" for c in address + chunk):
        return False
    if address == chunk:
        return False
    diff_i = [i for i, (x, y) in enumerate(zip(address, chunk)) if x != y]
    if len(diff_i) != 1:
        return False
    ca, cb = address[diff_i[0]], chunk[diff_i[0]]
    if _es_hangul_disassemble is not None:
        try:
            ja = _es_hangul_disassemble(ca)
            jb = _es_hangul_disassemble(cb)
            return _levenshtein(ja, jb) <= 2
        except Exception:
            pass
    th = _triplet_hamming_syllables(ca, cb)
    return th is not None and th <= 2


_NAME_CHUNK_RIGHT_GUARD = re.compile(
    r"^(?:은|는|이|가|을|를|과|와|으로|로|만|도|이랑|랑|하고|과의|,|\.|\)|]|}|…|\"|'|「|」|:|$)",
)


def fix_address_name_hangul_near_miss(address: str, text: str) -> str:
    """LLM 이 보고서 호칭을 한 음절만 비슷하게 틀린 경우(예: 므성→민성) 호칭으로 통일."""
    addr = address.strip()
    k = len(addr)
    if k < 2 or not all("\uac00" <= c <= "\ud7a3" for c in addr):
        return text
    n = len(text)
    out: list[str] = []
    i = 0
    while i < n:
        if i + k <= n:
            chunk = text[i : i + k]
            rest = text[i + k :]
            left_ch = text[i - 1] if i > 0 else ""
            # 앞 음절이 한글이면 복합어 안쪽(예: 「표정으로」의 「정으」)을 호칭 오타로 보지 않음.
            if (
                all("\uac00" <= c <= "\ud7a3" for c in chunk)
                and _near_miss_address_spelling(addr, chunk)
                and _NAME_CHUNK_RIGHT_GUARD.match(rest)
                and not ("\uac00" <= left_ch <= "\ud7a3")
            ):
                out.append(addr)
                i += k
                continue
        out.append(text[i])
        i += 1
    return "".join(out)


_COLLAPSED_NAME_PARTICLE_RE = re.compile(
    r"(?<![가-힣])([가-힣])(은|는|이|가|을|를)(?![가-힣])",
)


def _one_syllable_jamo_near_miss(correct: str, typo: str) -> bool:
    """한 음절끼리 자모 편집 거리가 가까우면 참 (믞→민 등)."""
    if len(correct) != 1 or len(typo) != 1:
        return False
    if not ("\uac00" <= correct <= "\ud7a3" and "\uac00" <= typo <= "\ud7a3"):
        return False
    if correct == typo:
        return False
    if _es_hangul_disassemble is not None:
        try:
            return _levenshtein(_es_hangul_disassemble(correct), _es_hangul_disassemble(typo)) <= 2
        except Exception:
            pass
    th = _triplet_hamming_syllables(correct, typo)
    return th is not None and th <= 2


def fix_garbled_first_syllable_name_particle(address: str, text: str) -> str:
    """첫 음절만 비슷하게 깨지고 둘째 음절이 빠진 뒤 조사가 붙은 경우 (믞은 → 민성은).

    첫 글자가 호칭 첫 글자와 같으면(예: 민은) 한 글자 이름과 구분이 안 되어 건드리지 않는다.
    """
    addr = address.strip()
    if len(addr) < 2 or not all("\uac00" <= c <= "\ud7a3" for c in addr):
        return text
    topic_p = topic_particle_phrase(addr)[len(addr) :]
    subj_p = subject_particle_phrase(addr)[len(addr) :]
    obj_p = object_particle_phrase(addr)[len(addr) :]
    allowed = {topic_p, subj_p, obj_p}

    def repl(m: re.Match[str]) -> str:
        c, p = m.group(1), m.group(2)
        if p not in allowed:
            return m.group(0)
        if c == addr[0]:
            return m.group(0)
        if not _one_syllable_jamo_near_miss(addr[0], c):
            return m.group(0)
        return addr + p

    return _COLLAPSED_NAME_PARTICLE_RE.sub(repl, text)


def fix_truncated_class_name_ideul(class_name: str, text: str) -> str:
    """「햇님반」이 「햇님이들」처럼 반(班)이 빠진 오타로 붙는 경우 →「햇님반 아이들」.

    DB 반 이름이 「…반」으로 끝날 때만, 앞쪽 줄기(반 제거) + 이들(조사) 패턴을 고친다.
    """
    cls = (class_name or "").strip()
    if len(cls) < 2 or not cls.endswith("반"):
        return text
    stem = cls[:-1]
    if not stem or not all("\uac00" <= c <= "\ud7a3" for c in stem):
        return text
    pat = re.escape(stem) + r"이들(과|와|의|은|는|이|가|을|를)?"

    def repl(m: re.Match[str]) -> str:
        suf = m.group(1) or ""
        return f"{cls} 아이들{suf}"

    return re.sub(pat, repl, text)


def fix_class_name_as_timeline_subject(
    address_name: str,
    class_name: str,
    text: str,
    *,
    class_scope: bool | None = None,
) -> str:
    """「햇님반이/가/은/는 …」처럼 반 이름이 통째 주어가 되면 보고서 호칭 주제로 바꾼다.

    - `class_scope` True: 생성 파이프라인 — 맨 앞은 「참여 미확인. 「반」 일과로」, 문장 중간은 「호칭」「반」 일과로.
    - `class_scope` False/None: 조회·저장 후처리 — 맨 앞·마침 뒤 모두 「호칭은/는 …」만 붙인다.
    - 요약 오타 「민성반 아이들」→ DB 반 이름(…반)으로 고친다.
    """
    c = (address_name or "").strip()
    cl = (class_name or "").strip()
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t or not c or not cl:
        return t
    topic = topic_particle_phrase(c)
    esc = re.escape(cl)
    if cl.endswith("반") and c + "반" != cl:
        t = re.sub(rf"{re.escape(c)}반(?=\s*아이들)", cl, t)

    def repl(m: re.Match[str]) -> str:
        pre = m.group(1)
        sp = m.group(4)
        at_line_start = pre == ""
        if class_scope is True:
            if at_line_start:
                return f"{topic} 참여 미확인. 「{cl}」 일과로{sp}"
            return f"{pre}{topic} 「{cl}」 일과로{sp}"
        return f"{pre}{topic}{sp}"

    # 「햇님반이는」「햇님반가는」— 이+는 등 이중 조사 (단일 조사 패턴은 뒤에 공백이 있어야 해서 여기서 먼저 처리)
    stacked_pat = re.compile(
        rf"(^|[。.]\s*)({esc})(이는|가는|은는|는은|이은|가은)(\s+)", re.UNICODE
    )
    t = stacked_pat.sub(repl, t)
    pat = re.compile(rf"(^|[。.]\s*)({esc})(이|가|은|는)(\s+)", re.UNICODE)
    return pat.sub(repl, t)


def fix_expression_record_possessive_phrase(name: str, text: str) -> str:
    """「호칭가 표정이 기록」→「호칭의 표정이 기록」(소유격 — es-hangul `josa` 와 같은 받침 규칙의 주격이 아니라 의)."""
    n = (name or "").strip()
    if not n or not text:
        return text
    return text.replace(f"{n}가 표정이 기록", f"{n}의 표정이 기록")


def _batchim_josa_triplet(name: str) -> tuple[str, str, str]:
    """(주격 이/가, 주제 은/는, 목적어 을/를) 접미만 — es-hangul 과 동일한 받침 규칙."""
    n = name.strip()
    if not n:
        return ("가", "는", "를")
    c = ord(n[-1])
    if 0xAC00 <= c <= 0xD7A3:
        has_batchim = (c - 0xAC00) % 28 != 0
        if has_batchim:
            return ("이", "은", "을")
        return ("가", "는", "를")
    return ("가", "는", "를")


def _subject_particle_suffix(name: str) -> str:
    """이름 마지막 음절이 한글일 때 받침 유무로 주격 조사 '이' 또는 '가' 선택."""
    return _batchim_josa_triplet(name)[0]


def subject_particle_phrase(name: str) -> str:
    """이름 + 주격 조사 (예: 민성 → 민성이, 민주 → 민주가) — PyPI `es-hangul` josa 로 선택."""
    n = name.strip()
    if not n:
        return ""
    if _es_hangul_josa is not None:
        return _es_hangul_josa(n, "이/가")
    return n + _batchim_josa_triplet(n)[0]


def topic_particle_phrase(name: str) -> str:
    """이름 + 주제 조사 은/는 (예: 민성 → 민성은, 민주 → 민주는) — PyPI `es-hangul` josa 로 선택."""
    n = name.strip()
    if not n:
        return ""
    if _es_hangul_josa is not None:
        return _es_hangul_josa(n, "은/는")
    return n + _batchim_josa_triplet(n)[1]


def object_particle_phrase(name: str) -> str:
    """이름 + 목적격 조사 을/를 (예: 민성 → 민성을, 민주 → 민주를) — PyPI `es-hangul` josa 로 선택."""
    n = name.strip()
    if not n:
        return ""
    if _es_hangul_josa is not None:
        return _es_hangul_josa(n, "을/를")
    return n + _batchim_josa_triplet(n)[2]


# 모델이 「이름 + 공백 + 서술」처럼 주격을 뺀 경우만 보수적으로 보완 (다음 어절 접두).
_SUBJECT_GAP_PREFIXES: tuple[str, ...] = (
    "점심시간에",
    "점심을",
    "점심에",
    "오후 간식",
    "간식을",
    "간식에",
    "간식 시간에",
    "낮잠을",
    "낮잠에",
    "낮잠 시간에",
    "낮잠시간에",
    "자유놀이에",
    "자유놀이를",
    "자유놀이",
    "교실 활동",
    "바깥 놀이",
    "실내놀이",
    "참여했",
    "참여하",
    "참여",
    "즐겼",
    "즐기",
    "즐겨",
    "먹었",
    "먹고",
    "먹으며",
    "잤",
    "자고",
    "자며",
    "자면",
    "자지",
    "놀았",
    "놀며",
    "놀고",
    "배웠",
    "읽었",
    "그렸",
    "만들었",
    "만들고",
    "듣고",
    "말했",
    "웃었",
    "울었",
    "있었",
    "없었",
    "많았",
    "적었",
    "나왔",
    "나와",
    "돌아",
    "움직",
    "보였",
    "잠을",
    "등원",
    "하원",
    "교실",
    "바깥",
    "실내",
    "활동",
    "표정",
)


def fix_missing_subject_josa_after_name(name: str, text: str) -> str:
    """「호칭 + 공백 + 동사/명사」처럼 주격이 빠진 흔한 패턴만 주격(이/가)으로 보완."""
    n = name.strip()
    if not n or not text or n not in text:
        return text
    subj = subject_particle_phrase(n)
    t = text
    for pref in sorted(_SUBJECT_GAP_PREFIXES, key=len, reverse=True):
        old = f"{n} {pref}"
        if old not in t:
            continue
        new = f"{subj} {pref}"
        t = t.replace(old, new)
    return t


def fix_wrong_josa_particle_pair(name: str, text: str) -> str:
    """이름+이/가·은/는 중 반대 형만 썼을 때 교정 (_batchim_josa_triplet 규칙)."""
    n = (name or "").strip()
    if not n or not text or n not in text:
        return text
    subj = subject_particle_phrase(n)
    topic = topic_particle_phrase(n)
    a, b, _ = _batchim_josa_triplet(n)
    wrong_subj = n + ("가" if a == "이" else "이")
    wrong_topic = n + ("는" if b == "은" else "은")
    t = text
    if wrong_subj != subj:
        t = t.replace(wrong_subj, subj)
    if wrong_topic != topic:
        t = t.replace(wrong_topic, topic)
    return t


def fix_report_time_josa_artifacts(text: str) -> str:
    """「점심시간은 지나」처럼 시간 명사에 주제 조사가 붙어 '지나다'에 잘못 연결된 경우 → 이/가."""
    if not text:
        return text
    pairs = (
        ("점심시간은 지나", "점심시간이 지나"),
        ("낮잠시간은 지나", "낮잠시간이 지나"),
        ("휴식시간은 지나", "휴식시간이 지나"),
        ("점심 시간은 지나", "점심 시간이 지나"),
        ("낮잠 시간은 지나", "낮잠 시간이 지나"),
        ("휴식 시간은 지나", "휴식 시간이 지나"),
    )
    t = text
    for wrong, right in pairs:
        t = t.replace(wrong, right)
    # 「…시간을 지나했다」— 잘못된 굴절(지내다·지나다 혼동)
    for wrong, right in (
        ("점심시간을 지나했다", "점심시간을 지냈다"),
        ("낮잠시간을 지나했다", "낮잠시간을 지냈다"),
        ("휴식시간을 지나했다", "휴식시간을 지냈다"),
        ("점심 시간을 지나했다", "점심 시간을 지냈다"),
        ("낮잠 시간을 지나했다", "낮잠 시간을 지냈다"),
        ("휴식 시간을 지나했다", "휴식 시간을 지냈다"),
        ("점심시간이 지나했다", "점심시간을 지냈다"),
        ("낮잠시간이 지나했다", "낮잠시간을 지냈다"),
        ("휴식시간이 지나했다", "휴식시간을 지냈다"),
        ("점심 시간이 지나했다", "점심 시간을 지냈다"),
        ("낮잠 시간이 지나했다", "낮잠 시간을 지냈다"),
        ("휴식 시간이 지나했다", "휴식 시간을 지냈다"),
    ):
        t = t.replace(wrong, right)
    return t


def fix_name_gwa_different_children_glitch(name: str, text: str) -> str:
    """「호칭과 다른 아이들」→ 주어는 호칭+이/가 (예: 민성이 다른 아이들과)."""
    n = (name or "").strip()
    if not n or not text or n not in text:
        return text
    subj = subject_particle_phrase(n)
    t = text
    suffixes = (
        "아이들이",
        "아이들을",
        "아이들과",
        "아이들",
        "아이가",
        "아이와",
        "아이",
        "친구들과",
        "친구들",
        "친구",
    )
    for suf in suffixes:
        for spacer in (" ", ""):
            wrong = f"{n}과 다른{spacer}{suf}"
            right = f"{subj} 다른{spacer}{suf}"
            if wrong in t:
                t = t.replace(wrong, right)
    return t


def fix_subject_josa_glitch(name: str, text: str) -> str:
    """모델이 내보내는 「이름이가」「이름가가」·「이름의 친구」류를 정리."""
    n = name.strip()
    if not n or not text:
        return text
    correct = subject_particle_phrase(n)
    t = text.replace(f"{n}이가", correct)
    t = t.replace(f"{n}가가", correct)
    t = re.sub(re.escape(n) + r"의 친구", correct + " 친구", t)
    return t


def fix_stacked_josa_glitch(name: str, text: str) -> str:
    """주격(이/가) 뒤에 또 주제(은/는)·목적(을/를)이 붙은 오류 — 한 조사만 남김.

    예: 민성이는 → 민성은, 민성이을 → 민성을, 민주가는 → 민주는.
    """
    n = name.strip()
    if not n or not text:
        return text
    topic = topic_particle_phrase(n)
    obj = object_particle_phrase(n)
    t = text
    for wrong, right in (
        (f"{n}이는", topic),
        (f"{n}가는", topic),
        (f"{n}이은", topic),
        (f"{n}가은", topic),
        (f"{n}은는", topic),
        (f"{n}는은", topic),
        (f"{n}이을", obj),
        (f"{n}가을", obj),
        (f"{n}이를", obj),
        (f"{n}가를", obj),
    ):
        t = t.replace(wrong, right)
    return t


def strip_cjk_ideographs_from_report_text(text: str) -> str:
    """한자·중·일 문자 등 CJK 통합 한자를 제거(소형 LLM 이 한글 안에 끼워 넣는 오타 방지).

    표준 한글 음절·자모·숫자·공백·일반 구두점은 유지한다.
    """
    if not text:
        return text
    t = re.sub(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", "", text)
    return re.sub(r" {2,}", " ", t).strip()


def _hhmm_to_minutes(s: str) -> int:
    h, _, m = s.strip().partition(":")
    return int(h) * 60 + int(m)


def _minutes_to_hhmm(total: int) -> str:
    total = max(0, min(total, 23 * 60 + 59))
    return f"{total // 60:02d}:{total % 60:02d}"


_ZWSP_RE = re.compile(r"[\ufeff\u200b-\u200d]")


def _canonical_hhmm(hhmm: str) -> str:
    """「9:00」·ZWSP 등을 제거해 일과표 앵커 시각과 비교 가능한 HH:MM 으로 통일."""
    raw = _ZWSP_RE.sub("", (hhmm or "").strip())
    if not raw:
        return ""
    parts = raw.split(":", 1)
    if len(parts) != 2:
        return raw
    try:
        h, m = int(parts[0]), int(parts[1])
    except ValueError:
        return raw
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return raw
    return f"{h:02d}:{m:02d}"


def slot_label_for_schedule_time(schedule: dict[str, str] | None, hhmm: str) -> str:
    """원 일과표 슬롯(예: 09:00-10:00) 중 시각이 포함되는 마지막 활동명(경계는 뒤쪽 슬롯)."""
    if not schedule or not hhmm:
        return ""
    try:
        t0 = _hhmm_to_minutes(hhmm)
    except ValueError:
        return ""
    hit = ""
    for slot, label in schedule.items():
        parts = slot.split("-", 1)
        if len(parts) != 2:
            continue
        try:
            ta = _hhmm_to_minutes(parts[0].strip())
            tb = _hhmm_to_minutes(parts[1].strip())
        except ValueError:
            continue
        if ta <= t0 <= tb:
            hit = label.strip()
    return hit


def _attendance_check_in_out(
    attendance: dict[str, str | None] | None,
) -> tuple[bool, bool]:
    att = attendance or {}
    cin = att.get("check_in_kst")
    cout = att.get("check_out_kst")
    return (
        bool(cin and str(cin).strip()),
        bool(cout and str(cout).strip()),
    )


def _narrative_has_check_in(
    attendance: dict[str, str | None] | None,
    *,
    infer_presence_from_photos: bool,
) -> bool:
    """등원 서술 허용 여부: DB 등원 시각이 있거나, 당일 이 아이 사진이 있으면 참으로 본다."""
    db_in, _ = _attendance_check_in_out(attendance)
    return db_in or infer_presence_from_photos


def use_class_scope_timeline(
    attendance: dict[str, str | None] | None,
    *,
    infer_presence_from_photos: bool,
) -> bool:
    """DB 개인 등·하원이 모두 비어 있고 당일 이 아이 사진도 없을 때만 '참여 미확인' 반·일과표 모드.

    로봇 촬영이 있으면 원에 나온 것으로 보아 **참여 미확인** 문구를 쓰지 않는다.
    (하원 「데이터가 없습니다」앵커 정리는 `use_dismissal_no_data_anchor_cleanup` 참고.)
    """
    db_in, db_out = _attendance_check_in_out(attendance)
    return not db_in and not db_out and not infer_presence_from_photos


def use_dismissal_no_data_anchor_cleanup(
    attendance: dict[str, str | None] | None,
) -> bool:
    """DB 개인 등·하원 시각이 모두 비어 있을 때 — 하원 구간 「데이터가 없습니다」앵커 후처리만 적용.

    사진이 있어도 등·하원 **시각**이 없으면 True(중복 데이터 줄 정리·대표 시각 한 줄).
    """
    db_in, db_out = _attendance_check_in_out(attendance)
    return not db_in and not db_out


def use_timeline_start_no_data_anchor(
    attendance: dict[str, str | None] | None,
    *,
    infer_presence_from_photos: bool,
) -> bool:
    """등원을 DB·당일 사진으로 확인할 수 없을 때 — 일과표 첫 시각에 「데이터가 없습니다」."""
    return not _narrative_has_check_in(
        attendance, infer_presence_from_photos=infer_presence_from_photos
    )


def use_timeline_end_no_data_anchor(
    attendance: dict[str, str | None] | None,
) -> bool:
    """하원 시각이 DB 에 없을 때 — 일과표 마지막 종료 시각에 「데이터가 없습니다」."""
    return not _attendance_check_in_out(attendance)[1]


def timeline_no_data_anchor_allowed_times(
    schedule: dict[str, str] | None,
    attendance: dict[str, str | None] | None,
    *,
    infer_presence_from_photos: bool,
) -> set[str]:
    """「데이터가 없습니다」가 허용되는 time(HH:MM 정규화) 집합."""
    allowed: set[str] = set()
    top_t, bot_t = _class_scope_no_data_anchor_times(schedule)
    if use_timeline_start_no_data_anchor(
        attendance, infer_presence_from_photos=infer_presence_from_photos
    ) and top_t:
        allowed.add(_canonical_hhmm(top_t))
    if use_timeline_end_no_data_anchor(attendance) and bot_t:
        allowed.add(_canonical_hhmm(bot_t))
    return allowed


_CLASS_SCOPE_CANNOT_JUDGE_ATTENDANCE_PHRASE = "DB 만으로는 판단할 수 없"

# class_scope 타임라인 첫 줄·등원 미기록 안내 — UI 에서 한 줄로 읽히게 유지
CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT = "데이터가 없습니다"


def _text_is_no_individual_data_line(text: str) -> bool:
    """모델이 마침표·잡공백·ZWSP 를 붙여도 「데이터가 없습니다」로 본다."""
    t = _ZWSP_RE.sub("", (text or "").strip())
    t = re.sub(r"[\s\.。]+$", "", t)
    return t == CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT


def collapse_legacy_class_scope_disclaimer(text: str) -> str:
    """저장돼 있던 긴 DB 안내 문단을 짧은 문구로 치환(조회·재폴리시 시)."""
    t = (text or "").strip()
    if not t:
        return t
    if (
        _CLASS_SCOPE_CANNOT_JUDGE_ATTENDANCE_PHRASE in t
        and "실제 참여와 같다고 볼 수 없다" in t
    ):
        return CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT
    if "개별 하원·참여는 DB에 없어 확인할 수 없다" in t and (
        "실제 하원·참여와 같다고 볼 수 없다" in t
    ):
        return CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT
    if "개별 하원은 DB에 없다" in t and "실제 하원·참여와 같다고 볼 수 없다" in t:
        return CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT
    return t


def _timeline_disclaimer_no_db_attendance(
    call: str,
    class_name: str,
    time_s: str,
    schedule: dict[str, str] | None,
) -> str:
    """개인 등·하원 등 데이터가 없을 때 — 긴 시스템 문구 대신 한 줄."""
    del call, class_name, time_s, schedule  # 시그니처 유지(호출부 호환)
    return CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT


def ensure_class_scope_attendance_disclaimer(
    events: list[dict[str, Any]],
    schedule: dict[str, str] | None,
    address_name: str,
    class_name: str,
    *,
    attendance: dict[str, str | None] | None,
    infer_presence_from_photos: bool,
) -> list[dict[str, Any]]:
    """등원 근거가 없을 때 일과표 첫 시각 줄을 「데이터가 없습니다」로 맞춘다(누락 시 삽입·기존 긴 안내는 덮어씀)."""
    if not use_timeline_start_no_data_anchor(
        attendance, infer_presence_from_photos=infer_presence_from_photos
    ):
        return [dict(e) for e in events]
    call = (address_name or "").strip()
    if not call:
        return [dict(e) for e in events]
    slots = _schedule_slots_sorted(schedule or {})
    if not slots:
        return [dict(e) for e in events]
    first_t = slots[0][0]
    disc = _timeline_disclaimer_no_db_attendance(call, class_name, first_t, schedule)
    out = [dict(e) for e in events]
    out.sort(key=lambda e: str(e.get("time", "")))
    for i, row in enumerate(out):
        if str(row.get("time", "")).strip() == first_t:
            if _text_is_no_individual_data_line(str(row.get("text", ""))):
                return out
            out[i] = {**row, "text": disc}
            return out
    out.append({"time": first_t, "photo_id": None, "text": disc})
    out.sort(key=lambda e: str(e.get("time", "")))
    return out


def _timeline_text_no_check_out_record_class(
    call: str, class_name: str, time_s: str, schedule: dict[str, str] | None
) -> str:
    del call, class_name, time_s, schedule
    return CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT


def _child_arrival_opening_line(
    subj: str, time_s: str, schedule: dict[str, str] | None
) -> str:
    """일과표 첫 구간 등 — 호칭 주체의 등원·시작 한 줄."""
    hint = slot_label_for_schedule_time(schedule, time_s) if schedule else ""
    if hint and "등원" in hint:
        return f"{subj} 등원해 「{hint}」를 시작했다."
    if hint:
        return f"{subj} 등원했다. 일과표「{hint}」에 맞춰 하루를 열었다."
    return f"{subj} 등원하며 오늘 하루를 시작했다."


def _timeline_text_no_check_in_record(
    subj: str, time_s: str, schedule: dict[str, str] | None
) -> str:
    hint = slot_label_for_schedule_time(schedule, time_s) if schedule else ""
    if hint:
        return (
            f"{subj} 오늘 등원 기록이 없어 개별 출석은 단정할 수 없다. "
            f"같은 시간대 반 일과는 「{hint}」에 맞춰 진행되었다."
        )
    return (
        f"{subj} 오늘 등원 기록이 없어 개별 출석은 단정할 수 없다. "
        "반은 이 시간대 일정에 맞춰 움직였다."
    )


def _timeline_text_no_check_out_record(
    subj: str, time_s: str, schedule: dict[str, str] | None
) -> str:
    hint = slot_label_for_schedule_time(schedule, time_s) if schedule else ""
    if hint:
        return (
            f"{subj} 하원 기록이 아직 없어도 일과표 흐름상 이 시간대는 「{hint}」에 해당한다. "
            "짐을 정리하며 마음을 가다듬고 하루를 마무리하는 분위기였다."
        )
    return f"{subj} 짐을 정리하고 조용히 자리를 정돈하며 하루를 접어 가는 시간이었다."


def _text_claims_recorded_arrival_for_child(call: str, text: str) -> bool:
    if "등원하지" in text or "등원 기록이 없" in text:
        return False
    if call not in text:
        return False
    markers = (
        "등원해",
        "등원했다",
        "등원했습니다",
        "등원합니다",
        "등원하며",
        "등원하여",
        "등원한 뒤",
    )
    return any(m in text for m in markers)


def _text_claims_recorded_dismissal_for_child(call: str, text: str) -> bool:
    if "하원하지" in text or "하원 기록이 아직 없" in text:
        return False
    if call not in text:
        return False
    markers = (
        "하원해",
        "하원했다",
        "하원했습니다",
        "하원합니다",
        "하원하며",
        "하원하여",
        "하원한 뒤",
    )
    return any(m in text for m in markers)


def _group_text_falsely_claims_dismissal(text: str) -> bool:
    """반 전체 주어로 하원을 단정하는 줄(호칭 없음) — DB 하원 없을 때 교정 대상."""
    if "하원하지" in text or "하원 기록이 아직 없" in text:
        return False
    if "아이들" not in text and "친구들" not in text and "원생" not in text:
        return False
    markers = (
        "하원해",
        "하원했다",
        "하원했습니다",
        "하원합니다",
        "하원하며",
        "하원하여",
    )
    return any(m in text for m in markers)


def merge_attendance_timeline_events(
    events: list[dict[str, Any]],
    address_name: str,
    attendance: dict[str, str | None] | None,
    schedule: dict[str, str] | None,
) -> list[dict[str, Any]]:
    """DB 등하원 시각을 타임라인에 반영. 비사진 동일 시각 줄에 호칭·등하원이 없으면 문장 접두."""
    call = (address_name or "").strip()
    if not call:
        return events
    att = attendance or {}
    cin = att.get("check_in_kst")
    cout = att.get("check_out_kst")
    out: list[dict[str, Any]] = [dict(e) for e in events]
    subj = subject_particle_phrase(call)

    def prefix_line(verb: str, clock: str) -> str:
        hint = slot_label_for_schedule_time(schedule, clock)
        if hint:
            return f"{subj} {verb}했습니다. 일과표「{hint}」."
        return f"{subj} {verb}했습니다."

    by_time: dict[str, list[int]] = {}
    for i, e in enumerate(out):
        t = str(e.get("time", "")).strip()
        if t:
            by_time.setdefault(t, []).append(i)

    for clock_raw, verb in ((cin, "등원"), (cout, "하원")):
        if not clock_raw or not isinstance(clock_raw, str):
            continue
        clock = clock_raw.strip()
        if not clock:
            continue
        prefix = prefix_line(verb, clock)
        idxs = by_time.get(clock)
        if not idxs:
            out.append({"time": clock, "photo_id": None, "text": prefix})
            by_time.setdefault(clock, []).append(len(out) - 1)
            continue
        if any(out[j].get("photo_id") is not None for j in idxs):
            out.append({"time": clock, "photo_id": None, "text": prefix})
            continue
        i0 = idxs[0]
        tex = str(out[i0].get("text", "")).strip()
        if call in tex and verb in tex:
            continue
        if call not in tex or verb not in tex:
            out[i0]["text"] = f"{prefix} {tex}".strip()

    out.sort(key=lambda e: str(e.get("time", "")))
    return out


def _canonical_photo_times(photo_events: list[dict[str, Any]]) -> dict[int, str]:
    """photo_id → 실제 촬영 시각(HH:MM) — LLM 이 다른 슬롯에 붙인 photo_id 를 떼어낼 때 사용."""
    m: dict[int, str] = {}
    for p in photo_events:
        try:
            pid = int(p["photo_id"])
        except (KeyError, TypeError, ValueError):
            continue
        t = str(p.get("time", "")).strip()
        if t:
            m[pid] = t
    return m


def sanitize_photo_event_placements(
    events: list[dict[str, Any]],
    photo_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """각 photo_id 는 실제 촬영 시각 행에만 유지. 잘못된 시각·중복 행은 photo_id 제거."""
    canonical = _canonical_photo_times(photo_events)
    if not canonical:
        return [dict(e) for e in events]
    out: list[dict[str, Any]] = []
    seen_at_canonical: set[int] = set()
    for e in events:
        row = dict(e)
        pid = row.get("photo_id")
        if not isinstance(pid, int) or pid not in canonical:
            out.append(row)
            continue
        want_t = canonical[pid]
        cur_t = str(row.get("time", "")).strip()
        if cur_t != want_t:
            row["photo_id"] = None
            out.append(row)
            continue
        if pid in seen_at_canonical:
            row["photo_id"] = None
            out.append(row)
            continue
        seen_at_canonical.add(pid)
        out.append(row)
    return out


def ensure_canonical_photo_rows(
    events: list[dict[str, Any]],
    photo_events: list[dict[str, Any]],
    address_name: str,
) -> list[dict[str, Any]]:
    """LLM 이 사진 줄을 빠뜨렸으면 실제 촬영 시각에 한 줄 삽입."""
    call = (address_name or "").strip()
    poss = f"{call}의" if call else "아이의"
    out = [dict(e) for e in events]
    pairs = {(str(e.get("time", "")).strip(), e.get("photo_id")) for e in out}
    for p in photo_events:
        try:
            pid = int(p["photo_id"])
        except (KeyError, TypeError, ValueError):
            continue
        t = str(p.get("time", "")).strip()
        if not t or (t, pid) in pairs:
            continue
        mode = str(p.get("mode", "")).strip()
        mk = _mode_display_korean(mode)
        tail = f" ({mk})" if mk and mk != "놀이" else ""
        text = f"{poss} 표정이 기록되었다{tail}."
        out.append({"time": t, "photo_id": pid, "text": text})
        pairs.add((t, pid))
    out.sort(key=lambda e: str(e.get("time", "")))
    return out


def _norm_session_token(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


_ROBOT_KO_DISPLAY = {
    "eduping": "에듀핑",
    "gogoping": "고고핑",
    "noriarm": "노리암",
}


def robot_display_korean(robot: str) -> str:
    """robot id ("noriarm" 등) 를 한국어 호칭 ("노리암") 으로 — LLM 이 영문 id 를 음역 (예: "노리아르마") 하지 않게."""
    key = (robot or "").strip().lower()
    return _ROBOT_KO_DISPLAY.get(key, robot or "")


def _mode_display_korean(mode: str) -> str:
    m = _norm_session_token(mode)
    if m in ("oxquiz", "ox-quiz"):
        return "OX 퀴즈"
    if m == "mugunghwa":
        return "무궁화꽃이 피었습니다"
    if m == "dance":
        return "율동"
    if m == "attendance":
        return "등하원 인사"
    if m in ("checkup", "check-up"):
        return "진찰 놀이"
    if m == "blocks":
        return "블럭 쌓기"
    if m == "shop":
        return "가게 놀이"
    if m in ("hideseek", "hide-seek"):
        return "숨바꼭질"
    if m == "lullaby":
        return "자장가"
    if m == "greeting":
        return "인사"
    if not m or m == "unknown":
        return "놀이"
    raw = (mode or "").strip().replace("_", "-")
    return raw if raw else "놀이"


def _text_suggests_mode_activity(text: str, mode: str) -> bool:
    """타임라인 본문이 해당 로봇 활동(모드)을 말하는지 — 중복 서술 줄 제거용."""
    raw = (text or "").strip()
    if not raw:
        return False
    tnorm = _norm_session_token(raw)
    m = _norm_session_token(mode)
    if "oxquiz" in m or m == "ox" or m.startswith("ox"):
        if "oxquiz" in tnorm:
            return True
        low = raw.lower()
        if "ox-quiz" in low or "ox_quiz" in low:
            return True
        if "ox 퀴즈" in raw or "OX 퀴즈" in raw:
            return True
        if "oxquiz" in low:
            return True
        return False
    return len(m) >= 3 and m in tnorm


def _cluster_photo_events_by_session(
    photo_events: list[dict[str, Any]],
    *,
    gap_minutes: int = 75,
) -> list[list[dict[str, Any]]]:
    """같은 로봇·모드 촬영을 시간 순으로 이을 때, 촬영 간격이 gap_minutes 이내면 한 세션으로 묶는다."""
    rows: list[dict[str, Any]] = []
    for p in photo_events:
        try:
            pid = int(p["photo_id"])
        except (KeyError, TypeError, ValueError):
            continue
        t = str(p.get("time", "")).strip()
        if not t:
            continue
        try:
            _hhmm_to_minutes(t)
        except ValueError:
            continue
        rows.append({**p, "photo_id": pid, "time": t})
    if not rows:
        return []
    rows.sort(key=lambda p: _hhmm_to_minutes(p["time"]))
    clusters: list[list[dict[str, Any]]] = [[rows[0]]]
    for p in rows[1:]:
        prev = clusters[-1][-1]
        key_p = (_norm_session_token(str(p.get("robot", ""))), _norm_session_token(str(p.get("mode", ""))))
        key_prev = (_norm_session_token(str(prev.get("robot", ""))), _norm_session_token(str(prev.get("mode", ""))))
        if key_p != key_prev:
            clusters.append([p])
            continue
        dt = _hhmm_to_minutes(p["time"]) - _hhmm_to_minutes(prev["time"])
        if 0 <= dt <= gap_minutes:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    return clusters


# LLM 이 사용자 메시지의 "emotion (강도 …)" 입력 형식을 그대로 베껴 쓴 쓸모없는 한 줄.
_RAW_EMOTION_GARBLE_LINE_RE = re.compile(
    r"^\s*[a-z][a-z0-9_-]{0,24}\s*\(\s*강도\s*[\d.]+\)\s*(?:의\s*)?표정을\s*지었(?:습니다|다)\s*\.?\s*$",
    re.IGNORECASE,
)

_LL_INLINE_EMOTION_GRADE_RE = re.compile(
    r"(?:,\s*)?\s*\b[a-z][a-z0-9_-]{0,24}\s*\(\s*강도\s*[\d.]+\)"
    r"(?:\s*의\s*표정을\s*(?:지었(?:습니다|다|으며)|지으며))?",
    re.IGNORECASE,
)
_REPORT_EMOTION_ONLY_PARENS_RE = re.compile(
    r"\s*\(\s*(?:basic|hello|happy|fun|interest|bored|sad|angry|sleep)"
    r"(?:\s*,\s*[a-z0-9_-]+)*\s*\)",
    re.IGNORECASE,
)


def scrub_llm_emotion_score_and_paren_tags(text: str) -> str:
    """요약·타임라인에 섞인 `happy (강도 1.00)`·`(happy)` 등 LLM 메타 잔재 제거."""
    if not text:
        return text
    t = _LL_INLINE_EMOTION_GRADE_RE.sub("", text)
    t = _REPORT_EMOTION_ONLY_PARENS_RE.sub("", t)
    # 감정 덩어리만 지워져 「…하였고의 표정을 지으며」처럼 붙은 잔재
    for _pat, _rep in (
        (r"였고의\s*표정을\s*(?:지었(?:습니다|다|으며)|지으며)", "였고"),
        (r"했고의\s*표정을\s*(?:지었(?:습니다|다|으며)|지으며)", "했고"),
        (r"았고의\s*표정을\s*(?:지었(?:습니다|다|으며)|지으며)", "았고"),
        (r"었고의\s*표정을\s*(?:지었(?:습니다|다|으며)|지으며)", "었고"),
    ):
        t = re.sub(_pat, _rep, t, flags=re.UNICODE)
    t = re.sub(r",\s*\.", ".", t)
    t = re.sub(r"\s+\.", ".", t)
    t = re.sub(r"\s{2,}", " ", t)
    return t.strip()


def remove_timeline_raw_emotion_dump_lines(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """영문 감정 id + `(강도 …)` 형태만 담긴 타임라인 줄 제거(보호자용 문장이 아님)."""
    if not events:
        return []
    out: list[dict[str, Any]] = []
    for e in events:
        row = dict(e)
        text = str(row.get("text", "") or "").strip()
        if _RAW_EMOTION_GARBLE_LINE_RE.match(text):
            continue
        out.append(row)
    return out


def dedupe_timeline_near_duplicate_texts(
    events: list[dict[str, Any]],
    *,
    max_gap_minutes: int = 45,
) -> list[dict[str, Any]]:
    """같은 문장이 짧은 간격으로 반복되면(예: 10:42 사진 줄 + 10:47 동일 문장) 뒤쪽을 제거."""
    if not events:
        return []
    sorted_ev = sorted((dict(e) for e in events), key=lambda e: str(e.get("time", "")))
    out: list[dict[str, Any]] = []
    for e in sorted_ev:
        text = str(e.get("text", "")).strip()
        if not out:
            out.append(e)
            continue
        prev = out[-1]
        ptext = str(prev.get("text", "")).strip()
        if text and text == ptext:
            try:
                gap = _hhmm_to_minutes(str(e["time"])) - _hhmm_to_minutes(str(prev["time"]))
            except (KeyError, ValueError):
                gap = 9999
            if 0 <= gap <= max_gap_minutes:
                e_photo = isinstance(e.get("photo_id"), int)
                p_photo = isinstance(prev.get("photo_id"), int)
                if e_photo and not p_photo:
                    out[-1] = e
                continue
        out.append(e)
    return out


def merge_same_session_photo_clusters_to_single_rows(
    events: list[dict[str, Any]],
    photo_events: list[dict[str, Any]],
    address_name: str,
    *,
    session_gap_minutes: int = 75,
) -> list[dict[str, Any]]:
    """같은 로봇·모드로 잡힌 촬영 세션을 타임라인 **한 줄**로 합친다.

    - 복수 장: 시작·끝 시각과 약 N분, 대표 photo_id(감정 점수 최고) 한 줄.
    - 한 장: 기존 「표정이 기록」 한 줄(해당 시각).
    LLM 이 슬롯마다 ox-quiz 를 반복해 넣은 비사진 줄은 세션 구간 안에서 제거한다.
    """
    call = (address_name or "").strip()
    if not call or not photo_events:
        return [dict(e) for e in events]
    clusters = _cluster_photo_events_by_session(photo_events, gap_minutes=session_gap_minutes)
    if not clusters:
        return [dict(e) for e in events]
    topic = topic_particle_phrase(call)
    poss = f"{call}의"
    cluster_pids: set[int] = set()
    merged_rows: list[dict[str, Any]] = []
    for cluster in clusters:
        # cluster 는 시각 오름차순 — pids_ordered 도 그 순서를 그대로 보존 (UI 가 시간순 strip 으로 렌더).
        pids_ordered: list[int] = []
        seen: set[int] = set()
        for p in cluster:
            try:
                pid = int(p["photo_id"])
            except (KeyError, TypeError, ValueError):
                continue
            if pid in seen:
                continue
            seen.add(pid)
            pids_ordered.append(pid)
        cluster_pids |= seen
        first_t = str(cluster[0]["time"]).strip()
        last_t = str(cluster[-1]["time"]).strip()
        best = max(
            cluster,
            key=lambda p: float(str(p.get("score", "0"))),
        )
        try:
            best_pid = int(best["photo_id"])
        except (KeyError, TypeError, ValueError):
            continue
        mode_ko = _mode_display_korean(str(best.get("mode", "")))
        if len(cluster) == 1:
            mode_s = str(best.get("mode", "")).strip()
            mk = _mode_display_korean(mode_s)
            tail = f" ({mk})" if mk and mk != "놀이" else ""
            text = f"{poss} 표정이 기록되었다{tail}."
            cap_t = str(best.get("time", first_t)).strip()
            merged_rows.append({
                "time": cap_t,
                "photo_id": best_pid,
                "photo_ids": pids_ordered,
                "text": text,
            })
        else:
            try:
                first_m = _hhmm_to_minutes(first_t)
                last_m = _hhmm_to_minutes(last_t)
            except ValueError:
                continue
            dur = max(1, last_m - first_m)
            text = (
                f"{topic} {first_t}부터 {last_t}까지 약 {dur}분 동안 {mode_ko}를 "
                "즐겁게 이어가며 활동을 마치며 행복한 표정으로 마무리했다."
            )
            merged_rows.append({
                "time": first_t,
                "photo_id": best_pid,
                "photo_ids": pids_ordered,
                "text": text,
            })

    def keep_event(ev: dict[str, Any]) -> bool:
        pid = ev.get("photo_id")
        if isinstance(pid, int) and pid in cluster_pids:
            return False
        tx = str(ev.get("text", ""))
        # 사진 세션 시각 밖(점심·낮잠 슬롯 등)에도 LLM 이 같은 모드를 반복하는 경우가 있어,
        # 해당 모드를 본문에서 짚는 줄은 세션별 한 줄(merged_rows)만 남긴다.
        for cluster in clusters:
            mode_ref = str(cluster[0].get("mode", ""))
            if _text_suggests_mode_activity(tx, mode_ref):
                return False
        return True

    out = [dict(e) for e in events if keep_event(e)]
    out.extend(merged_rows)
    out.sort(key=lambda e: str(e.get("time", "")))
    return out


def rewrite_photo_event_texts_with_emotion(
    events: list[dict[str, Any]],
    photo_events: list[dict[str, Any]],
    address_name: str,
) -> list[dict[str, Any]]:
    """photo_id 가 있는 이벤트의 text 를 게임·감정 데이터로 결정론적으로 다시 쓴다.

    LLM 이 사진 시각이 일과표 (낮잠 등) 안에 들어가면 사진과 무관한 슬롯 텍스트
    ("자리를 정리하고 충분한 낮잠으로 오전의 피로를 풀었다") 를 생성하는 사례 방지.
    이름 fuzzy-fix 등 모든 후처리가 끝난 뒤 마지막에 호출 — 따라서 결과가 그대로 출력된다.

    입력:
      events: skeleton 단계에서 만들어진 타임라인 row 목록. photo_id / photo_ids 가 들어 있다.
      photo_events: 같은 자녀·날짜의 사진 메타. {photo_id, time, robot, mode, emotion, score}.
      address_name: 호칭 (조사 처리용).
    """
    call = (address_name or "").strip()
    if not call or not events:
        return [dict(e) for e in events]

    pe_by_id: dict[int, dict[str, Any]] = {}
    for p in photo_events or []:
        try:
            pid = int(p.get("photo_id"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        pe_by_id[pid] = p
    if not pe_by_id:
        return [dict(e) for e in events]

    topic = topic_particle_phrase(call)

    out: list[dict[str, Any]] = []
    for ev in events:
        new_ev = dict(ev)
        pid = new_ev.get("photo_id")
        pids_raw = new_ev.get("photo_ids") or []
        ids: list[int] = []
        for x in pids_raw:
            try:
                ids.append(int(x))
            except (TypeError, ValueError):
                continue
        if not ids and isinstance(pid, int):
            ids = [pid]
        cluster = [pe_by_id[i] for i in ids if i in pe_by_id]
        if not cluster:
            out.append(new_ev)
            continue

        # 모드: 가장 흔한 mode 채택 (한 클러스터는 보통 단일 모드지만 안전망).
        mode_counts: dict[str, int] = {}
        for p in cluster:
            m = str(p.get("mode", "")).strip().lower()
            if m:
                mode_counts[m] = mode_counts.get(m, 0) + 1
        main_mode = max(mode_counts, key=mode_counts.get) if mode_counts else ""  # type: ignore[arg-type]
        mode_ko = _mode_display_korean(main_mode)

        emotions = [str(p.get("emotion", "")).strip().lower() for p in cluster]
        n_happy = sum(1 for e in emotions if e == "happy")
        n_sad = sum(1 for e in emotions if e == "sad")
        n_total = len(cluster)

        first_t = str(cluster[0].get("time", "")).strip()
        last_t = str(cluster[-1].get("time", "")).strip()
        same_time = first_t == last_t

        activity_phrase = f"{mode_ko} 시간" if mode_ko != "놀이" else "활동 시간"

        if n_total == 1:
            emo = emotions[0]
            if emo == "happy":
                text = f"{topic} {activity_phrase}에 환하게 웃는 모습이 카메라에 한 장 담겼다."
            elif emo == "sad":
                text = f"{topic} {activity_phrase}에 잠시 시무룩한 표정이 카메라에 한 장 담겼다."
            else:
                text = f"{topic} {activity_phrase}의 표정이 카메라에 한 장 담겼다."
        else:
            span = (
                f"{first_t}"
                if same_time
                else f"{first_t}부터 {last_t}까지"
            )
            if n_sad == 0 and n_happy > 0:
                text = (
                    f"{topic} {span} {activity_phrase}에 푹 빠져, "
                    f"환하게 웃는 표정이 {n_happy}번이나 카메라에 담겼다."
                )
            elif n_happy == 0 and n_sad > 0:
                text = (
                    f"{topic} {span} {activity_phrase}에 참여하는 동안, "
                    f"시무룩한 표정이 {n_sad}번 카메라에 담겼다."
                )
            elif n_happy > 0 and n_sad > 0:
                text = (
                    f"{topic} {span} {activity_phrase}을 즐기며, "
                    f"환하게 웃는 모습이 {n_happy}번, 잠시 시무룩한 표정도 {n_sad}번 담겼다."
                )
            else:
                text = (
                    f"{topic} {span} {activity_phrase}의 표정이 {n_total}장 기록되었다."
                )

        new_ev["text"] = text
        out.append(new_ev)
    return out


def rewrite_photo_event_texts_in_json(
    content_json: str,
    photo_events: list[dict[str, Any]],
    address_name: str,
) -> str:
    """JSON 문자열 (events + summary) 안의 photo_id 가 있는 row 의 text 를 다시 쓴다.

    `polish_report_json_content` 가 이름 fuzzy-fix 로 `정리` → `정우` 같은 변형을
    일으키기도 해서, polish 가 끝난 *뒤* 결정론적 텍스트를 박아 넣는 마지막 단계.
    JSON 이 아니거나 events 가 list 가 아니면 원본 반환.
    """
    s = (content_json or "").strip()
    if not s:
        return s
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        return s
    if not isinstance(data, dict):
        return s
    events = data.get("events")
    if not isinstance(events, list):
        return s
    ev_dicts = [ev for ev in events if isinstance(ev, dict)]
    rewritten = rewrite_photo_event_texts_with_emotion(ev_dicts, photo_events, address_name)
    data["events"] = rewritten
    return json.dumps(data, ensure_ascii=False)


def _schedule_slots_sorted(schedule: dict[str, str]) -> list[tuple[str, int, int, str]]:
    """슬롯 키 HH:MM-HH:MM → (시작 HH:MM, 시작 분, 끝 분, 활동명), 시작 시각 순."""
    rows: list[tuple[str, int, int, str]] = []
    for key, label in (schedule or {}).items():
        parts = str(key).split("-", 1)
        if len(parts) != 2:
            continue
        a, b = parts[0].strip(), parts[1].strip()
        try:
            ta = _hhmm_to_minutes(a)
            tb = _hhmm_to_minutes(b)
        except ValueError:
            continue
        if ta > tb:
            continue
        rows.append((a, ta, tb, (label or "").strip()))
    rows.sort(key=lambda x: x[1])
    return rows


def _event_time_minutes(ev: dict[str, Any]) -> int | None:
    try:
        return _hhmm_to_minutes(str(ev.get("time", "")).strip())
    except (ValueError, TypeError, KeyError):
        return None


def _filler_text_for_class_schedule(
    call: str,
    class_name: str,
    label: str,
    menus: list[str],
    attendance: dict[str, str | None] | None,
    *,
    force_narrative_dismissal: bool = False,
) -> str:
    """등·하원 DB·사진이 모두 없을 때 — 보고 대상 호칭으로 시작하되 활동은 일과표·반 흐름으로만 서술."""
    c = (call or "").strip()
    topic = topic_particle_phrase(c) if c else "이 아이는"
    cls = (class_name or "").strip()
    cls_tag = f"「{cls}」반" if cls else "반"
    _, has_out = _attendance_check_in_out(attendance)
    lb = label.strip()

    def lead(body: str) -> str:
        return (
            f"{topic} 일과표 「{lb}」에 해당하는 시간으로, {cls_tag}에서는 {body}"
        )

    if "점심" in lb and menus:
        menu_bit = ", ".join(menus[:4])
        return lead(f"점심으로 {menu_bit} 등을 곁들여 식사하며 담소를 나누는 흐름이 있었다.")
    if "점심" in lb:
        return lead("점심으로 자리에 앉아 반찬을 골고루 먹으며 식사를 마치는 흐름이 있었다.")
    if "하원" in lb or "통합 보육" in lb:
        if has_out or force_narrative_dismissal:
            return (
                f"{topic} 일과표 「{lb}」에 해당하는 시간으로, {cls_tag}에서는 "
                "짐을 챙기고 하원 준비를 하며 통합 보육 친구들과 놀거리를 정리하는 흐름이 있었다."
            )
        return CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT
    if "등원" in lb and "하원" not in lb:
        return lead(
            "등원·자유놀이에 맞춰 자리에 들어와 인사를 나누고 장난감과 책으로 몸을 푸는 흐름이 있었다."
        )
    if "오전 간식" in lb or (("오전" in lb or "아침" in lb) and "간식" in lb):
        return lead("간식을 나눠 받아 조금씩 먹으며 쉬는 흐름이 있었다.")
    if "오후 간식" in lb or ("오후" in lb and "간식" in lb):
        return lead("간식을 가볍게 나눠 먹고 잠깐 쉬는 흐름이 있었다.")
    if "낮잠" in lb:
        return lead("이불을 덮고 누우거나 조용히 책을 넘기며 쉬는 흐름이 있었다.")
    if "휴식" in lb:
        return lead("퍼즐이나 그림책을 보며 긴장을 푸는 흐름이 있었다.")
    if "특별" in lb:
        return lead("모둠 활동·발표처럼 집중이 필요한 놀이가 이어지는 흐름이 있었다.")
    if "교실" in lb or "바깥" in lb or "자유" in lb or "놀이" in lb:
        return lead("교실과 바깥을 오가며 블록·역할·뛰기 놀이를 섞어 가며 뛰어노는 흐름이 있었다.")
    if "간식" in lb:
        return lead("간식을 조금씩 나눠 먹으며 담소를 나누는 흐름이 있었다.")
    return lead("선생님과 차례를 지키며 몸을 움직이는 활동이 이어지는 흐름이 있었다.")


def _filler_text_for_schedule_label(
    subj: str,
    label: str,
    menus: list[str],
    attendance: dict[str, str | None] | None = None,
    *,
    infer_presence_from_photos: bool = False,
    class_scope: bool = False,
    class_name: str = "",
    call_for_class_scope: str = "",
    force_narrative_dismissal: bool = False,
) -> str:
    """일과표 활동명에 맞춰 서술형 한 줄(활동을 했다 식의 껍데기 문장 지양)."""
    if class_scope:
        return _filler_text_for_class_schedule(
            (call_for_class_scope or "").strip(),
            class_name,
            label,
            menus,
            attendance,
            force_narrative_dismissal=force_narrative_dismissal,
        )
    has_in_narrative = _narrative_has_check_in(
        attendance, infer_presence_from_photos=infer_presence_from_photos
    )
    _, has_out = _attendance_check_in_out(attendance)
    lb = label.strip()
    if "점심" in lb and menus:
        menu_bit = ", ".join(menus[:4])
        return f"{subj} 점심 시간에 {menu_bit} 등을 곁들여 배불리 먹으며 이야기도 나눴다."
    if "점심" in lb:
        return f"{subj} 점심 시간에 자리에 앉아 반찬을 골고루 먹고 천천히 씹으며 식사를 마쳤다."
    if "하원" in lb or "통합 보육" in lb:
        if has_out:
            return f"{subj} 짐을 챙기고 하원 준비를 하며 남은 시간에는 통합 보육 친구들과 조용히 놀거리를 정리했다."
        quoted = lb if lb else "하원 및 통합 보육"
        return (
            f"{subj} 하원 기록이 아직 없어도 일과표 흐름상 이 시간대는 「{quoted}」에 해당한다. "
            "짐을 정리하며 마음을 가다듬고 하루를 마무리하는 분위기였다."
        )
    if "등원" in lb and "하원" not in lb:
        if has_in_narrative:
            return f"{subj} 등원한 뒤 반 친구들과 인사를 나누고 장난감과 책을 가지고 자유롭게 하루를 열었다."
        return f"{subj} 이 시간대에는 반 친구들과 인사를 나누고 장난감과 책을 가지고 자유롭게 몸을 풀었다."
    if "오전 간식" in lb or (("오전" in lb or "아침" in lb) and "간식" in lb):
        return f"{subj} 오전 간식 시간에 간식을 나눠 받아 조금씩 먹으며 쉬었다."
    if "오후 간식" in lb or ("오후" in lb and "간식" in lb):
        return f"{subj} 오후 간식 시간에 간식을 가볍게 나눠 먹고 잠깐 쉬었다."
    if "낮잠" in lb:
        return f"{subj} 이불을 덮고 누워 낮잠을 자거나 조용히 책을 넘기며 몸을 쉬게 했다."
    if "휴식" in lb:
        return f"{subj} 조용히 쉬는 시간에 퍼즐이나 그림책을 보며 긴장을 풀었다."
    if "특별" in lb:
        return f"{subj} 오후 특별 시간에는 모둠 활동과 발표처럼 집중이 필요한 놀이에 참여했다."
    if "교실" in lb or "바깥" in lb or "자유" in lb or "놀이" in lb:
        return f"{subj} 교실과 바깥을 오가며 블록·역할·뛰기 놀이를 섞어 가며 친구들과 땀을 냈다."
    if "간식" in lb:
        return f"{subj} 간식 시간에 반 친구들과 간식을 조금씩 나눠 먹으며 담소를 나눴다."
    # 일반 슬롯 — 활동명은 녹이되 「…」활동을 했다 패턴은 피함
    return f"{subj} 이 시간대에는 「{lb}」에 맞춰 선생님과 친구들과 함께 몸을 움직이고 차례를 지키며 즐겁게 시간을 보냈다."


def fill_timeline_schedule_gaps(
    events: list[dict[str, Any]],
    schedule: dict[str, str] | None,
    address_name: str,
    menu_items: list[str] | None = None,
    attendance: dict[str, str | None] | None = None,
    *,
    infer_presence_from_photos: bool = False,
    class_scope: bool = False,
    class_name: str = "",
) -> list[dict[str, Any]]:
    """LLM 이 생략한 일과표 구간마다 photo_id=null 한 줄을 넣어 등원~하원 흐름이 비지 않게 한다."""
    slots = _schedule_slots_sorted(schedule or {})
    if not slots:
        return [dict(e) for e in events]
    call = (address_name or "").strip()
    subj = subject_particle_phrase(call) if call else "아이가"
    out: list[dict[str, Any]] = [dict(e) for e in events]
    covered_mins = [m for m in (_event_time_minutes(e) for e in out) if m is not None]

    def slot_has_event(ta: int, tb: int) -> bool:
        return any(ta <= m <= tb for m in covered_mins)

    menus = [str(x).strip() for x in (menu_items or []) if str(x).strip()]

    for start_hhmm, ta, tb, label in slots:
        if not label or slot_has_event(ta, tb):
            continue
        text = _filler_text_for_schedule_label(
            subj,
            label,
            menus,
            attendance,
            infer_presence_from_photos=infer_presence_from_photos,
            class_scope=class_scope,
            class_name=class_name,
            call_for_class_scope=call,
        )
        if len(text) > 100:
            text = text[:97].rstrip() + "…"
        out.append({"time": start_hhmm, "photo_id": None, "text": text})
        covered_mins.append(_hhmm_to_minutes(start_hhmm))

    out.sort(key=lambda e: str(e.get("time", "")))
    return out


_TRAILING_MENU_PAREN_RE = re.compile(r"\s*\(([^)]{2,400})\)\s*$")


def _paren_tokens_match_lunch(inner: str, menu_items: list[str]) -> bool:
    """괄호 안 품목 나열이 DB 점심 메뉴와 같은 집합이면 참 (간식 줄에 점심 메뉴가 붙은 경우 제거)."""
    items = [str(x).strip() for x in menu_items if str(x).strip()]
    if not items:
        return False
    inner_parts = [p.strip() for p in re.split(r"[,，]", inner) if p.strip()]
    if not inner_parts:
        return False
    set_menu = {re.sub(r"\s+", "", x) for x in items}
    set_paren = {re.sub(r"\s+", "", x) for x in inner_parts}
    if set_menu == set_paren:
        return True
    if len(items) >= 2 and set_menu.issubset(set_paren) and len(set_paren) <= len(set_menu) + 1:
        return True
    return False


def strip_lunch_menu_from_non_lunch_events(
    events: list[dict[str, Any]],
    schedule: dict[str, str] | None,
    menu_items: list[str] | None,
) -> list[dict[str, Any]]:
    """점심 DB 메뉴 괄호는 일과표 점심 슬롯에만 둔다. LLM 이 간식 등에 동일 메뉴를 붙이면 제거."""
    menus = [str(x).strip() for x in (menu_items or []) if str(x).strip()]
    if not menus:
        return [dict(e) for e in events]
    out: list[dict[str, Any]] = []
    for e in events:
        row = dict(e)
        text = str(row.get("text", "") or "")
        time_s = str(row.get("time", "")).strip()
        label = slot_label_for_schedule_time(schedule, time_s) if schedule else ""
        if "점심" in label or not text:
            out.append(row)
            continue
        m = _TRAILING_MENU_PAREN_RE.search(text)
        if not m or not _paren_tokens_match_lunch(m.group(1), menus):
            out.append(row)
            continue
        if not label and "점심" in text:
            out.append(row)
            continue
        if not label and not any(
            k in text for k in ("간식", "오전 간식", "오후 간식", "아침 간식")
        ):
            out.append(row)
            continue
        row["text"] = text[: m.start()].rstrip()
        out.append(row)
    return out


def _note_tail_nominal_phrase(frag: str) -> str:
    """메모 절편을 '… 모습' 앞에 붙이기 좋은 체언구로 만든다(현재형 서술어 어미 -다 → -던)."""
    w = (frag or "").strip()
    if len(w) >= 2 and w.endswith("다") and not w.endswith("이다"):
        return w[:-1] + "던"
    return w


def _summary_tail_from_child_notes_line(topic: str, cls_prefix: str, line: str) -> str:
    """교사 메모 한 줄을 요약 꼬리문장으로 풀어 쓴다(「…」원문 인용·나열·메타 비유 지양)."""
    s = re.sub(r"\s+", " ", (line or "").strip())
    for ch in ("「", "」", '"', "'", "“", "”"):
        s = s.replace(ch, "")
    parts = re.split(r"\s*(?:그러나|하지만|그런데)\s*", s, maxsplit=1)
    if len(parts) == 2:
        a, b = parts[0].strip().rstrip("."), parts[1].strip().rstrip(".")
        if len(a) > 42:
            a = a[:39].rstrip() + "…"
        if len(b) > 42:
            b = b[:39].rstrip() + "…"
        na, nb = _note_tail_nominal_phrase(a), _note_tail_nominal_phrase(b)
        return (
            f"{topic} {cls_prefix}한편 {na} 모습이 있었고, "
            f"또 다른 순간에는 {nb} 모습도 함께 보였습니다."
        )
    if "," in s:
        a, b = [x.strip().rstrip(".") for x in s.split(",", 1)]
        if len(a) > 5 and len(b) > 5:
            if len(a) > 48:
                a = a[:45].rstrip() + "…"
            if len(b) > 48:
                b = b[:45].rstrip() + "…"
            na, nb = _note_tail_nominal_phrase(a), _note_tail_nominal_phrase(b)
            return (
                f"{topic} {cls_prefix}한편 {na} 모습이 있었고, "
                f"또 다른 순간에는 {nb} 모습도 함께 보였습니다."
            )
    frag = s[:88].rstrip()
    if len(s) > 88:
        frag += "…"
    return f"{topic} {cls_prefix}이날 함께 엿보인 모습으로는 {frag}"


def rewrite_class_collective_subject_to_child(
    text: str,
    call: str,
    cls: str,
    *,
    class_scope: bool,
) -> str:
    """「반명 아이들은/이 …」「반명에서는 아이들이 …」처럼 집단을 앞세운 표현을 보고 대상 호칭 중심으로 고친다.

    문장 **맨앞**뿐 아니라 쉼표 뒤·문장 중간(공백 뒤)에 붙은 같은 패턴도 정리한다.
    목적격 「… 햇님반 아이들과 놀았다」의 「아이들과」는 건드리지 않는다.
    """
    t = re.sub(r"\s+", " ", (text or "").strip())
    c = (call or "").strip()
    cl = (cls or "").strip()
    if not t or not c or not cl:
        return t
    esc = re.escape(cl)
    topic = topic_particle_phrase(c)
    subj = subject_particle_phrase(c)

    # 「햇님반에서는 아이들이/은」(문장 어디서나)
    t = re.sub(rf"{esc}에서는\s*아이들(?:이|은)\s*", f"「{cl}」 반에서 ", t)

    # 줄 맨앞: 「햇님반」 아이들이 … (반 이름이 따옴표로만 감싸인 LLM 출력)
    m_guil = re.match(rf"^「{esc}」\s*아이들(?:은|이|을|를)\s*(.+)$", t)
    if m_guil:
        rest = m_guil.group(1).strip()
        if class_scope:
            return f"{topic} 참여 미확인. 「{cl}」 일과로 {rest}"
        return f"{topic} 「{cl}」 일과로 {rest}"

    # 쉼표 뒤 절: ", 햇님반 아이들은 …"
    if class_scope:
        t = re.sub(rf"(,|，)\s*{esc}\s*아이들(?:은|이)\s*", rf"\1 「{cl}」 반 일과로는 ", t)
    else:
        t = re.sub(rf"(,|，)\s*{esc}\s*아이들(?:은|이)\s*", rf"\1 {topic} ", t)

    # 문장 중간(공백 뒤): "… 햇님반 아이들은 …" (단, '아이들과' 제외는 패턴에서 은/이만)
    if class_scope:
        t = re.sub(rf"\s+{esc}\s*아이들(?:은|이)\s+", f" 「{cl}」 반 일과로는 ", t)
    else:
        t = re.sub(rf"\s+{esc}\s*아이들(?:은|이)\s+", f" {topic} ", t)

    # 줄/문장 맨앞
    m = re.match(rf"^{esc}\s*아이들과\s*(.+)$", t)
    if m:
        rest = m.group(1).strip()
        if class_scope:
            return f"{topic} 참여 미확인. 「{cl}」 친구들과 {rest}"
        return f"{subj} 「{cl}」 친구들과 {rest}"

    m = re.match(rf"^{esc}\s*아이들(은|이|을|를)\s*(.+)$", t)
    if m:
        josa = m.group(1)
        rest = m.group(2).strip()
        if class_scope:
            return f"{topic} 참여 미확인. 「{cl}」 일과로 {rest}"
        if josa == "은":
            return f"{topic} {rest}"
        return f"{subj} {rest}"

    return fix_class_name_as_timeline_subject(c, cl, t, class_scope=class_scope)


def _dismissal_canonical_start_hhmm(schedule: dict[str, str] | None) -> str | None:
    """하원·통합 보육이 붙은 슬롯이 여러 개면 **가장 늦게 시작하는** 슬롯의 시작 시각(한 줄만 '데이터'용)."""
    cand: list[tuple[str, int]] = []
    for start_hhmm, ta, _tb, label in _schedule_slots_sorted(schedule or {}):
        lb = (label or "").strip()
        if "하원" in lb or "통합 보육" in lb:
            cand.append((start_hhmm, ta))
    if not cand:
        return None
    return max(cand, key=lambda x: x[1])[0]


def _class_scope_no_data_anchor_times(
    schedule: dict[str, str] | None,
) -> tuple[str | None, str | None]:
    """(첫 일과 시각, 마지막 일과 **종료** 시각) — 타임라인 맨 앞·맨 끝 「데이터가 없습니다」 앵커."""
    slots = _schedule_slots_sorted(schedule or {})
    if not slots:
        return None, None
    _start_key, _ta, tb_last, _lab = slots[-1]
    return slots[0][0], _minutes_to_hhmm(tb_last)


def _slot_label_at_time_sorted(schedule: dict[str, str] | None, hhmm: str) -> str:
    """일과표 슬롯 중 시각이 포함되는 활동명 — `slot_label_for_schedule_time` 과 같이 **경계는 뒤쪽 슬롯**."""
    try:
        hh = _canonical_hhmm(hhmm.strip())
        tm = _hhmm_to_minutes(hh)
    except ValueError:
        return ""
    hit = ""
    for _s, ta, tb, lab in _schedule_slots_sorted(schedule or {}):
        if ta <= tm <= tb:
            hit = (lab or "").strip()
    return hit


def normalize_class_scope_dismissal_slots_to_no_data(
    events: list[dict[str, Any]],
    schedule: dict[str, str] | None,
    *,
    apply_end_slot_no_data: bool,
) -> list[dict[str, Any]]:
    """하원 DB 가 비어 있을 때, 일과표 **마지막 종료 시각** 줄만 「데이터가 없습니다」로 통일."""
    if not apply_end_slot_no_data:
        return [dict(e) for e in events]
    _top, bot = _class_scope_no_data_anchor_times(schedule)
    if not bot:
        return [dict(e) for e in events]
    bot_n = _canonical_hhmm(bot)
    out: list[dict[str, Any]] = []
    for e in events:
        row = dict(e)
        if row.get("photo_id") is not None:
            out.append(row)
            continue
        time_n = _canonical_hhmm(str(row.get("time", "")))
        if time_n == bot_n:
            row["text"] = CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT
        out.append(row)
    return out


def repair_extraneous_class_scope_no_data_rows(
    events: list[dict[str, Any]],
    schedule: dict[str, str] | None,
    address_name: str,
    class_name: str,
    menu_items: list[str] | None,
    attendance: dict[str, str | None] | None,
    *,
    infer_presence_from_photos: bool,
    narrative_class_scope: bool,
) -> list[dict[str, Any]]:
    """「데이터가 없습니다」는 허용된 앵커 시각(맨 앞·맨 끝)에만 두고 나머지는 채움."""
    allowed = timeline_no_data_anchor_allowed_times(
        schedule,
        attendance,
        infer_presence_from_photos=infer_presence_from_photos,
    )
    if not allowed:
        return [dict(e) for e in events]
    call = (address_name or "").strip()
    if not call:
        return [dict(e) for e in events]
    subj = subject_particle_phrase(call)
    menus = [str(x).strip() for x in (menu_items or []) if str(x).strip()]
    out: list[dict[str, Any]] = []
    for e in events:
        row = dict(e)
        text = str(row.get("text", "")).strip()
        time_s = str(row.get("time", "")).strip()
        time_n = _canonical_hhmm(time_s)
        if not _text_is_no_individual_data_line(text) or time_n in allowed:
            out.append(row)
            continue
        label = _slot_label_at_time_sorted(schedule, time_n) or slot_label_for_schedule_time(
            schedule, time_n
        )
        if not label:
            row["text"] = f"{topic_particle_phrase(call)} 이 시각은 일과표 구간과 맞지 않아 활동을 구체적으로 적지 못했습니다."
            out.append(row)
            continue
        filler = _filler_text_for_schedule_label(
            subj,
            label,
            menus,
            attendance,
            infer_presence_from_photos=infer_presence_from_photos,
            class_scope=narrative_class_scope,
            class_name=class_name,
            call_for_class_scope=call,
            force_narrative_dismissal=True,
        )
        row["text"] = filler
        out.append(row)
    return out


def collapse_redundant_class_scope_participation_prefixes(
    events: list[dict[str, Any]],
    address_name: str,
    class_name: str,
    *,
    class_scope: bool,
) -> list[dict[str, Any]]:
    """class_scope 일 때 「참여 미확인」·「반」 아이들 주어는 **첫 줄 이후** 반복하지 않게 정리."""
    if not class_scope:
        return [dict(e) for e in events]
    c = (address_name or "").strip()
    cl = (class_name or "").strip()
    if not c or not cl:
        return [dict(e) for e in events]
    topic = topic_particle_phrase(c)
    esc_top = re.escape(topic)
    esc_cl = re.escape(cl)
    seen = False
    out: list[dict[str, Any]] = []
    for e in events:
        row = dict(e)
        t = re.sub(r"\s+", " ", str(row.get("text", "")).strip())
        if t:
            if "참여 미확인" in t:
                if seen:
                    t = re.sub(rf"^(?:{esc_top}\s*)?참여 미확인입니다?[.\s]*", "", t).strip()
                else:
                    seen = True
            if re.match(rf"^(?:{esc_top}\s*)?「{esc_cl}」\s*아이들(?:이|은|을|를)\b", t):
                t = re.sub(
                    rf"^(?:{esc_top}\s*)?「{esc_cl}」\s*아이들(?:이|은|을|를)\s+",
                    f"{topic}「{cl}」 일과로 ",
                    t,
                    count=1,
                )
                t = re.sub(r"\s+", " ", t).strip()
        row["text"] = t
        out.append(row)
    return out


def soften_dismissal_no_data_when_intraday_narrative_in_slot(
    events: list[dict[str, Any]],
    schedule: dict[str, str] | None,
    attendance: dict[str, str | None] | None,
    address_name: str,
    class_name: str,
    menu_items: list[str] | None,
    *,
    infer_presence_from_photos: bool,
    narrative_class_scope: bool,
) -> list[dict[str, Any]]:
    """하원 대표 시각이 「데이터가 없습니다」인데 같은 슬롯 안 뒤에 구체 서술이 있으면 앞 줄을 일과 채움으로 바꾼다."""
    if not schedule:
        return [dict(e) for e in events]
    if _attendance_check_in_out(attendance)[1]:
        return [dict(e) for e in events]
    canon_raw = _dismissal_canonical_start_hhmm(schedule)
    if not canon_raw:
        return [dict(e) for e in events]
    canon_n = _canonical_hhmm(canon_raw)
    canon_m = _hhmm_to_minutes(canon_n)
    _, end_anchor_raw = _class_scope_no_data_anchor_times(schedule)
    end_anchor_n = _canonical_hhmm(end_anchor_raw) if end_anchor_raw else ""
    tb_end: int | None = None
    canon_label = ""
    for start_hhmm, ta, tb, lab in _schedule_slots_sorted(schedule):
        if _canonical_hhmm(start_hhmm) == canon_n:
            tb_end = tb
            canon_label = (lab or "").strip()
            break
    if tb_end is None:
        return [dict(e) for e in events]
    later_story = False
    for e in events:
        tm = _event_time_minutes(e)
        if tm is None:
            continue
        if canon_m < tm <= tb_end:
            tx = str(e.get("text", "")).strip()
            if (
                tx
                and not _text_is_no_individual_data_line(tx)
                and len(tx) >= 16
            ):
                later_story = True
                break
    if not later_story:
        return [dict(e) for e in events]
    call = (address_name or "").strip()
    if not call or not canon_label:
        return [dict(e) for e in events]
    subj = subject_particle_phrase(call)
    menus = [str(x).strip() for x in (menu_items or []) if str(x).strip()]
    filler = _filler_text_for_schedule_label(
        subj,
        canon_label,
        menus,
        attendance,
        infer_presence_from_photos=infer_presence_from_photos,
        class_scope=narrative_class_scope,
        class_name=class_name,
        call_for_class_scope=call,
        force_narrative_dismissal=True,
    )
    if len(filler) > 100:
        filler = filler[:97].rstrip() + "…"
    out: list[dict[str, Any]] = []
    for e in events:
        row = dict(e)
        if row.get("photo_id") is not None:
            out.append(row)
            continue
        if _canonical_hhmm(str(row.get("time", ""))) == canon_n and _text_is_no_individual_data_line(
            str(row.get("text", ""))
        ):
            if end_anchor_n and canon_n == end_anchor_n:
                out.append(row)
                continue
            row["text"] = filler
        out.append(row)
    return out


def _last_schedule_slot_meta(
    schedule: dict[str, str] | None,
) -> tuple[str, int, int, str] | None:
    """마지막 슬롯: (원본 키, 시작 분, 끝 분, 활동명)."""
    slots = _schedule_slots_sorted(schedule or {})
    if not slots:
        return None
    start_hhmm, ta, tb, lab = slots[-1]
    slot_key: str | None = None
    for key in schedule or {}:
        parts = str(key).split("-", 1)
        if len(parts) != 2:
            continue
        try:
            kta = _hhmm_to_minutes(parts[0].strip())
            ktb = _hhmm_to_minutes(parts[1].strip())
        except ValueError:
            continue
        if kta == ta and ktb == tb:
            slot_key = str(key).strip()
            break
    if not slot_key:
        slot_key = f"{_canonical_hhmm(start_hhmm)}-{_minutes_to_hhmm(tb)}"
    return slot_key, ta, tb, (lab or "").strip()


def _timeline_event_sort_minutes(time_s: str) -> int | None:
    raw = _ZWSP_RE.sub("", (time_s or "").strip())
    if not raw:
        return None
    if raw.count("-") == 1 and ":" in raw.split("-", 1)[0]:
        a, _, _ = raw.partition("-")
        a = a.strip()
        try:
            return _hhmm_to_minutes(a)
        except ValueError:
            return None
    try:
        return _hhmm_to_minutes(raw)
    except ValueError:
        return None


def _pick_merged_slot_narrative_text(texts: list[str]) -> str:
    best = ""
    best_score = (-1, -1)
    for raw in texts:
        t = re.sub(r"\s+", " ", (raw or "").strip())
        if not t:
            continue
        nodata = _text_is_no_individual_data_line(t)
        score = (0 if nodata else 1, len(t))
        if score > best_score or (score == best_score and len(t) > len(best)):
            best = t
            best_score = score
    return best or CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT


def merge_final_schedule_slot_timeline_rows(
    events: list[dict[str, Any]],
    schedule: dict[str, str] | None,
) -> list[dict[str, Any]]:
    """마지막 일과표 구간 안의 비사진 줄(맨 끝 앵커 시각 제외)을 구간 키(`16:00-18:00`) 한 줄로 합친다."""
    meta = _last_schedule_slot_meta(schedule)
    if not meta:
        return [dict(e) for e in events]
    slot_key, ta, tb_end, _lab = meta
    merge_idx: list[int] = []
    texts: list[str] = []
    for i, e in enumerate(events):
        if e.get("photo_id") is not None:
            continue
        ts = str(e.get("time", "")).strip()
        if not ts:
            continue
        if ts == slot_key:
            merge_idx.append(i)
            texts.append(str(e.get("text", "")))
            continue
        if ts.count("-") == 1 and ":" in ts:
            a, _, b = ts.partition("-")
            try:
                am = _hhmm_to_minutes(a.strip())
                bm = _hhmm_to_minutes(b.strip())
                if am == ta and bm == tb_end:
                    merge_idx.append(i)
                    texts.append(str(e.get("text", "")))
                    continue
            except ValueError:
                pass
        tm = _event_time_minutes(e)
        if tm is None:
            continue
        if ta <= tm < tb_end:
            merge_idx.append(i)
            texts.append(str(e.get("text", "")))
    if len(merge_idx) < 2:
        return [dict(e) for e in events]
    merged_text = _pick_merged_slot_narrative_text(texts)
    first_i = min(merge_idx)
    new_row: dict[str, Any] = {"time": slot_key, "photo_id": None, "text": merged_text}
    out: list[dict[str, Any]] = []
    for i, e in enumerate(events):
        if i in merge_idx:
            if i == first_i:
                out.append(new_row)
            continue
        out.append(dict(e))
    out.sort(
        key=lambda row: (
            _timeline_event_sort_minutes(str(row.get("time", ""))) or 99999,
            str(row.get("time", "")),
        )
    )
    return out


def ensure_class_scope_timeline_end_no_data_row(
    events: list[dict[str, Any]],
    schedule: dict[str, str] | None,
    attendance: dict[str, str | None] | None,
) -> list[dict[str, Any]]:
    """하원 기록이 없을 때 타임라인 **맨 끝**에 「데이터가 없습니다」 한 줄을 둔다(없으면 추가)."""
    if not use_timeline_end_no_data_anchor(attendance):
        return [dict(e) for e in events]
    _, bot = _class_scope_no_data_anchor_times(schedule)
    if not bot:
        return [dict(e) for e in events]
    bot_n = _canonical_hhmm(bot)
    out: list[dict[str, Any]] = [dict(e) for e in events]
    for row in out:
        if row.get("photo_id") is not None:
            continue
        if _canonical_hhmm(str(row.get("time", ""))) == bot_n:
            row["text"] = CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT
            return out
    out.append({"time": bot_n, "photo_id": None, "text": CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT})
    out.sort(
        key=lambda row: (
            _timeline_event_sort_minutes(str(row.get("time", ""))) or 99999,
            str(row.get("time", "")),
        )
    )
    return out


def rewrite_class_scope_timeline_child_topic(
    events: list[dict[str, Any]],
    address_name: str,
    class_name: str,
    *,
    class_scope: bool,
) -> list[dict[str, Any]]:
    """LLM·일괄 서술에서 「반명+아이들」 주어를 보고 대상 호칭 중심으로 고친다(class_scope 여부에 따라 단정·참여 문구만 달리함)."""
    call = (address_name or "").strip()
    cls = (class_name or "").strip()
    if not call or not cls:
        return [dict(e) for e in events]
    out: list[dict[str, Any]] = []
    for e in events:
        row = dict(e)
        text = str(row.get("text", "")).strip()
        if not text:
            out.append(row)
            continue
        row["text"] = rewrite_class_collective_subject_to_child(
            text, call, cls, class_scope=class_scope
        )
        out.append(row)
    return out


def fix_timeline_child_focus_events(
    events: list[dict[str, Any]],
    address_name: str,
    class_name: str,
    schedule: dict[str, str] | None,
    attendance: dict[str, str | None] | None = None,
    *,
    infer_presence_from_photos: bool = False,
    class_scope: bool = False,
) -> list[dict[str, Any]]:
    """반 전체·'반 이름' 오타 등으로 주인공이 흐려진 등원 줄을 보고서 호칭 중심으로 고친다."""
    call = (address_name or "").strip()
    if not call:
        return [dict(e) for e in events]
    subj = subject_particle_phrase(call)
    narrative_in = _narrative_has_check_in(
        attendance, infer_presence_from_photos=infer_presence_from_photos
    )
    _, db_out = _attendance_check_in_out(attendance)
    out: list[dict[str, Any]] = []
    for e in events:
        row = dict(e)
        text = str(row.get("text", "")).strip()
        text = re.sub(r"\s+", " ", text.replace("반 이름", "").strip())
        time_s = str(row.get("time", "")).strip()
        group_arrival = (
            "등원" in text
            and call not in text
            and ("아이들" in text or "친구들" in text or "원생" in text)
        )
        group_dismissal = (
            "하원" in text
            and call not in text
            and ("아이들" in text or "친구들" in text or "원생" in text)
        )
        if group_arrival:
            if not narrative_in:
                if class_scope:
                    row["text"] = _timeline_disclaimer_no_db_attendance(
                        call, class_name, time_s, schedule
                    )
                else:
                    row["text"] = _timeline_text_no_check_in_record(subj, time_s, schedule)
            else:
                row["text"] = _child_arrival_opening_line(subj, time_s, schedule)
        elif group_dismissal and not db_out:
            if class_scope:
                row["text"] = _timeline_text_no_check_out_record_class(
                    call, class_name, time_s, schedule
                )
            else:
                row["text"] = _timeline_text_no_check_out_record(subj, time_s, schedule)
        else:
            row["text"] = text
        out.append(row)
    return out


def scrub_unrecorded_arrival_departure_claims(
    events: list[dict[str, Any]],
    address_name: str,
    attendance: dict[str, str | None] | None,
    schedule: dict[str, str] | None,
    *,
    infer_presence_from_photos: bool = False,
    class_scope: bool = False,
    class_name: str = "",
) -> list[dict[str, Any]]:
    """DB 에 등원·하원이 없는데 본문이 사실처럼 단정하면 일과표 맞춤 중립 문장으로 바꾼다."""
    call = (address_name or "").strip()
    if not call:
        return [dict(e) for e in events]
    db_in, db_out = _attendance_check_in_out(attendance)
    narrative_in = _narrative_has_check_in(
        attendance, infer_presence_from_photos=infer_presence_from_photos
    )
    subj = subject_particle_phrase(call)
    out: list[dict[str, Any]] = []
    for e in events:
        row = dict(e)
        text = str(row.get("text", "")).strip()
        time_s = str(row.get("time", "")).strip()
        if infer_presence_from_photos and not db_in and "등원 기록이 없" in text:
            row["text"] = _child_arrival_opening_line(subj, time_s, schedule)
        elif not narrative_in and _text_claims_recorded_arrival_for_child(call, text):
            if class_scope:
                row["text"] = _timeline_disclaimer_no_db_attendance(
                    call, class_name, time_s, schedule
                )
            else:
                row["text"] = _timeline_text_no_check_in_record(subj, time_s, schedule)
        elif not db_out and _text_claims_recorded_dismissal_for_child(call, text):
            if class_scope:
                row["text"] = _timeline_text_no_check_out_record_class(
                    call, class_name, time_s, schedule
                )
            else:
                row["text"] = _timeline_text_no_check_out_record(subj, time_s, schedule)
        elif not db_out and _group_text_falsely_claims_dismissal(text) and call not in text:
            if class_scope:
                row["text"] = _timeline_text_no_check_out_record_class(
                    call, class_name, time_s, schedule
                )
            else:
                row["text"] = _timeline_text_no_check_out_record(subj, time_s, schedule)
        else:
            row["text"] = text
        out.append(row)
    return out


_NOTE_TOKEN_RE = re.compile(r"[\uac00-\ud7a3]{3,}")


def _notes_substantively_in_summary(notes: str, summary: str) -> bool:
    """교사 메모의 3글자 이상 한글 덩어리가 요약에 이미 들어갔는지."""
    s = re.sub(r"\s+", "", summary)
    first_line = (notes or "").replace("\r", "").split("\n")[0]
    for tok in _NOTE_TOKEN_RE.findall(first_line)[:14]:
        if len(tok) >= 3 and tok in s:
            return True
    return False


def augment_summary_with_child_notes(
    summary: str,
    child_notes: str | None,
    address_name: str,
    class_name: str,
    *,
    max_total_len: int = 220,
    short_summary_len: int = 72,
) -> str:
    """DB `child.notes`가 있는데 요약이 짧거나 메모와 동떨어지면, 꼬리 한 문장을 덧붙인다.

    원문을 「」로 붙이지 않고, 그러나/하지만 또는 쉼표로 나뉜 둘을 풀어 서술한다. 추가 LLM 호출 없음.
    """
    raw = (child_notes or "").strip()
    if not raw:
        return (summary or "").strip()
    s = (summary or "").strip()
    first_line = raw.replace("\r", "").split("\n")[0].strip()
    if not first_line:
        return s
    if _notes_substantively_in_summary(raw, s):
        return s
    if len(s) >= short_summary_len:
        return s
    call = (address_name or "").strip()
    if not call:
        return s
    topic = topic_particle_phrase(call)
    cls = (class_name or "").strip()
    cls_prefix = f"{cls}에서 " if cls else ""
    tail = _summary_tail_from_child_notes_line(topic, cls_prefix, first_line)
    merged = f"{s} {tail}".strip()
    if len(merged) > max_total_len:
        merged = merged[: max_total_len - 1] + "…"
    return merged


def retain_top_k_photo_timeline(
    events: list[dict[str, Any]],
    photo_events: list[dict[str, Any]],
    *,
    k: int = 1,
) -> list[dict[str, Any]]:
    """하루 표정 사진이 여러 장이어도 타임라인 썸네일은 상위 k 장만(기본 1장, 감정 점수 우선)."""
    if k < 1:
        return [dict(e) for e in events]
    score_by_pid: dict[int, float] = {}
    time_by_pid: dict[int, str] = {}
    for p in photo_events:
        try:
            pid = int(p["photo_id"])
        except (KeyError, TypeError, ValueError):
            continue
        try:
            score_by_pid[pid] = float(str(p.get("score", "0")))
        except ValueError:
            score_by_pid[pid] = 0.0
        time_by_pid[pid] = str(p.get("time", "")).strip()
    used = {int(e["photo_id"]) for e in events if isinstance(e.get("photo_id"), int)}
    if len(used) <= k:
        return [dict(e) for e in events]
    ordered = sorted(used, key=lambda pid: (-score_by_pid.get(pid, 0.0), time_by_pid.get(pid, "")))
    keep = set(ordered[:k])
    out: list[dict[str, Any]] = []
    for e in events:
        row = dict(e)
        pid = row.get("photo_id")
        if isinstance(pid, int) and pid not in keep:
            row["photo_id"] = None
        out.append(row)
    return out


_PHOTO_CAPTURE_ECHO_PATTERNS: tuple[re.Pattern[str], ...] = (
    # "…오늘 포착된 표정에서 가장 행복해 보였다/으며/…"
    re.compile(
        r",?\s*오늘\s*포착된\s*표정에서\s*가장\s*행복해\s*보였(?:다|으며|고|습니다|습니까)?\.?",
        re.UNICODE,
    ),
    # "…(감정은) 오늘 포착된 표정과 유사했…"
    re.compile(
        r",?\s*(?:[가-힣]{1,10}의\s*감정(?:은|이)\s*)?오늘\s*포착된\s*표정과\s*유사했(?:다|으며|고|습니다|습니까)?\.?",
        re.UNICODE,
    ),
    re.compile(
        r",?\s*오늘\s*포착된\s*표정와\s*유사했(?:다|으며|고|습니다|습니까)?\.?",
        re.UNICODE,
    ),
    re.compile(
        r",?\s*오늘\s*포착된\s*표정과도?\s*비슷했(?:다|으며|고|습니다|습니까)?\.?",
        re.UNICODE,
    ),
)


def strip_photo_capture_heading_echo(text: str) -> str:
    """프롬프트 섹션 제목을 본문에 반복하는 '오늘 포착된 표정…' 잔재를 제거한다."""
    if not text or "포착된 표정" not in text:
        return text
    t = text
    # 섹션 제목이 한 줄 앞에 그대로 붙은 경우(마크다운 **, 전각 ： 포함)
    t = re.sub(
        r"^[\s\u200b]*(?:\*{1,2}\s*)?오늘\s*포착된\s*표정(?:\s*\*{1,2})?\s*[：:]\s*",
        "",
        t,
        flags=re.UNICODE,
    )
    t = re.sub(
        r"(?<=[。.])\s*(?:\*{1,2}\s*)?오늘\s*포착된\s*표정(?:\s*\*{1,2})?\s*[：:]\s*",
        " ",
        t,
        flags=re.UNICODE,
    )
    t = re.sub(
        r"\s+(?:\*{1,2}\s*)?오늘\s*포착된\s*표정(?:\s*\*{1,2})?\s*[：:]\s*",
        " ",
        t,
        flags=re.UNICODE,
    )
    for pat in _PHOTO_CAPTURE_ECHO_PATTERNS:
        t = pat.sub("", t)
    if "오늘 포착된 표정" in t:
        t = re.sub(r",?\s*오늘\s*포착된\s*표정[^.\n]{1,80}(?:유사|비슷|행복해\s*보였)[^.\n]{0,30}", "", t, flags=re.UNICODE)
    t = re.sub(r"\s{2,}", " ", t).strip()
    t = re.sub(r"^\s*[,.]\s*", "", t)
    t = re.sub(r"\s+[,.]\s*$", "", t)
    return t.strip(" ,")


NO_PHOTO_TIMELINE_TEXT_FALLBACK = "반 일과에 맞춰 활동을 이어 갔습니다."


def scrub_expression_meta_without_photos(text: str) -> str:
    """로봇 표정 촬영(photo_events)이 없을 때 LLM 이 넣은 포착·얼굴·기록 표현 환각을 제거한다.

    사진이 있는 보고서에는 호출하지 않는다(「표정이 기록」 줄은 실제 촬영 행에만 쓰임).
    """
    if not text:
        return text
    t = strip_photo_capture_heading_echo(text)
    # 남은 「오늘 포착…」 꼬리(제목만 덧붙인 경우)
    t = re.sub(r"오늘\s*포착된\s*표정\s*[：:]?\s*", "", t, flags=re.UNICODE)
    t = re.sub(
        r",?\s*(?:행복한|즐거운|밝은|신나는)\s*표정을\s*지었(?:습니다|다)\.?",
        "",
        t,
        flags=re.UNICODE,
    )
    t = re.sub(
        r"[\uac00-\ud7a3]{1,12}의\s*표정이\s*기록되었(?:습니다|다)(?:\s*\([^)]*\))?\.?",
        "",
        t,
        flags=re.UNICODE,
    )
    t = re.sub(r"\s{2,}", " ", t).strip()
    t = re.sub(r"^[,.;]\s*", "", t).strip(" ,.;")
    return t


def normalize_report_subject_openers_to_topic(name: str, text: str) -> str:
    """문장(마침표 기준)마다 선두가 이름+이/가이면 이름+은/는로 통일한다.

    모델이 비슷한 일과 줄에서 이/가·은/는를 번갈아 쓰면 어색해지므로,
    보고서 한 줄·요약은 주제 조사(은/는) 톤으로 맞춘다. (es-hangul `josa` 결과와 동일 호칭·조사)
    """
    n = (name or "").strip()
    if not n or not text or n not in text:
        return text
    subj = subject_particle_phrase(n)
    topic = topic_particle_phrase(n)

    def patch_leading(seg: str) -> str:
        s = seg.strip()
        if not s.startswith(subj):
            return s
        tail = s[len(subj) :]
        if tail and not tail[0].isspace():
            return s
        rest = tail.lstrip()
        if rest.startswith("아니"):
            return s
        return f"{topic} {rest}" if rest else topic

    raw = text.strip()
    if "." not in raw:
        return patch_leading(raw)
    segs = re.split(r"(?<=\.)\s+", raw)
    out: list[str] = []
    for x in segs:
        x = x.strip()
        if not x:
            continue
        ends_dot = x.endswith(".")
        body = x[:-1].strip() if ends_dot else x
        p = patch_leading(body)
        out.append(p + ("." if ends_dot else ""))
    return " ".join(out)


_STALE_SUMMARY_MEMO_PHRASE_RE = re.compile(
    r"\s*메모에 적힌 바와 겹치는 점도 있었다\.\s*",
    re.UNICODE,
)


def scrub_stale_summary_memo_phrase(text: str) -> str:
    """구버전 요약 꼬리의 메타 표현 제거(재생성 없이 문장만 정리)."""
    if not text or "메모에 적힌" not in text:
        return text
    t = _STALE_SUMMARY_MEMO_PHRASE_RE.sub(" ", text)
    return re.sub(r" {2,}", " ", t).strip()


def fix_common_report_korean_typos(text: str) -> str:
    """요약·본문에서 자주 나오는 한국어 오타만 치환(이름 무관)."""
    if not text:
        return text
    t = text
    t = t.replace("노았습니다", "놀았습니다")
    t = t.replace("노았으며", "놀았으며")
    t = t.replace("노았고", "놀았고")
    # 호칭 근접 오타 교정이 「표정으로」→「표정우로」로 잘못 붙인 희귀 깨짐 복구
    t = t.replace("표정우로", "표정으로")
    # 일과 타임라인은 하루 돌아본 서술 — 식사 줄의 현재형 「먹습니다」를 과거형으로 통일
    t = re.sub(
        r"(점심|오전 간식|오후 간식|간식)을\s*먹습니다(?=\s|[(.]|$)",
        r"\1을 먹었습니다",
        t,
    )
    return t


def scrub_participation_disclaimer_attendance_verbs(text: str) -> str:
    """「참여 미확인」과 같은 줄에 등원·하원 완료 서술을 두지 않는다(논리 모순 제거)."""
    if not text or "참여 미확인" not in text:
        return text
    t = re.sub(r"\s+", " ", text.strip())
    if re.search(r"등원했(?:습니다)?", t):
        t = re.sub(
            r"일과로\s*등원했(?:습니다)?",
            "일과로 등원 시간대에 맞춰 반 친구들과 하루를 여는 흐름이 있었습니다",
            t,
        )
    if re.search(r"하원했(?:습니다)?", t):
        t = re.sub(
            r"일과로\s*하원했(?:습니다)?",
            "일과로 하원·통합 보육 시간에 맞춰 반에서 마무리를 준비하는 흐름이 있었습니다",
            t,
        )
    return t


def dedupe_adjacent_name_subject_markers(name: str, text: str) -> str:
    """「지수는 지수는」「민성이 민성이」처럼 호칭+조사가 공백으로 연달아 중복된 경우 한 번만 남긴다."""
    n = (name or "").strip()
    if not n or not text or n not in text:
        return text
    topic = topic_particle_phrase(n)
    subj = subject_particle_phrase(n)
    t = text
    if len(topic) >= 2:
        dup_t = re.compile(re.escape(topic) + r"[,，]?\s*" + re.escape(topic))
        while dup_t.search(t):
            t = dup_t.sub(topic, t)
    if len(subj) >= 2 and subj != topic:
        dup_s = re.compile(re.escape(subj) + r"[,，]?\s*" + re.escape(subj))
        while dup_s.search(t):
            t = dup_s.sub(subj, t)
    return t


def formalize_parent_facing_report_korean(text: str) -> str:
    """보호자용 존댓말 — 문장 단위로 평서 종결(…다/…했다)을 습니다·입니다 쪽으로 맞춘다.

    고정 문구 「데이터가 없습니다」·이미 「…습니다」「…입니다」로 끝난 문장은 유지한다.
    """

    def one_sentence(seg: str) -> str:
        s = seg.strip()
        if not s:
            return seg
        if s.rstrip(".。 ") == CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT:
            return s
        had_period = bool(re.search(r"[\.。]\s*$", s))
        core = s.rstrip(".。 \t")
        if not core:
            return seg
        paren_rest = ""
        m_paren = re.search(r"(\s*\([^)]*\))(\s*[\.。]?)?\s*$", core)
        if m_paren:
            paren_rest = m_paren.group(1) + (m_paren.group(2) or "")
            core = core[: m_paren.start()].rstrip()
        if not core:
            return seg
        if core.endswith(
            (
                "습니다",
                "입니다",
                "습니까",
                "입니까",
                "드립니다",
                "드리겠습니다",
                "있습니다",
                "없습니다",
            )
        ):
            return core + paren_rest + ("." if had_period else "")
        # 긴 어미 우선 (없었다 / 있었다 등)
        tail_pairs: tuple[tuple[str, str], ...] = (
            ("없었다", "없었습니다"),
            ("있었다", "있었습니다"),
            ("같았다", "같았습니다"),
            ("드러났다", "드러났습니다"),
            ("가졌다", "가졌습니다"),
            ("였다", "였습니다"),
            ("나눴다", "나누었습니다"),
            ("봤다", "보았습니다"),
            ("줬다", "주었습니다"),
            ("됐다", "되었습니다"),
            ("일어났다", "일어났습니다"),
            ("잤다", "잤습니다"),
            ("했다", "했습니다"),
            ("었다", "었습니다"),
            ("았다", "았습니다"),
            ("보냈다", "보냈습니다"),
            ("지냈다", "지냈습니다"),
            ("한다", "합니다"),
            ("된다", "됩니다"),
            ("인다", "입니다"),
            ("없다", "없습니다"),
            ("있다", "있습니다"),
            ("좋다", "좋습니다"),
            ("많다", "많습니다"),
            ("싶다", "싶습니다"),
            ("같다", "같습니다"),
            ("맞다", "맞습니다"),
        )
        out = core
        for plain, polite in tail_pairs:
            if out.endswith(plain):
                out = out[: -len(plain)] + polite
                break
        if out == core and re.search(r"참여 미확인$", out):
            out = re.sub(r"참여 미확인$", "참여 미확인입니다", out)
        return out + paren_rest + ("." if had_period else "")

    raw = (text or "").strip()
    if not raw:
        return raw
    if raw == CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT:
        return raw
    parts = re.split(r"(?<=[\.。])\s+", raw)
    if len(parts) == 1:
        return one_sentence(parts[0])
    return " ".join(one_sentence(p) for p in parts if p.strip())


def fix_garbled_meogeul_name_food_phrase(name: str, text: str) -> str:
    """「… 등 먹을 강택이 풍성」처럼 이름이 목적어 자리에 끼어든 요약 오류 → 자연스러운 표현."""
    n = (name or "").strip()
    if not n or not text:
        return text
    return re.sub(
        rf"먹을\s+{re.escape(n)}(이|가)\s+풍성",
        "먹거리가 풍성",
        text,
        flags=re.UNICODE,
    )


def polish_report_korean_josa(name: str, text: str) -> str:
    """보고서 한 줄용 조사 교정 체인 (시간명사 → 소유 → 반대 이/가·은/는 → 과/아이 → 주격 오타 …)."""
    if not text:
        return text
    t = fix_report_time_josa_artifacts(text)
    t = fix_common_report_korean_typos(t)
    t = scrub_llm_emotion_score_and_paren_tags(t)
    t = scrub_participation_disclaimer_attendance_verbs(t)
    t = strip_photo_capture_heading_echo(t)
    n = name.strip()
    if not n:
        t = scrub_stale_summary_memo_phrase(t)
        t = formalize_parent_facing_report_korean(t)
        return strip_cjk_ideographs_from_report_text(t)
    t = fix_expression_record_possessive_phrase(n, t)
    t = fix_address_name_hangul_near_miss(n, t)
    t = fix_garbled_first_syllable_name_particle(n, t)
    t = fix_possessive_name_glitch(n, t)
    t = fix_wrong_josa_particle_pair(n, t)
    t = fix_name_gwa_different_children_glitch(n, t)
    t = fix_subject_josa_glitch(n, t)
    t = fix_stacked_josa_glitch(n, t)
    t = fix_missing_subject_josa_after_name(n, t)
    t = normalize_report_subject_openers_to_topic(n, t)
    t = fix_garbled_meogeul_name_food_phrase(n, t)
    t = dedupe_adjacent_name_subject_markers(n, t)
    t = scrub_stale_summary_memo_phrase(t)
    t = formalize_parent_facing_report_korean(t)
    return strip_cjk_ideographs_from_report_text(t)


def polish_report_json_content(
    content: str,
    address_name: str,
    registered_full_name: str | None = None,
    *,
    class_name: str | None = None,
) -> str:
    """보고서 `content` 가 JSON(events+summary) 이면 각 문자열만 한국어 후처리.

    JSON 이 아니면(레거시 평문) 전체 문자열에만 동일 체인을 적용한다.
    """
    s = (content or "").strip()
    if not s:
        return s
    addr = address_name.strip()
    reg = (registered_full_name or "").strip()
    cls_nm = (class_name or "").strip()

    def _one_line(t: str) -> str:
        t = collapse_legacy_class_scope_disclaimer(t)
        if reg and reg != addr:
            t = scrub_registered_name_in_report_text(t, reg, addr)
        if cls_nm:
            t = fix_truncated_class_name_ideul(cls_nm, t)
            t = fix_class_name_as_timeline_subject(addr, cls_nm, t, class_scope=None)
        if addr:
            return polish_report_korean_josa(addr, t)
        t = scrub_llm_emotion_score_and_paren_tags(t)
        return strip_cjk_ideographs_from_report_text(fix_report_time_josa_artifacts(t))

    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        return _one_line(s)

    if not isinstance(data, dict):
        return _one_line(s)

    events = data.get("events")
    if isinstance(events, list):
        ev_list = [dict(ev) for ev in events if isinstance(ev, dict)]
        ev_list = remove_timeline_raw_emotion_dump_lines(ev_list)
        data["events"] = ev_list
        for ev in ev_list:
            if "text" in ev:
                ev["text"] = _one_line(str(ev.get("text", "")))

    summ = data.get("summary")
    if isinstance(summ, str):
        data["summary"] = _one_line(summ)
    elif summ is not None:
        data["summary"] = _one_line(str(summ))

    return json.dumps(data, ensure_ascii=False)


def fix_possessive_name_glitch(name: str, text: str) -> str:
    """이름 직후에 주격(이/가)이 소유격 앞에 잘못 붙은 경우 제거.

    한국어 소유는 보통 「이름+의」 한 번이면 충분한데, 모델이 「이름+이+의」·「이름+가+의」
    형태로 내보내는 경우가 있어, 주어진 `name` 앞말에 한해 정규식으로 정리한다.
    """
    n = name.strip()
    if not n or not text:
        return text
    return re.sub(re.escape(n) + r"(이의|가의)", n + "의", text)
