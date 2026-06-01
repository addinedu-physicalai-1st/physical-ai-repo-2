"""출결 endpoint 테스트."""
import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient

from control_service.config import settings

pytestmark = pytest.mark.asyncio


def _device_headers() -> dict[str, str]:
    return {"X-Device-Token": settings.robot_device_token}


async def _wait_for_bg_tasks() -> None:
    """`asyncio.create_task` + `asyncio.to_thread` 가 thread executor 까지 한 바퀴 돌게 대기.

    sleep(0) 만으론 executor thread wake-up + future resolve 까지 못 가서 raise 경로가
    flaky 했음. 50ms 면 mock 동작에 충분 — 실제 ROS publish 는 background 라 무관.
    """
    await asyncio.sleep(0.05)


async def test_list_all_attendance_includes_unchecked_children(
    teacher_client: AsyncClient, db_session
):
    from control_db.models import Attendance, Child

    today = date.today()
    c1 = Child(name="A", birth_date=date(2021, 1, 1), class_name="햇살반",
               photo_url=None, created_at=datetime.now(timezone.utc))
    c2 = Child(name="B", birth_date=date(2021, 2, 2), class_name="햇살반",
               photo_url=None, created_at=datetime.now(timezone.utc))
    db_session.add_all([c1, c2])
    await db_session.flush()

    db_session.add(
        Attendance(
            child_id=c1.id, date=today, type="IN",
            time=datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc),
        )
    )
    await db_session.flush()

    response = await teacher_client.get(f"/api/attendance?date={today.isoformat()}")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2

    by_name = {r["child_name"]: r for r in body}
    assert by_name["A"]["check_in"] is not None
    assert by_name["A"]["check_out"] is None
    assert by_name["B"]["check_in"] is None


async def test_list_all_attendance_as_parent_returns_403(parent_client: AsyncClient):
    response = await parent_client.get(f"/api/attendance?date={date.today().isoformat()}")
    assert response.status_code == 403


