"""메뉴 endpoint 테스트."""
from datetime import date

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _seed_menu(db_session, day: int, items: list[str]):
    from control_db.models import Menu
    db_session.add(Menu(day=day, items=items))
    await db_session.flush()


async def test_menu_by_date_returns_matching_day(teacher_client: AsyncClient, db_session):
    await _seed_menu(db_session, day=15, items=["미역국", "쌀밥"])
    response = await teacher_client.get("/api/menu?date=2026-05-15")
    assert response.status_code == 200
    body = response.json()
    assert body["date"] == "2026-05-15"
    assert body["items"] == ["미역국", "쌀밥"]


async def test_menu_by_date_with_no_seed_returns_empty_items(
    teacher_client: AsyncClient,
):
    response = await teacher_client.get("/api/menu?date=2026-05-15")
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []


async def test_menu_by_month_returns_only_seeded_days(teacher_client: AsyncClient, db_session):
    await _seed_menu(db_session, 1, ["A"])
    await _seed_menu(db_session, 15, ["B"])
    await _seed_menu(db_session, 31, ["C"])

    response = await teacher_client.get("/api/menu?month=2026-05")  # May has 31 days
    assert response.status_code == 200
    body = response.json()
    days = sorted(int(e["date"].split("-")[2]) for e in body)
    assert days == [1, 15, 31]


async def test_menu_by_month_for_february_skips_31(teacher_client: AsyncClient, db_session):
    await _seed_menu(db_session, 28, ["X"])
    await _seed_menu(db_session, 31, ["Y"])  # 2 월엔 매핑 안 됨

    response = await teacher_client.get("/api/menu?month=2026-02")
    body = response.json()
    days = [e["date"] for e in body]
    assert "2026-02-28" in days
    assert all(not d.endswith("-31") for d in days)


async def test_menu_without_params_returns_400(teacher_client: AsyncClient):
    response = await teacher_client.get("/api/menu")
    assert response.status_code == 400


async def test_menu_unauthenticated_returns_401(client: AsyncClient):
    response = await client.get("/api/menu?date=2026-05-15")
    assert response.status_code == 401
