"""BT_return_sub — 도킹 복귀 SubTree.

흐름 (3단계):
    1. NavigateToVertex("충전소입구")  — graph_router 로 lane 따라 도크 앞까지
    2. AlignToDock                     — CHARGING_DOCK_TARGET_YAW 까지 제자리 회전
    3. ReverseIntoDock                 — N초 동안 cmd_vel.linear.x 후진 → 도크 도달

전체를 OneShot 으로 감싸 SUCCESS 후 재실행 차단 (Sequence 자식 재돌리기 방지).
자동 도킹 (접점 감지) 은 발표 범위 외 — 사람이 admin UI 디버그 버튼으로 `docked`
trigger 발사 → CHARGING 전이.

빌더 호출 시점 (RETURNING / LOW_BATTERY_RETURN 진입 시 BT swap) 에 blackboard 의
``CHARGING_DOCK_APPROACH_KEY = "충전소입구"`` + ``CHARGING_DOCK_TARGET_YAW`` =
waypoints.yaml 의 충전소입구 vertex.yaw 를 채워둔다. yaml 이 admin UI 로 갱신
되면 다음 RETURNING 진입 시 자동 반영.

자세한 디자인 결정: ``docs/superpowers/specs/`` (없음 — 대화로만 결정).
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import py_trees
import yaml
from py_trees.common import Access

from ...behaviors.navigation.align_to_dock import AlignToDock
from ...behaviors.navigation.navigate_to_vertex import NavigateToVertex
from ...behaviors.navigation.reverse_into_dock import ReverseIntoDock
from ...blackboard import Keys

if TYPE_CHECKING:
    from ....context import Context


_APPROACH_VERTEX_NAME = "충전소입구"


def _load_vertex_yaw(vertex_name: str) -> float:
    """waypoints.yaml 에서 vertex.yaw 조회. 못 찾으면 0.0 (AlignToDock 가 즉시 SUCCESS).

    경로 우선순위:
      1. ament share dir (``get_package_share_directory("gogoping_navigation")``)
      2. source tree 의 ``config/waypoints.yaml`` (개발 환경)
    """
    candidates: list[Path] = []
    try:
        from ament_index_python.packages import get_package_share_directory
        candidates.append(
            Path(get_package_share_directory("gogoping_navigation"))
            / "config" / "waypoints.yaml"
        )
    except Exception:
        pass
    # source tree fallback — 이 파일 기준 상대 경로
    here = Path(__file__).resolve()
    candidates.append(
        here.parents[5] / "gogoping_navigation" / "config" / "waypoints.yaml"
    )

    for path in candidates:
        if not path.exists():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        for v in data.get("waypoints", []):
            if v.get("name") == vertex_name:
                return float(v.get("yaw", 0.0))
    return 0.0


def _seed_blackboard(approach_vertex_name: str) -> None:
    """SubTree 진입 시 blackboard 의 접근 vertex name + target yaw 를 1회 세팅."""
    bb = py_trees.blackboard.Client(name="return_subtree_init")
    bb.register_key(key=Keys.CHARGING_DOCK_APPROACH_KEY, access=Access.WRITE)
    bb.register_key(key=Keys.CHARGING_DOCK_TARGET_YAW, access=Access.WRITE)
    bb.set(Keys.CHARGING_DOCK_APPROACH_KEY, approach_vertex_name)
    bb.set(Keys.CHARGING_DOCK_TARGET_YAW, _load_vertex_yaw(approach_vertex_name))


def build_return_subtree(ctx: "Context") -> py_trees.behaviour.Behaviour:
    """RETURNING / LOW_BATTERY_RETURN MainTree 의 Parallel 자식으로 부착할 SubTree.

    OneShot 으로 감싸 SUCCESS 후 재실행 차단.
    """
    _seed_blackboard(_APPROACH_VERTEX_NAME)

    sequence = py_trees.composites.Sequence(
        name="return_sequence",
        memory=True,
        children=[
            NavigateToVertex(
                name="navigate_to_dock_approach",
                target_key=Keys.CHARGING_DOCK_APPROACH_KEY,
            ),
            AlignToDock("align_to_dock", ctx),
            ReverseIntoDock("reverse_into_dock", ctx),
        ],
    )
    return py_trees.decorators.OneShot(
        name="BT_return_sub",  # tree_inspector 의 BT_*_sub 패턴 매칭용 — admin UI BT SUB 영역에 표시
        child=sequence,
        policy=py_trees.common.OneShotPolicy.ON_COMPLETION,
    )


__all__ = ["build_return_subtree"]