async def test_child_attendance_for_my_child_works(
    client: AsyncClient, make_user, db_session
):
    from control_db.models import Attendance, Child, ParentChild

    parent = await make_user("p@x.com", "test1234", role="parent")
    today = date.today()
    child = Child(name="민준", birth_date=date(2021, 1, 1), class_name="햇살반",
                  photo_url=None, created_at=datetime.now(timezone.utc))
    db_session.add(child)
    await db_session.flush()
    db_session.add(ParentChild(parent_id=parent.id, child_id=child.id))
    db_session.add(
        Attendance(child_id=child.id, date=today, type="IN",
                   time=datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc))
    )
    await db_session.flush()

    await client.post(
        "/api/auth/cookie/login",
        data={"username": "p@x.com", "password": "test1234"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    response = await client.get(f"/api/children/{child.id}/attendance")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1


async def test_child_attendance_for_others_child_returns_404(
    client: AsyncClient, make_user, db_session
):
    from control_db.models import Child

    parent = await make_user("p@x.com", "test1234", role="parent")
    other_child = Child(name="X", birth_date=date(2021, 1, 1), class_name="햇살반",
                        photo_url=None, created_at=datetime.now(timezone.utc))
    db_session.add(other_child)
    await db_session.flush()

    await client.post(
        "/api/auth/cookie/login",
        data={"username": "p@x.com", "password": "test1234"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    response = await client.get(f"/api/children/{other_child.id}/attendance")
    assert response.status_code == 404


# ---- /attendance/check + 자동 인사 모션 트리거 ----


@pytest.fixture
def fake_bridge(tmp_path):
    """가짜 eduping bridge — `app.state.eduping_bridge` 자리에 끼우고 play_routine 호출 추적.

    Preflight 통과를 위해 routines_root 아래 openarm_greeting/{morning,evening}.yaml 더미 생성.
    `is_real_follower_active` 도 True 기본 — 테스트에서 필요 시 override.
    """
    from control_service.main import app

    greeting_dir = tmp_path / "openarm_greeting"
    greeting_dir.mkdir(parents=True, exist_ok=True)
    (greeting_dir / "morning.yaml").write_text("# fixture stub\n")
    (greeting_dir / "evening.yaml").write_text("# fixture stub\n")

    bridge = SimpleNamespace(
        play_routine=MagicMock(return_value={"ok": True}),
        routines_root=tmp_path,
        is_real_follower_active=MagicMock(return_value=True),
    )
    prev = getattr(app.state, "eduping_bridge", None)
    app.state.eduping_bridge = bridge
    try:
        yield bridge
    finally:
        if prev is None:
            try:
                delattr(app.state, "eduping_bridge")
            except AttributeError:
                pass
        else:
            app.state.eduping_bridge = prev


async def _make_child(db_session, name: str = "정우"):
    from control_db.models import Child
    child = Child(name=name, birth_date=date(2021, 1, 1), class_name="햇살반",
                  photo_url=None, created_at=datetime.now(timezone.utc))
    db_session.add(child)
    await db_session.flush()
    return child


async def test_check_in_does_not_fire_greeting_replaced_by_highfive(
    client: AsyncClient, db_session, fake_bridge
):
    """등원(IN) morning 율동은 하이파이브로 대체 — 서버 팔 인사 모션을 안 친다."""
    child = await _make_child(db_session)
    response = await client.post(
        "/api/attendance/check",
        json={"child_id": child.id, "type": "IN"},
        headers=_device_headers(),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["already"] is False
    assert body["arm_status"] == "skipped:replaced_by_highfive"
    await _wait_for_bg_tasks()
    fake_bridge.play_routine.assert_not_called()


async def test_check_out_fires_evening_greeting(client: AsyncClient, db_session, fake_bridge):
    child = await _make_child(db_session, name="민준")
    response = await client.post(
        "/api/attendance/check",
        json={"child_id": child.id, "type": "OUT"},
        headers=_device_headers(),
    )
    assert response.status_code == 200, response.text
    assert response.json()["arm_status"] == "fired"
    await _wait_for_bg_tasks()
    fake_bridge.play_routine.assert_called_once()
    args, kwargs = fake_bridge.play_routine.call_args
    assert args[:2] == ("greeting", "evening")
    assert kwargs.get("target") == "real"


async def test_duplicate_check_in_does_not_fire_greeting(
    client: AsyncClient, db_session, fake_bridge
):
    from control_db.models import Attendance

    child = await _make_child(db_session, name="서연")
    db_session.add(
        Attendance(
            child_id=child.id,
            date=date.today(),
            type="IN",
            time=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()

    response = await client.post(
        "/api/attendance/check",
        json={"child_id": child.id, "type": "IN"},
        headers=_device_headers(),
    )
    assert response.status_code == 200, response.text
    assert response.json()["already"] is True
    await _wait_for_bg_tasks()
    fake_bridge.play_routine.assert_not_called()


async def test_check_out_succeeds_when_bridge_missing(client: AsyncClient, db_session):
    """eduping bridge 미초기화여도 출결은 정상 기록 — arm_status 로 사유 노출.
    (등원은 하이파이브로 대체돼 인사 모션을 안 치므로 하원으로 bridge-missing 경로 검증.)"""
    from control_service.main import app

    prev = getattr(app.state, "eduping_bridge", None)
    if hasattr(app.state, "eduping_bridge"):
        delattr(app.state, "eduping_bridge")
    try:
        child = await _make_child(db_session, name="지수")
        response = await client.post(
            "/api/attendance/check",
            json={"child_id": child.id, "type": "OUT"},
            headers=_device_headers(),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["already"] is False
        assert body["arm_status"] == "skipped:no_bridge"
    finally:
        if prev is not None:
            app.state.eduping_bridge = prev


async def test_check_out_skips_when_real_arm_inactive(
    client: AsyncClient, db_session, fake_bridge
):
    # 등원은 하이파이브로 대체 — 하원(evening)으로 no-real-arm 스킵 경로 검증.
    fake_bridge.is_real_follower_active.return_value = False
    child = await _make_child(db_session, name="윤서")
    response = await client.post(
        "/api/attendance/check",
        json={"child_id": child.id, "type": "OUT"},
        headers=_device_headers(),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["already"] is False
    assert body["arm_status"] == "skipped:no_real_arm"
    await _wait_for_bg_tasks()
    # 실물 미가동 시 background playback 자체를 schedule 안 함.
    fake_bridge.play_routine.assert_not_called()


async def test_check_out_skips_when_routine_missing(
    client: AsyncClient, db_session, fake_bridge
):
    # 등원(IN)은 하이파이브로 대체돼 서버 모션을 안 치므로 routine_missing 분기는
    # 하원(OUT)=evening 으로 검증. 픽스처가 만든 evening.yaml 을 지운다.
    (fake_bridge.routines_root / "openarm_greeting" / "evening.yaml").unlink()
    child = await _make_child(db_session, name="시우")
    response = await client.post(
        "/api/attendance/check",
        json={"child_id": child.id, "type": "OUT"},
        headers=_device_headers(),
    )
    assert response.status_code == 200, response.text
    assert response.json()["arm_status"] == "skipped:routine_missing:evening"
    await _wait_for_bg_tasks()
    fake_bridge.play_routine.assert_not_called()


# ---- DELETE /api/attendance/{child_id} (교사 디버그용 리셋) ----


async def test_delete_attendance_removes_row_and_allows_recheck(
    teacher_client: AsyncClient, db_session, fake_bridge
):
    """교사가 하원 리셋 → 같은 자녀 같은 날 OUT 을 다시 체크하면 already=False + 새 모션 trigger.

    (등원=IN 은 하이파이브로 대체돼 서버 모션을 안 치므로 refire 검증은 OUT=evening 으로 한다.)"""
    from control_db.models import Attendance

    child = await _make_child(db_session, name="재이")
    db_session.add(
        Attendance(
            child_id=child.id,
            date=date.today(),
            type="OUT",
            time=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()

    response = await teacher_client.delete(
        f"/api/attendance/{child.id}?date={date.today().isoformat()}&type=OUT"
    )
    assert response.status_code == 204, response.text

    # 재체크 시 새 row 가 생성되고 모션도 다시 fire.
    recheck = await teacher_client.post(
        "/api/attendance/check",
        json={"child_id": child.id, "type": "OUT"},
        headers=_device_headers(),
    )
    assert recheck.status_code == 200, recheck.text
    body = recheck.json()
    assert body["already"] is False
    assert body["arm_status"] == "fired"
    await _wait_for_bg_tasks()
    fake_bridge.play_routine.assert_called_once()


async def test_delete_attendance_returns_404_when_no_row(teacher_client: AsyncClient, db_session):
    child = await _make_child(db_session, name="유나")
    response = await teacher_client.delete(
        f"/api/attendance/{child.id}?date={date.today().isoformat()}&type=IN"
    )
    assert response.status_code == 404


async def test_delete_attendance_requires_teacher(parent_client: AsyncClient, db_session):
    """학부모 권한으론 디버그 삭제 거부."""
    child = await _make_child(db_session, name="도윤")
    response = await parent_client.delete(
        f"/api/attendance/{child.id}?date={date.today().isoformat()}&type=IN"
    )
    assert response.status_code == 403


async def test_check_out_succeeds_when_play_routine_raises(
    client: AsyncClient, db_session, fake_bridge
):
    """play_routine 이 예외를 던져도 출결 응답은 200 + 새 row 가 commit 돼야 한다.

    (등원=IN 은 하이파이브로 대체돼 play_routine 자체를 안 부르므로 OUT=evening 으로 검증.)"""
    fake_bridge.play_routine.side_effect = RuntimeError("real arm offline")
    child = await _make_child(db_session, name="하늘")
    response = await client.post(
        "/api/attendance/check",
        json={"child_id": child.id, "type": "OUT"},
        headers=_device_headers(),
    )
    assert response.status_code == 200, response.text
    assert response.json()["already"] is False
    await _wait_for_bg_tasks()
    fake_bridge.play_routine.assert_called_once()
