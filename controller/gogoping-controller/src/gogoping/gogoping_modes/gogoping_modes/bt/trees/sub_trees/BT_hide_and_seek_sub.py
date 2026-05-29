"""BT_hide_and_seek_sub — 6 step Sequence: move → recruit → countdown → patrol → return → end.

확장 (2026-05-25): patrol-only → 진짜 hideseek 워크플로우.

Sequence(memory=True):
    1. step_move_to_play: SetDestinationKey(play_area) + SetHideseekPhase("move_to_play") + build_goto_subtree
    2. step_recruit: SetHideseekPhase("recruit") + AwaitRecruitComplete
    3. step_countdown: SetHideseekPhase("countdown") + Countdown(30s)
    4. step_patrol: SetHideseekPhase("patrol") +
         Parallel(SuccessOnOne, children=[BT_patrol_sub, HideSeekCaughtMonitor])
    5. step_return: SetDestinationKey(play_area) + SetHideseekPhase("return") +
         Parallel(SuccessOnOne, children=[BT_goto_subtree, HideSeekCaughtMonitor])
    6. step_end: SetHideseekPhase("end") + py_trees.behaviours.Running()
         — Running 이 RUNNING 영구 유지 → root Sequence 가 SUCCESS 안 되고 → main.py 의
           task_done trigger 안 발화 → HIDEANDSEEK 유지 → mode='숨바꼭질' 유지 →
           HideAndSeekGame 마운트 유지 → EndPhase UI 가 사용자 close 까지 보임.
         사용자가 EndPhase 의 "대기로" 클릭 → postModeClick("대기") → cancel trigger →
           HIDEANDSEEK→IDLE → UI 언마운트.

blackboard 의존:
    - HIDESEEK_PLAY_AREA_KEY (named pose) — Step 1, 5 (build 시점에 1회 읽고 SetDestinationKey 의 const 인자로 박음)
    - SEARCH_WAYPOINTS — Step 4 (BT_patrol_sub)
    - HIDESEEK_REGISTERED_IDS — Step 2 (AwaitRecruitComplete), Step 4·5 (Caught monitor)
    - HIDESEEK_CAUGHT_IDS — Step 4·5 (Caught monitor)
    - DESTINATION_KEY — Step 1, 5 가 W (SetDestinationKey)
    - HIDESEEK_PHASE — 본 빌더의 SetHideseekPhase 들이 W (UI 라우팅)

빈 리스트 / 결손 시 Failure leaf — reconciler 가 정상 경로에선 미리 차단.

자세한 명세: docs/bt/trees/BT_hide_and_seek_sub.md
"""
from __future__ import annotations

import math

import py_trees
from py_trees.common import Access

from ....context import Context
from ...behaviors.common.await_recruit_complete import AwaitRecruitComplete
from ...behaviors.common.countdown import Countdown
from ...behaviors.common.set_destination_key import SetDestinationKey
from ...behaviors.common.set_hideseek_phase import SetHideseekPhase
from ...behaviors.navigation.rotate_to_yaw import RotateToYaw
from ...behaviors.perception.hide_seek_caught_monitor import HideSeekCaughtMonitor
from ...blackboard import Keys
from .BT_goto_sub import build_goto_subtree
from .BT_patrol_sub import build_patrol_sub

_COUNTDOWN_SECONDS = 30.0


def _load_grouped_vertices_from_yaml() -> list[str]:
    """yaml 에서 group 이 채워진 vertex 이름만 list 로 반환. fallback 용.

    control-service 의 _build_group_patrol_order 와 유사하지만 shuffle / NN 없음.
    BT 가 search_waypoints blackboard 없이 진입했을 때 (force_state 디버그) 즉시
    Failure 하지 않고 yaml 직접 로드해 동작 보장.
    """
    try:
        import yaml
        from pathlib import Path
        from ament_index_python.packages import get_package_share_directory
        share = Path(get_package_share_directory("gogoping_navigation"))
        wp_path = share / "config" / "waypoints.yaml"
        data = yaml.safe_load(wp_path.read_text(encoding="utf-8")) or {}
        return [
            w["name"] for w in (data.get("waypoints") or [])
            if w.get("group")
        ]
    except Exception:
        return []


