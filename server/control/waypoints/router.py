"""웨이포인트 REST + SSE. teleop install 패턴 따름."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from server.control.waypoints import yaml_store as ys
from server.control.waypoints.ros_bridge import WaypointsRosBridge


class CreateBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=40)


class GotoBody(BaseModel):
    name: str = Field(..., min_length=1)


class RouteBody(BaseModel):
    """다익스트라 경로 조회 / 시작 요청. name 은 목적지 vertex name."""
    name: str = Field(..., min_length=1)


class GotoPoseBody(BaseModel):
    """RViz Nav2 Goal 패턴 — 좌표 직접 지정 (클릭-드래그 인터랙션용).
    yaml 에 저장 안 함, 단발 NavigateToPose 만."""
    x: float
    y: float
    yaw: float


class InitialPoseBody(BaseModel):
    """RViz 2D Pose Estimate 패턴 — AMCL 위치 추정 재초기화.
    로봇은 이동하지 않음. AMCL 파티클이 이 좌표 근처로 재샘플링됨."""
    x: float
    y: float
    yaw: float


class LaneBody(BaseModel):
    """간선 잇기/끊기 — yaml key `from` 는 파이썬 예약어라 alias 로 매핑."""
    from_: str = Field(..., min_length=1, alias="from")
    to: str = Field(..., min_length=1)

    model_config = {"populate_by_name": True}


class AutoEdgeBody(BaseModel):
    """자동 간선 — 거리 threshold 이하 모든 노드 쌍을 양방향 lane 으로 생성."""
    threshold: float = Field(..., gt=0)
    replace_existing: bool = False


class MoveBody(BaseModel):
    """노드 이동 — PATCH /waypoints/{name}."""
    x: float
    y: float
    yaw: float


class ClickAddBody(BaseModel):
    """좌표 직접 노드 추가 — POST /waypoints/click."""
    name: str = Field(..., min_length=1, max_length=40)
    x: float
    y: float
    yaw: float


def install(app: FastAPI, bridge: WaypointsRosBridge) -> None:
    router = APIRouter(prefix="/waypoints", tags=["waypoints"])

    @router.get("")
    def list_all() -> dict:
        wps, patrols = ys.load()
        return {
            "waypoints": [
                {"name": w.name, "x": w.x, "y": w.y, "yaw": w.yaw}
                for w in wps
            ],
            "patrols": patrols,
            "lanes": [
                {"from": ln.from_, "to": ln.to, "bidirectional": ln.bidirectional}
                for ln in ys.load_lanes()
            ],
        }

    @router.post("", status_code=201)
    def create(body: CreateBody) -> dict:
        snap = bridge.odom_snapshot()
        if snap is None:
            raise HTTPException(
                409,
                "odom 미수신 — 텔레옵으로 로봇을 잠시 움직여주세요",
            )
        try:
            wp = ys.add(body.name.strip(), *snap)
        except ys.WaypointStoreError as e:
            raise HTTPException(409, str(e))
        bridge._emit({"type": "waypoints", "reason": "created"})
        return {"name": wp.name, "x": wp.x, "y": wp.y, "yaw": wp.yaw}

    # ────────── nav graph editor (Task 10+) ──────────
    # 주의: 아래 lane/* endpoint 는 `@router.delete("/{name}")` 의 path parameter
    # 매칭에 잡히지 않게 그것보다 위에서 등록한다 (FastAPI 는 등록 순서대로 매칭).

    def _check_nav_idle() -> None:
        """nav2 active 면 409 nav_busy. UI 우회 방지용 백엔드 검증."""
        h = bridge.health()
        if h.get("nav_active"):
            raise HTTPException(409, "nav_busy")

    def _emit_state_after_write(reload_result: dict | None = None) -> dict:
        """write 후 표준 응답 — yaml 새 상태 동봉 + SSE broadcast.
        reload_result.success 가 False 면 yaml_saved/graph_reloaded 명시."""
        wps, _ = ys.load()
        lanes = ys.load_lanes()
        bridge._emit({"type": "waypoints", "reason": "updated"})
        payload = {
            "ok": True,
            "waypoints": [{"name": w.name, "x": w.x, "y": w.y, "yaw": w.yaw} for w in wps],
            "lanes": [{"from": ln.from_, "to": ln.to, "bidirectional": ln.bidirectional}
                      for ln in lanes],
        }
        if reload_result is not None and not reload_result.get("success", True):
            payload["yaml_saved"] = True
            payload["graph_reloaded"] = False
            payload["detail"] = reload_result.get("message", "")
        return payload

    @router.post("/lanes")
    def add_lane_route(body: LaneBody) -> dict:
        _check_nav_idle()
        try:
            ys.add_lane(body.from_, body.to)
        except ys.LaneStoreError as e:
            if "lane_exists" in str(e):
                raise HTTPException(409, "lane_exists")
            raise HTTPException(400, str(e))
        reload_result = bridge.reload_graph()
        return _emit_state_after_write(reload_result)

    @router.delete("/lanes")
    def remove_lane_route(body: LaneBody) -> dict:
        _check_nav_idle()
        try:
            ys.remove_lane(body.from_, body.to)
        except KeyError:
            raise HTTPException(404, "lane 없음")
        reload_result = bridge.reload_graph()
        return _emit_state_after_write(reload_result)

    @router.post("/undo")
    def undo_route() -> dict:
        """가장 최근 add() 1개 되돌림. 노드에 lane 잇혀있으면 409."""
        _check_nav_idle()
        try:
            result = ys.undo_last_add()
        except ys.WaypointStoreError as e:
            if "node_has_lanes" in str(e):
                raise HTTPException(409, "node_has_lanes")
            raise HTTPException(409, str(e))
        if result is None:
            raise HTTPException(408, "nothing_to_undo")
        reload_result = bridge.reload_graph()
        return _emit_state_after_write(reload_result)

    @router.post("/click", status_code=201)
    def click_add(body: ClickAddBody) -> dict:
        """좌표 직접 노드 추가 — admin UI 의 빈 곳 드래그 → 이름 팝업 후 호출."""
        _check_nav_idle()
        try:
            ys.add(body.name.strip(), body.x, body.y, body.yaw)
        except ys.WaypointStoreError as e:
            raise HTTPException(409, str(e))
        reload_result = bridge.reload_graph()
        return _emit_state_after_write(reload_result)

    @router.patch("/{name}")
    def move_node(name: str, body: MoveBody) -> dict:
        _check_nav_idle()
        try:
            ys.update(name, body.x, body.y, body.yaw)
        except KeyError:
            raise HTTPException(404, f"'{name}' 없음")
        reload_result = bridge.reload_graph()
        return _emit_state_after_write(reload_result)

    @router.post("/lanes/auto")
    def auto_edge_route(body: AutoEdgeBody) -> dict:
        """자동 간선 — 거리 threshold 이하 노드 쌍 일괄 lane 생성.
        replace_existing=True 면 기존 모두 제거 후 재생성."""
        _check_nav_idle()
        from math import hypot
        wps, _ = ys.load()
        # 결정론적 쌍 생성 (이름 정렬)
        pairs: list[tuple[str, str]] = []
        for i, a in enumerate(wps):
            for b in wps[i + 1:]:
                if hypot(a.x - b.x, a.y - b.y) <= body.threshold:
                    pairs.append(tuple(sorted([a.name, b.name])))
        if body.replace_existing:
            for ln in list(ys.load_lanes()):
                ys.remove_lane(ln.from_, ln.to)
        existing_keys = {
            tuple(sorted([ln.from_, ln.to])) for ln in ys.load_lanes()
        }
        added = 0
        skipped = 0
        for from_, to in pairs:
            key = tuple(sorted([from_, to]))
            if key in existing_keys:
                skipped += 1
                continue
            try:
                ys.add_lane(from_, to)
                added += 1
                existing_keys.add(key)
            except ys.LaneStoreError:
                skipped += 1
        reload_result = bridge.reload_graph()
        payload = _emit_state_after_write(reload_result)
        payload["added"] = added
        payload["skipped"] = skipped
        return payload

    @router.delete("/{name}")
    def delete(name: str) -> dict:
        try:
            cascaded = ys.remove(name)
        except KeyError:
            raise HTTPException(404, f"'{name}' 없음")
        except ys.WaypointStoreError as e:
            raise HTTPException(409, str(e))
        bridge._emit({"type": "waypoints", "reason": "deleted"})
        return {
            "ok": True,
            "cascaded_lanes": [
                {"from": ln.from_, "to": ln.to} for ln in cascaded
            ],
        }

    @router.post("/goto", status_code=202)
    def goto(body: GotoBody) -> dict:
        try:
            wp = ys.get(body.name)
        except KeyError:
            raise HTTPException(404, f"'{body.name}' 없음")
        goal_id = uuid4().hex
        bridge.navigate_to_pose(wp.x, wp.y, wp.yaw, goal_id)
        return {"goal_id": goal_id, "name": wp.name}

    @router.post("/goto-pose", status_code=202)
    def goto_pose(body: GotoPoseBody) -> dict:
        """좌표 직접 지정 Goto — RViz Nav2 Goal 과 동일 패턴.
        클릭-드래그 인터랙션에서 사용. yaml 저장 안 함."""
        goal_id = uuid4().hex
        bridge.navigate_to_pose(body.x, body.y, body.yaw, goal_id)
        return {
            "goal_id": goal_id,
            "name": "(click)",
            "x": body.x, "y": body.y, "yaw": body.yaw,
        }

    @router.post("/initialpose", status_code=202)
    def initial_pose(body: InitialPoseBody) -> dict:
        """AMCL 위치 추정 재초기화 — RViz 2D Pose Estimate 와 동일 패턴.
        admin-ui 의 Shift+클릭-드래그 인터랙션에서 사용. 로봇 이동 없음."""
        bridge.set_initial_pose(body.x, body.y, body.yaw)
        return {"x": body.x, "y": body.y, "yaw": body.yaw}

    @router.post("/patrol/{patrol_name}", status_code=202)
    def patrol(patrol_name: str) -> dict:
        try:
            members = ys.get_patrol(patrol_name)
        except KeyError:
            raise HTTPException(404, f"patrol '{patrol_name}' 없음")
        goal_id = uuid4().hex
        bridge.follow_waypoints(
            [(m.x, m.y, m.yaw) for m in members], goal_id
        )
        return {
            "goal_id": goal_id,
            "patrol": patrol_name,
            "waypoints": [
                {"name": m.name, "x": m.x, "y": m.y, "yaw": m.yaw}
                for m in members
            ],
        }

    @router.get("/patrol/{patrol_name}")
    def get_patrol(patrol_name: str) -> dict:
        """Lookup-only — BT 가 캐시용으로 호출."""
        try:
            members = ys.get_patrol(patrol_name)
        except KeyError:
            raise HTTPException(404, f"patrol '{patrol_name}' 없음")
        return {
            "patrol": patrol_name,
            "waypoints": [
                {"name": m.name, "x": m.x, "y": m.y, "yaw": m.yaw}
                for m in members
            ],
        }

    @router.post("/route")
    def route(body: RouteBody) -> dict:
        """다익스트라 경로 조회 (시각화/디버깅용). 로봇 안 움직임."""
        result = bridge.route_to(body.name)
        if not result["success"]:
            raise HTTPException(404, result["message"])
        return result

    @router.post("/navigate", status_code=202)
    def navigate(body: RouteBody) -> dict:
        """vertex 이름으로 graph routing 시작 — 다익스트라 경로 따라 nav2 위임."""
        goal_id = uuid4().hex
        bridge.navigate_to_vertex(body.name, goal_id)
        return {"goal_id": goal_id, "name": body.name}

    @router.post("/cancel")
    def cancel() -> dict:
        bridge.cancel_current()
        return {"ok": True}

    @router.get("/health")
    def health() -> dict:
        h = bridge.health()
        script = (Path(__file__).resolve().parents[3]
                  / "device" / "gogoping_ws" / "src" / "gogoping"
                  / "gogoping_navigation" / "map_scripts"
                  / "check-maps-drift.sh")
        if script.exists():
            try:
                rc = subprocess.run(
                    ["bash", str(script)],
                    capture_output=True, timeout=5,
                ).returncode
                h["map_drift"] = (rc != 0)
            except (subprocess.TimeoutExpired, OSError):
                h["map_drift"] = False
        else:
            h["map_drift"] = False
        return h

    @router.get("/events")
    async def events(request: Request) -> StreamingResponse:
        q: asyncio.Queue[dict] = asyncio.Queue(maxsize=100)
        bridge.register_listener(q)

        async def gen():
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        ev = await asyncio.wait_for(q.get(), timeout=15.0)
                        yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
            finally:
                bridge.unregister_listener(q)

        return StreamingResponse(gen(), media_type="text/event-stream")

    app.include_router(router)
