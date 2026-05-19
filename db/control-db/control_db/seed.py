"""DB seed — 교사·학부모·자녀 + 31일 메뉴 + 오늘자 등하원/보고서 (학부모 포털 데모용).

사용:
    python -m control_db.seed                  # 추가만 (idempotent)
"""
import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

from fastapi_users.password import PasswordHelper
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from control_db.models import Attendance, Child, Menu, ParentChild, Report, User
from control_db.session import async_session_maker

_KST = timezone(timedelta(hours=9))

SEED_PASSWORD = "1234"

MENU_SAMPLES: Sequence[list[str]] = [
    ["미역국", "쌀밥", "계란말이", "시금치나물", "바나나"],
    ["김치찌개", "잡곡밥", "제육볶음", "콩나물무침", "귤"],
    ["닭곰탕", "쌀밥", "깍두기", "브로콜리", "사과"],
    ["된장찌개", "잡곡밥", "고등어구이", "시금치나물", "키위"],
    ["소고기무국", "잡곡밥", "배추김치", "오이무침", "딸기"],
]

# (이름, 생년월일, 반, 특이사항)
CHILD_SAMPLES: Sequence[tuple[str, date, str, str | None]] = [
    ("박우림", date(2021, 2, 14),  "햇님반", "선생님 말을 잘 듣는 척을 잘한다. 다른 아이들의 관심을 끌기를 좋아한다."),
    ("최민성", date(2021, 4, 28),  "햇님반", "활동량이 다른 아이들에 비해 많다. 낮잠 시간에 잠을 안자고 돌아다니므로 주의."),
    ("이정우", date(2021, 6, 10),  "햇님반", "낯가림이 심하다. 그러나 게임 시간에는 말이 많아진다."),
    ("이지수", date(2021, 9, 22),  "햇님반", "엘리베이터를 좋아하는 경향이 있다. 교사의 말을 듣지 않을 때가 있다."),
    ("이강택", date(2021, 11, 3),  "햇님반", "축구를 좋아한다. 가끔 밖에서 매미나 지렁이를 잡아와서 곤란할 때가 있다."),
    ("노영주", date(2021, 3, 1),  "햇님반", "낮잠 시간에 한번 자면 못 일어난다. 잠꼬대로 부산 사투리를 한다."),
]

# (email, 이름, 매핑할 자녀 이름)
PARENT_SAMPLES: Sequence[tuple[str, str, str]] = [
    ("parent@test.com",  "박혁거세", "박우림"),
    ("parent2@test.com", "최치원", "최민성"),
    ("parent3@test.com", "이알평", "이정우"),
    ("parent3@test.com", "이알평", "이지수"),
    ("parent3@test.com", "이알평", "이강택"),
    ("parent4@test.com", "노수", "노영주"),
]


async def seed_teacher(session: AsyncSession, helper: PasswordHelper) -> None:
    existing = (
        await session.execute(select(User).where(User.email == "teacher@test.com"))
    ).scalar_one_or_none()
    if existing:
        existing.hashed_password = helper.hash(SEED_PASSWORD)
        await session.commit()
        print(f"[seed] teacher@test.com 비밀번호 = {SEED_PASSWORD} (갱신)")
        return

    user = User(
        email="teacher@test.com",
        hashed_password=helper.hash(SEED_PASSWORD),
        is_active=True,
        is_verified=True,
        is_superuser=False,
        role="teacher",
        name="노영주",
        phone=None,
    )
    session.add(user)
    await session.commit()
    print(f"[seed] teacher@test.com / {SEED_PASSWORD} 추가")


async def seed_children(session: AsyncSession) -> dict[str, int]:
    """이름 → child.id 매핑 반환 (학부모 매핑용)."""
    result: dict[str, int] = {}
    added = 0
    for name, birth, klass, notes in CHILD_SAMPLES:
        existing = (
            await session.execute(
                select(Child).where(
                    Child.name == name, Child.birth_date == birth, Child.class_name == klass
                )
            )
        ).scalar_one_or_none()
        if existing:
            existing.notes = notes
            result[name] = existing.id
            continue
        child = Child(name=name, birth_date=birth, class_name=klass, notes=notes)
        session.add(child)
        await session.flush()
        result[name] = child.id
        added += 1
    await session.commit()
    print(f"[seed] children {added}명 추가 (총 {len(CHILD_SAMPLES)}명 중)")
    return result


