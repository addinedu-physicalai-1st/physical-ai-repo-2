"""DB seed — 교사·학부모·자녀 + 31일 메뉴.

사용:
    python -m server.db.seed                  # 추가만 (idempotent)
"""
import asyncio
import json
from datetime import date
from pathlib import Path
from typing import Sequence

from fastapi_users.password import PasswordHelper
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.db.models import Child, Menu, ParentChild, User
from server.db.session import async_session_maker

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
    ("parent4@test.com", "이알평", "이강택"),
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
    from server.ai.embed import embed_text

    for row in missing:
        row.embedding = await embed_text(menu_doc_text(row.day, row.items))
    await session.commit()
    print(f"[seed] menu embedding {len(missing)}건 생성 완료")


async def main() -> None:
    helper = PasswordHelper()
    async with async_session_maker() as session:
        await seed_teacher(session, helper)
        child_ids = await seed_children(session)
        await seed_parents(session, helper, child_ids)
        await seed_menu(session)


if __name__ == "__main__":
    asyncio.run(main())