def build_hide_and_seek_sub(ctx: Context) -> py_trees.behaviour.Behaviour:
    """6 step Sequence 빌더.

    Parameters
    ----------
    ctx : Context
        ``build_goto_subtree`` / ``build_patrol_sub`` 가 사용 (camera_pan / nav action client 등).

    Returns
    -------
    Behaviour
        정상: ``Sequence(name="BT_hide_and_seek_sub", memory=True)`` — 6 step.
        결손: ``Failure`` leaf (play_area / waypoints 부재).
    """
    bb = py_trees.blackboard.Client(name="BT_hide_and_seek_sub/builder")
    bb.register_key(key=Keys.HIDESEEK_PLAY_AREA_KEY, access=Access.READ)
    bb.register_key(key=Keys.SEARCH_WAYPOINTS, access=Access.READ)
    bb.register_key(key=Keys.HIDESEEK_PATROL_ONLY, access=Access.READ)

    # 각 키 별도 try — 한 키 미설정이 다른 키 fallback 으로 reset 되는 버그 방지.
    try:
        play_area = bb.get(Keys.HIDESEEK_PLAY_AREA_KEY)
    except KeyError:
        play_area = ""
    try:
        wps_raw = bb.get(Keys.SEARCH_WAYPOINTS)
    except KeyError:
        wps_raw = None
    try:
        patrol_only = bool(bb.get(Keys.HIDESEEK_PATROL_ONLY))
    except KeyError:
        patrol_only = False
    wps = list(wps_raw or [])

    # fallback (2026-05-28) — force_state 등으로 search_waypoints 가 비어있는
    # 경우 yaml 의 group 채워진 vertex 를 직접 로드. control-service Goal flow 우회
    # 진입을 허용 (debug 편의 + BT 가 즉시 죽지 않게 안전망).
    if not wps:
        wps = _load_grouped_vertices_from_yaml()
        if not wps:
            return py_trees.behaviours.Failure(name="BT_hide_and_seek_sub_no_waypoints")

    # ─── patrol_only 분기 ─────────────────────────────────────────────────
    # admin UI [순찰] 버튼이 set — 모집/카운트다운/이동/복귀 없이 patrol_sub 만
    # 단독 실행. SetHideseekPhase("patrol") 만 추가해 robot-web 이 PatrolPhase UI
    # 곧바로 마운트하도록.
    if patrol_only:
        return py_trees.composites.Sequence(
            name="BT_hide_and_seek_sub_patrol_only",
            memory=True,
            children=[
                SetHideseekPhase(name="set_phase_patrol_only", phase="patrol"),
                build_patrol_sub(ctx, wps),
            ],
        )

    # ─── 술래잡기 6-step Sequence ─────────────────────────────────────────
    if not play_area:
        # fallback (2026-05-28) — force_state 등으로 play_area 비었으면
        # state_to_goal 의 default "운동장-단상" 사용.
        play_area = "운동장-단상"

    # Step 1: move_to_play — destination 셋 → phase 마커 → 실제 goto subtree → 오른쪽(yaw=0) 정렬.
    step_move = py_trees.composites.Sequence(
        name="step_move_to_play",
        memory=True,
        children=[
            SetDestinationKey(name="set_dest_play_area_move", key=play_area),
            SetHideseekPhase(name="set_phase_move_to_play", phase="move_to_play"),
            build_goto_subtree(ctx),
            RotateToYaw(name="face_right_at_play_area", target_yaw=0.0),
        ],
    )

    # Step 2: recruit — UI 가 등록 종료 시 control-service 가 HIDESEEK_REGISTERED_IDS 셋팅.
    # 등록 완료까지만 — 180° 회전은 countdown 과 동시에(아래 step_countdown 의 parallel).
    step_recruit = py_trees.composites.Sequence(
        name="step_recruit",
        memory=True,
        children=[
            SetHideseekPhase(name="set_phase_recruit", phase="recruit"),
            AwaitRecruitComplete(name="await_recruit"),
        ],
    )

    # Step 3: countdown — 30초. 출발 누르면 "완전히 뒤돈 뒤 카운트" 가 아니라
    # **바로 30초 카운트 시작 + 180° 회전을 동시에**(병렬) 진행. 회전은 그때만 1.4배 빠르게
    # (angular_speed 0.5 → 0.7). countdown 이 끝나면 step_countdown SUCCESS (회전은 ~4.5s 면 끝).
    countdown_seq = py_trees.composites.Sequence(
        name="countdown_seq",
        memory=True,
        children=[
            SetHideseekPhase(name="set_phase_countdown", phase="countdown"),
            Countdown(
                name="countdown_30s",
                seconds=_COUNTDOWN_SECONDS,
                check_skip_key=Keys.HIDESEEK_SKIP_COUNTDOWN,
            ),
        ],
    )
    step_countdown = py_trees.composites.Parallel(
        name="step_countdown",
        # countdown 이 SUCCESS 판정 기준 — 회전은 동시 진행만 (먼저 끝나도 countdown 대기).
        policy=py_trees.common.ParallelPolicy.SuccessOnSelected(
            children=[countdown_seq], synchronise=False,
        ),
        children=[
            countdown_seq,
            RotateToYaw(
                name="face_left_during_countdown",
                target_yaw=math.pi,
                angular_speed=0.7,   # 0.5 × 1.4 — 카운트다운 중에만 빠르게 뒤돌기
            ),
        ],
    )

    # Step 4: patrol — parallel(patrol_sub + caught monitor). 자식 중 하나라도 SUCCESS 면 parallel SUCCESS.
    patrol_subtree = build_patrol_sub(ctx, wps)
    caught_mon_patrol = HideSeekCaughtMonitor(name="caught_monitor_patrol")
    patrol_parallel = py_trees.composites.Parallel(
        name="patrol_with_caught_monitor",
        policy=py_trees.common.ParallelPolicy.SuccessOnOne(),
        children=[patrol_subtree, caught_mon_patrol],
    )
    step_patrol = py_trees.composites.Sequence(
        name="step_patrol",
        memory=True,
        children=[
            SetHideseekPhase(name="set_phase_patrol", phase="patrol"),
            patrol_parallel,
        ],
    )

    # Step 5: return — destination 재셋 (확실히 play_area) → phase → parallel(goto + caught).
    return_goto = build_goto_subtree(ctx)
    caught_mon_return = HideSeekCaughtMonitor(name="caught_monitor_return")
    return_parallel = py_trees.composites.Parallel(
        name="return_with_caught_monitor",
        policy=py_trees.common.ParallelPolicy.SuccessOnOne(),
        children=[return_goto, caught_mon_return],
    )
    step_return = py_trees.composites.Sequence(
        name="step_return",
        memory=True,
        children=[
            SetDestinationKey(name="set_dest_play_area_return", key=play_area),
            SetHideseekPhase(name="set_phase_return", phase="return"),
            return_parallel,
        ],
    )

    # Step 6: end — phase 마커 셋팅 후 영구 RUNNING. 사용자의 명시 cancel (postModeClick("대기"))
    # 만이 종료시킬 수 있다. RUNNING 이 root SUCCESS 를 막아 main.py 의 task_done 발화 차단.
    step_end = py_trees.composites.Sequence(
        name="step_end",
        memory=True,
        children=[
            SetHideseekPhase(name="set_phase_end", phase="end"),
            py_trees.behaviours.Running(name="hideseek_end_idle"),
        ],
    )

    return py_trees.composites.Sequence(
        name="BT_hide_and_seek_sub",
        memory=True,
        children=[step_move, step_recruit, step_countdown, step_patrol, step_return, step_end],
    )
