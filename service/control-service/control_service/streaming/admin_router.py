"""수동 admin 제어 endpoint.

PLAN §3.6, SR-CAM-005.

POST /api/streaming/robots/{robot}/stop
POST /api/streaming/robots/{robot}/start
GET  /api/streaming/health
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

from control_service.auth import current_active_user
from control_service.streaming import config as scfg
from control_service.streaming.robot_controller import RobotController

# Q4 — fastapi-users 쿠키 인증. 이 endpoint 들은 admin 액션이라 인증 필수.
RobotName = Literal["gogoping", "eduping", "noriarm"]


def make_admin_router(controller: RobotController) -> APIRouter:
    router = APIRouter(prefix="/api/streaming", tags=["streaming-admin"])

    @router.post("/robots/{robot}/stop")
    async def manual_stop(
        robot: RobotName,
        _user=Depends(current_active_user),
    ) -> dict:
        robot_id = scfg.ROBOT_IDS[robot]
        if not controller.has_robot(robot_id):
            raise HTTPException(
                status_code=503,
                detail=(
                    f"robot '{robot}' 의 IP 가 등록되지 않음 "
                    f"(shared/machine_ips.json 확인)"
                ),
            )
        ok = await controller.manual_stop(robot_id)
        return {"ok": ok, "robot": robot, "action": "stop"}

    @router.post("/robots/{robot}/start")
    async def manual_start(
        robot: RobotName,
        _user=Depends(current_active_user),
    ) -> dict:
        robot_id = scfg.ROBOT_IDS[robot]
        if not controller.has_robot(robot_id):
            raise HTTPException(
                status_code=503,
                detail=f"robot '{robot}' 의 IP 가 등록되지 않음",
            )
        ok = await controller.manual_start(robot_id)
        return {"ok": ok, "robot": robot, "action": "start"}

    return router
