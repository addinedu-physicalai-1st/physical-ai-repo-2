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

    @router.delete("/{name}")
    def delete(name: str) -> dict:
        try:
            ys.remove(name)
        except KeyError:
            raise HTTPException(404, f"'{name}' 없음")
        except ys.WaypointStoreError as e:
            raise HTTPException(409, str(e))
        bridge._emit({"type": "waypoints", "reason": "deleted"})
        return {"ok": True}

    @router.post("/goto", status_code=202)
    def goto(body: GotoBody) -> dict:
        try:
            wp = ys.get(body.name)
        except KeyError:
            raise HTTPException(404, f"'{body.name}' 없음")
        goal_id = uuid4().hex
        bridge.navigate_to_pose(wp.x, wp.y, wp.yaw, goal_id)
        return {"goal_id": goal_id, "name": wp.name}

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