async def seed_parents(
    session: AsyncSession,
    helper: PasswordHelper,
    child_ids: dict[str, int],
) -> None:
    added = 0
    for email, name, child_name in PARENT_SAMPLES:
        existing = (
            await session.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if existing:
            existing.hashed_password = helper.hash(SEED_PASSWORD)
            continue
        cid = child_ids.get(child_name)
        if cid is None:
            print(f"[seed] WARN — child '{child_name}' 미존재, parent {email} skip")
            continue
        user = User(
            email=email,
            hashed_password=helper.hash(SEED_PASSWORD),
            is_active=True,
            is_verified=True,
            is_superuser=False,
            role="parent",
            name=name,
            phone="010-0000-0000",
        )
        session.add(user)
        await session.flush()
        session.add(ParentChild(parent_id=user.id, child_id=cid))
        added += 1
    await session.commit()
    print(f"[seed] parents {added}명 추가 (모든 비밀번호 = {SEED_PASSWORD})")


def menu_doc_text(day: int, items: list[str]) -> str:
    """RAG 인덱스용 문서 텍스트 — day 숫자를 포함시켜 day 매칭도 가능하게."""
    return f"{day}일 점심 메뉴: {', '.join(items)}"


_EMBEDDING_FIXTURE_PATH = (
    Path(__file__).resolve().parent / "seed_data" / "menu_embeddings.json"
)


def _load_embedding_fixture() -> dict[int, list[float]]:
    """seed_data/menu_embeddings.json 의 미리 계산된 1024d 벡터 — Ollama 의존성 제거용."""
    if not _EMBEDDING_FIXTURE_PATH.exists():
        return {}
    with _EMBEDDING_FIXTURE_PATH.open(encoding="utf-8") as f:
        raw = json.load(f)
    return {int(k): v for k, v in raw.items()}


async def seed_menu(session: AsyncSession) -> None:
    """31일치 메뉴를 채우고 embedding 도 같이 박아준다.

    embedding 은 seed_data/menu_embeddings.json (미리 계산된 fixture) 우선.
    fixture 에 없는 day 는 Ollama (bge-m3) 로 계산. fixture 가 없으면 전체 Ollama.
    """
    fixture = _load_embedding_fixture()

    existing = (await session.execute(select(Menu))).scalars().all()
    have = {m.day for m in existing}
    added = 0
    for day in range(1, 32):
        if day in have:
            continue
        items = MENU_SAMPLES[(day - 1) % len(MENU_SAMPLES)]
        session.add(
            Menu(
                day=day,
                items=items,
                embedding=fixture.get(day),
            )
        )
        added += 1
    await session.commit()
    print(f"[seed] menu {added}일 추가 (이미 있는 {len(have)}일은 skip)")

    # embedding 이 비어 있는 row 들 — fixture 없는 day 또는 기존 NULL row
    missing = (
        (await session.execute(select(Menu).where(Menu.embedding.is_(None))))
        .scalars()
        .all()
    )
    if not missing:
        print("[seed] menu embedding 모두 채워짐 — Ollama 호출 skip")
        return

    print(f"[seed] menu embedding {len(missing)}건 누락 — Ollama bge-m3 로 계산")
    from ai_service.embed import embed_text

    for row in missing:
        row.embedding = await embed_text(menu_doc_text(row.day, row.items))
    await session.commit()
    print(f"[seed] menu embedding {len(missing)}건 생성 완료")


# 학부모 포털 Attendance / Report 탭이 비어 보이지 않도록, 자녀별로 오늘자
# 등(09:05 KST) / 하원(16:10 KST) + 평문 보고서를 채워준다. UNIQUE 제약
# (attendance: child_id+date+type, report: child_id+date) 으로 재실행 시 skip.
# 보고서는 평문 — parent Report.vue 는 split('\n'), teacher Reports.vue 는 JSON
# 파싱 실패 시 summary 에 그대로 떨어뜨려 양쪽 모두 정상 렌더된다.
_REPORT_SUMMARY_BY_NAME: dict[str, str] = {
    "박우림": "오늘은 친구들 앞에서 율동을 멋지게 발표했어요. 새로운 노래도 빠르게 따라 불렀습니다.",
    "최민성": "활동 시간 동안 에너지가 넘쳤어요. 낮잠 시간에는 옆 친구의 도움으로 잘 누워 있었습니다.",
    "이정우": "오전에는 조용히 책을 읽다가, OX 퀴즈 시간에 가장 큰 목소리로 답을 외쳤어요.",
    "이지수": "엘리베이터 놀이를 친구들과 함께 즐겼고, 정리 정돈도 잘 도와주었습니다.",
    "이강택": "바깥놀이 시간에 축구를 가장 즐겼고, 친구들에게 패스도 잘 해주었어요.",
    "노영주": "낮잠 후 컨디션이 좋았고, 점심 시간에 새로운 반찬도 잘 먹었습니다.",
}


async def seed_attendance(session: AsyncSession, child_ids: dict[str, int]) -> None:
    today = datetime.now(_KST).date()
    check_in_time = datetime.combine(today, datetime.min.time(), _KST).replace(hour=9, minute=5)
    check_out_time = datetime.combine(today, datetime.min.time(), _KST).replace(hour=16, minute=10)

    added = 0
    for name, cid in child_ids.items():
        for att_type, time_val in (("IN", check_in_time), ("OUT", check_out_time)):
            existing = (
                await session.execute(
                    select(Attendance).where(
                        Attendance.child_id == cid,
                        Attendance.date == today,
                        Attendance.type == att_type,
                    )
                )
            ).scalar_one_or_none()
            if existing:
                continue
            session.add(Attendance(child_id=cid, date=today, type=att_type, time=time_val))
            added += 1
    await session.commit()
    print(f"[seed] attendance {added}건 추가 (오늘 {today.isoformat()} 기준 IN/OUT)")


def _seed_report_content(name: str) -> str:
    """JSON {events, summary} — 교사 보고서 포맷과 동일. 백엔드 polish 가 평문은
    한 줄로 합쳐버려 학부모 타임라인이 1개 항목으로 보이는 문제 회피용."""
    summary = _REPORT_SUMMARY_BY_NAME.get(name, "오늘 하루도 즐겁게 보냈습니다.")
    events = [
        {"time": "09:05", "photo_id": None, "text": "등원 후 친구들과 인사를 나눴어요."},
        {"time": "10:30", "photo_id": None, "text": "자유 놀이 시간에 블럭을 쌓으며 놀았어요."},
        {"time": "12:00", "photo_id": None, "text": "점심 식사 시간 — 골고루 잘 먹었어요."},
        {"time": "13:00", "photo_id": None, "text": "낮잠 시간 동안 차분히 휴식했어요."},
        {"time": "15:00", "photo_id": None, "text": "OX 퀴즈 활동에 활발히 참여했어요."},
        {"time": "16:10", "photo_id": None, "text": "하원 인사를 마쳤어요."},
    ]
    return json.dumps({"events": events, "summary": summary}, ensure_ascii=False)


async def seed_reports(session: AsyncSession, child_ids: dict[str, int]) -> None:
    """오늘자 보고서 upsert. 기존 행이 JSON 이 아니면(이전 평문 seed) 덮어쓴다 —
    교사·학부모가 직접 편집한 JSON 본문은 건드리지 않는다."""
    today = datetime.now(_KST).date()
    now_utc = datetime.now(timezone.utc)

    added = 0
    upgraded = 0
    for name, cid in child_ids.items():
        existing = (
            await session.execute(
                select(Report).where(Report.child_id == cid, Report.date == today)
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.content.strip().startswith("{"):
                continue
            existing.content = _seed_report_content(name)
            existing.updated_at = now_utc
            upgraded += 1
            continue
        session.add(
            Report(
                child_id=cid,
                date=today,
                content=_seed_report_content(name),
                created_at=now_utc,
                updated_at=None,
            )
        )
        added += 1
    await session.commit()
    print(
        f"[seed] report {added}건 추가 + {upgraded}건 평문→JSON 업그레이드 "
        f"(오늘 {today.isoformat()})"
    )


async def main() -> None:
    helper = PasswordHelper()
    async with async_session_maker() as session:
        await seed_teacher(session, helper)
        child_ids = await seed_children(session)
        await seed_parents(session, helper, child_ids)
        await seed_menu(session)
        await seed_attendance(session, child_ids)
        await seed_reports(session, child_ids)


if __name__ == "__main__":
    asyncio.run(main())
