"""보고서 타임라인 골격 (skeleton) — 일과표를 1차 spine 으로 두고 사진 클러스터·등하원
시각을 끼워 넣은 row 배열을 만든다.

이 골격을 LLM 프롬프트에 그대로 보내고, LLM 은 **각 row 의 `text` 필드만** 채운다.
응답을 파싱한 뒤 `enforce_skeleton_on_events` 가 골격에 맞춰 다시 정렬·검증해 LLM
이 row 를 추가/삭제/재정렬해도 골격이 보존되도록 한다.

설계:
- skeleton 의 각 row 는 `time`, `slot_label`, `photo_id`, `photo_ids`, `role` 을 갖는다.
- role:
    "schedule"        — 일과표 슬롯 시작 시각(spine).
    "schedule-end"    — 마지막 슬롯 종료 시각(하루의 끝).
    "attendance-in"   — DB 등원 시각이 슬롯 시작과 다르면 별도 row.
    "attendance-out"  — DB 하원 시각이 슬롯 시작과 다르면 별도 row.
    "photo-cluster"   — 같은 세션 사진 묶음 한 줄. 슬롯 안에 별도 row 로 삽입.
    "no-data-start"   — 등원·당일 사진이 모두 없을 때 첫 schedule row 의 변형.
    "no-data-end"     — 하원 시각이 없을 때 마지막 schedule-end row 의 변형.

photo placement 정책 (사용자 결정 — "Separate row inside the slot"):
- 사진 클러스터는 슬롯 spine 과 **별도 row** 로 슬롯 내부에 들어간다.
- 같은 슬롯 안에 사진 클러스터 row 가 있어도 schedule row 는 그대로 유지한다.
"""
from __future__ import annotations

from typing import Any, TypedDict

from server.ai.korean_postprocess import (
    _canonical_hhmm,
    _cluster_photo_events_by_session,
    _hhmm_to_minutes,
    _mode_display_korean,
    _schedule_slots_sorted,
    _slot_label_at_time_sorted,
    robot_display_korean,
    subject_particle_phrase,
    topic_particle_phrase,
)


class SkeletonRow(TypedDict, total=False):
    time: str             # HH:MM
    slot_label: str       # 해당 시각이 속하는 일과표 활동명 (없으면 "")
    photo_id: int | None  # 대표 photo_id (감정 점수 최고)
    photo_ids: list[int]  # 클러스터의 전체 photo_id (시간순)
    role: str             # 위 docstring 의 role 값 중 하나
    # attendance-in/out 인데 DB 기록 시각이 일과표 윈도우 밖이라 boundary(09:00/18:00)
    # 로 끌어붙인 경우: 텍스트에 (잘못된) 시각을 노출하지 않도록 표시.
    attendance_time_clamped: bool
    # photo-cluster 메타 — LLM 이 영문 id 를 음역 (예: noriarm → 노리아르마) 하지 않도록 한국어로 미리 변환.
    photo_robot_ko: str   # 예: "노리암"
    photo_mode_ko: str    # 예: "OX 퀴즈"
    photo_emotion: str    # 예: "happy"
    photo_score: str      # 예: "0.90"


def build_timeline_skeleton(
    schedule: dict[str, str] | None,
    photo_events: list[dict[str, Any]],
    attendance: dict[str, str | None] | None,
    *,
    cluster_gap_minutes: int = 75,
) -> list[SkeletonRow]:
    """spine = 일과표 슬롯 시작 시각. 사진 클러스터·등하원 row 를 끼워 넣는다.

    9–18 같은 일과표 윈도우를 벗어나는 입력 처리:
    - 사진 클러스터: 시작 시각을 윈도우 [첫 슬롯 시작, 마지막 슬롯 종료−1분] 안으로 clamp.
      윈도우 안의 다른 슬롯으로 옮겨 들어간 사진은 그 슬롯 라벨로 다시 attach.
    - 등하원: 윈도우 밖이면 row 자체를 drop. 「20:32 등원」 같은 사실에 어긋난 표시를 막는다.
    """
    slots = _schedule_slots_sorted(schedule or {})
    rows: list[SkeletonRow] = []
    win_start = slots[0][1] if slots else None
    win_end = slots[-1][2] if slots else None  # 분 단위. 18:00 같은 마지막 슬롯 종료.

    # 활동 슬롯(등원·하원·식사·낮잠을 제외한 슬롯) — 윈도우 밖 사진을 의미 있는 시각에 배치할 때 쓴다.
    # 예: OX 퀴즈 사진이 01:49 같은 새벽이면 등원 시간이 아닌 오전 활동 (예: 11:00) 으로 옮긴다.
    _SLOT_EXCLUDE_KEYWORDS = ("등원", "하원", "점심", "낮잠", "간식")
    activity_slots = [
        (s, ta, tb, lab) for s, ta, tb, lab in slots
        if not any(k in (lab or "") for k in _SLOT_EXCLUDE_KEYWORDS)
    ]
    if activity_slots:
        am_target_min = (activity_slots[0][1] + activity_slots[0][2]) // 2
        pm_target_min = (activity_slots[-1][1] + activity_slots[-1][2]) // 2
    elif slots:
        # 활동 슬롯이 비면 윈도우 안쪽 1분으로 fallback.
        am_target_min = slots[0][1] + 1
        pm_target_min = slots[-1][2] - 1
    else:
        am_target_min = pm_target_min = None

    def _within_window(hhmm: str) -> bool:
        if win_start is None or win_end is None:
            return True
        try:
            m = _hhmm_to_minutes(hhmm)
        except ValueError:
            return False
        return win_start <= m <= win_end

    def _clamp_into_window(hhmm: str) -> str:
        """윈도우 밖 사진을 오전/오후 활동 슬롯의 한가운데로 옮긴다.

        - 윈도우 안 시각: 그대로 (실제 촬영 시각 유지).
        - 윈도우 시작 전 (예: 01:49) → 오전 활동 슬롯 중간 (예: 11:00).
        - 윈도우 종료 후 (예: 23:50) → 오후 활동 슬롯 중간 (예: 15:30).
        근거: 등원·식사·낮잠·하원 슬롯은 활동 사진이 어울리지 않으므로 활동 슬롯에 모은다.
        """
        if win_start is None or win_end is None:
            return hhmm
        try:
            m = _hhmm_to_minutes(hhmm)
        except ValueError:
            return _minutes_to_hhmm(am_target_min) if am_target_min is not None else hhmm
        if win_start <= m <= win_end:
            return hhmm
        if m < win_start:
            return _minutes_to_hhmm(am_target_min) if am_target_min is not None else _minutes_to_hhmm(win_start + 1)
        return _minutes_to_hhmm(pm_target_min) if pm_target_min is not None else _minutes_to_hhmm(win_end - 1)

    # 1) spine — 슬롯 시작 시각마다 한 row
    for start_hhmm, _ta, _tb, label in slots:
        rows.append({
            "time": _canonical_hhmm(start_hhmm),
            "slot_label": label,
            "photo_id": None,
            "photo_ids": [],
            "role": "schedule",
        })

    # 2) 하루 끝 — 마지막 슬롯 종료 시각 row (스피너 닫기 용)
    if slots:
        _start, _ta, tb_last, label_last = slots[-1]
        end_hhmm = _minutes_to_hhmm(tb_last)
        if not any(r["time"] == end_hhmm for r in rows):
            rows.append({
                "time": end_hhmm,
                "slot_label": label_last,
                "photo_id": None,
                "photo_ids": [],
                "role": "schedule-end",
            })

    # 3) 사진 클러스터 — 슬롯 안에 별도 row 로 끼움
    for cluster in _cluster_photo_events_by_session(
        photo_events, gap_minutes=cluster_gap_minutes
    ):
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
        if not pids_ordered:
            continue
        best = max(cluster, key=lambda p: float(str(p.get("score", "0"))))
        try:
            best_pid = int(best["photo_id"])
        except (KeyError, TypeError, ValueError):
            best_pid = pids_ordered[0]
        first_t_raw = _canonical_hhmm(str(cluster[0]["time"]).strip())
        first_t = _clamp_into_window(first_t_raw)
        rows.append({
            "time": first_t,
            "slot_label": _slot_label_at_time_sorted(schedule, first_t),
            "photo_id": best_pid,
            "photo_ids": pids_ordered,
            "role": "photo-cluster",
            "photo_robot_ko": robot_display_korean(str(best.get("robot", ""))),
            "photo_mode_ko": _mode_display_korean(str(best.get("mode", ""))),
            "photo_emotion": str(best.get("emotion", "")).strip(),
            "photo_score": str(best.get("score", "")).strip(),
        })

    # 4) 등하원 시각 — 일과표 윈도우 밖은 drop. 슬롯 시작과 같으면 그 schedule row 의 role 만 교체,
    #    다르면 별도 attendance row 를 끼워 넣는다.
    att = attendance or {}
    cin = att.get("check_in_kst")
    cout = att.get("check_out_kst")
    if cin:
        cin_n = _canonical_hhmm(str(cin).strip())
        if cin_n and _within_window(cin_n):
            existing_at_t = next(
                (r for r in rows if r["time"] == cin_n and r["role"] in ("schedule", "schedule-end")),
                None,
            )
            if existing_at_t is not None:
                existing_at_t["role"] = "attendance-in"
            else:
                rows.append({
                    "time": cin_n,
                    "slot_label": _slot_label_at_time_sorted(schedule, cin_n),
                    "photo_id": None,
                    "photo_ids": [],
                    "role": "attendance-in",
                })
    if cout:
        cout_n = _canonical_hhmm(str(cout).strip())
        if cout_n and _within_window(cout_n):
            existing_at_t = next(
                (r for r in rows if r["time"] == cout_n and r["role"] in ("schedule", "schedule-end")),
                None,
            )
            if existing_at_t is not None:
                existing_at_t["role"] = "attendance-out"
            else:
                rows.append({
                    "time": cout_n,
                    "slot_label": _slot_label_at_time_sorted(schedule, cout_n),
                    "photo_id": None,
                    "photo_ids": [],
                    "role": "attendance-out",
                })

    # 5) Boundary 규칙 — 첫/마지막 timeline row 는 attendance 또는 no-data 만 허용.
    #    photo·schedule 이 boundary 시각을 차지하지 못하게 막는다.
    win_start_hhmm = _minutes_to_hhmm(win_start) if win_start is not None else None
    win_end_hhmm = _minutes_to_hhmm(win_end) if win_end is not None else None
    cin_n = _canonical_hhmm(str(cin).strip()) if cin else None
    cout_n = _canonical_hhmm(str(cout).strip()) if cout else None

    # 5a) Photo-cluster 가 boundary 시각에 정확히 박히면 1분 안쪽으로 옮긴다 (09:00 → 09:01,
    #     18:00 → 17:59). 이렇게 해야 보호 대상인 boundary row 가 dedup 에서 살아남는다.
    if win_start_hhmm and win_start is not None:
        for r in rows:
            if r.get("role") == "photo-cluster" and r["time"] == win_start_hhmm:
                r["time"] = _minutes_to_hhmm(win_start + 1)
    if win_end_hhmm and win_end is not None:
        for r in rows:
            if r.get("role") == "photo-cluster" and r["time"] == win_end_hhmm:
                r["time"] = _minutes_to_hhmm(win_end - 1)

    # 5b) Boundary role 결정 — 첫 row(win_start)
    #   · cin in-window 이면 step 4 가 처리 (promote 혹은 별도 row + 이후 필터링).
    #   · cin out-of-window 면 09:00 boundary 에 attendance-in 을 박되 시각 표시는 생략 (clamped).
    #   · cin 없음 → no-data-start.
    if win_start_hhmm:
        cin_present_anywhere = cin_n is not None
        cin_in_window = cin_present_anywhere and _within_window(cin_n)
        if cin_present_anywhere and not cin_in_window:
            for r in rows:
                if r["time"] == win_start_hhmm and r["role"] == "schedule":
                    r["role"] = "attendance-in"
                    r["attendance_time_clamped"] = True
                    break
        elif not cin_in_window:
            for r in rows:
                if r["time"] == win_start_hhmm and r["role"] == "schedule":
                    r["role"] = "no-data-start"
                    break

    # 5c) Boundary role 결정 — 마지막 row(win_end)
    if win_end_hhmm:
        cout_present_anywhere = cout_n is not None
        cout_in_window = cout_present_anywhere and _within_window(cout_n)
        if cout_present_anywhere and not cout_in_window:
            for r in rows:
                if r["time"] == win_end_hhmm and r["role"] in ("schedule", "schedule-end"):
                    r["role"] = "attendance-out"
                    r["attendance_time_clamped"] = True
                    break
        elif not cout_in_window:
            for r in rows:
                if r["time"] == win_end_hhmm and r["role"] in ("schedule", "schedule-end"):
                    r["role"] = "no-data-end"
                    break

    # 6) 정렬 + 동시각 정리
    def _key(r: SkeletonRow) -> tuple[int, int]:
        try:
            tm = _hhmm_to_minutes(r["time"])
        except (ValueError, KeyError):
            tm = 9999
        # 같은 시각이면 role 우선순위: attendance > photo-cluster > no-data-* > schedule-end > schedule
        priority = {
            "attendance-in": 0,
            "attendance-out": 0,
            "photo-cluster": 1,
            "no-data-start": 2,
            "no-data-end": 2,
            "schedule-end": 3,
            "schedule": 4,
        }.get(r.get("role", ""), 9)
        return (tm, priority)

    rows.sort(key=_key)

    # 같은 시각이 여러 role 로 잡혔으면 우선순위 1위(이미 sort 결과의 앞 row) 만 남긴다.
    # 흔한 케이스: clamp 로 09:00 으로 끌려온 photo-cluster 와 09:00 schedule 이 겹침 →
    # photo-cluster 만 살리고 schedule 은 흡수(라벨은 photo-cluster row 가 이미 갖고 있음).
    deduped: list[SkeletonRow] = []
    seen_times: set[str] = set()
    for r in rows:
        t = r.get("time", "")
        if t in seen_times:
            continue
        seen_times.add(t)
        deduped.append(r)

    # 윈도우-안 등하원이 있으면 timeline 을 그 시각 범위로 좁힌다:
    # - cin=09:14 → 09:00 row 는 의미 없으니 drop, 첫 row 가 09:14 attendance-in.
    # - cout=16:43 → 18:00 「데이터가 없습니다」 row 는 의미 없으니 drop, 마지막 row 가 16:43 attendance-out.
    # 등하원이 없거나 윈도우 밖이면 그대로 두어 no-data anchor 가 boundary 를 차지하게 한다.
    if cin_n and _within_window(cin_n):
        deduped = [r for r in deduped if r["time"] >= cin_n]
    if cout_n and _within_window(cout_n):
        deduped = [r for r in deduped if r["time"] <= cout_n]

    return deduped


def _slot_aware_fallback(row: SkeletonRow, topic: str, has_attendance: bool) -> str:
    """LLM 이 row 를 누락했을 때 슬롯 라벨로 의미 있는 1-2 문장 fallback 을 만든다.

    - `topic`: "정우는" 같은 호칭+주제 조사. 비어 있으면 일반 "친구들과 함께" 우회.
    - `has_attendance`: 등하원 기록이 있어 아이가 원에 있었다고 볼 수 있는지.
      True 면 단정형(…했습니다), False 면 추측형(…했을 것입니다).
    """
    slot = (row.get("slot_label") or "").strip()
    actor = topic or "친구들과 함께"

    # 각 키워드마다 (past, speculative) 문장 쌍을 둔다 — 두 시제를 합쳐 만들지 않고 직접 작성해 어법 안전.
    keyword_templates: list[tuple[str, str, str]] = [
        ("등원",
         f"{actor} 선생님·친구들과 반갑게 인사를 나누고 좋아하는 놀잇감을 골라 자유롭게 놀며 하루를 시작했습니다.",
         f"{actor} 선생님·친구들과 인사를 나누고 자유롭게 놀이하며 하루를 열어 갔을 것입니다."),
        ("자유놀이",
         f"{actor} 좋아하는 놀잇감을 직접 골라 친구들과 어울리며 자유놀이 시간을 즐겁게 보냈습니다.",
         f"{actor} 좋아하는 놀잇감을 골라 친구들과 어울리며 자유롭게 놀이했을 것입니다."),
        ("오전 간식",
         f"{actor} 오전 간식 시간에 자리에 차분히 앉아 친구들과 도란도란 이야기를 나누며 간식을 맛있게 먹었습니다.",
         f"{actor} 오전 간식 시간에 친구들과 함께 간식을 즐겁게 먹었을 것입니다."),
        ("교실 활동",
         f"{actor} 교실에서 친구들과 함께 활동에 참여하고 바깥으로 나가 몸을 움직이며 즐겁게 놀이했습니다.",
         f"{actor} 교실 활동과 바깥 놀이를 친구들과 함께 두루 즐겼을 것입니다."),
        ("바깥 놀이",
         f"{actor} 바깥에서 친구들과 신나게 뛰놀며 활동에 흠뻑 빠져 있었습니다.",
         f"{actor} 바깥에서 친구들과 신나게 어울리며 놀이했을 것입니다."),
        ("점심",
         f"{actor} 친구들과 식탁에 둘러앉아 골고루 음식을 맛있게 먹고 즐거운 점심시간을 보냈습니다.",
         f"{actor} 친구들과 함께 점심을 맛있게 먹으며 즐거운 식사 시간을 보냈을 것입니다."),
        ("낮잠",
         f"{actor} 자리를 정리하고 편안히 누워 충분한 낮잠으로 오전의 피로를 풀었습니다.",
         f"{actor} 편안한 분위기에서 낮잠을 자며 푹 쉬었을 것입니다."),
        ("휴식",
         f"{actor} 조용한 분위기에서 몸을 쉬며 마음을 차분히 가다듬는 시간을 보냈습니다.",
         f"{actor} 조용히 몸과 마음을 쉬는 시간을 보냈을 것입니다."),
        ("오후 간식",
         f"{actor} 오후 간식 시간에 친구들과 가볍게 이야기를 나누며 간식을 즐겁게 먹었습니다.",
         f"{actor} 오후 간식 시간에 친구들과 어울려 간식을 즐겁게 먹었을 것입니다."),
        ("오후 특별 활동",
         f"{actor} 오후 특별 활동에 호기심 어린 표정으로 참여하며 새로운 경험을 즐겁게 만들어 갔습니다.",
         f"{actor} 오후 특별 활동에 참여하며 새로운 경험을 즐겁게 누렸을 것입니다."),
        ("특별 활동",
         f"{actor} 특별 활동 시간에 적극적으로 참여하며 다양한 경험을 즐겁게 누렸습니다.",
         f"{actor} 특별 활동에 참여하며 다양한 경험을 만났을 것입니다."),
        ("하원",
         f"{actor} 가방과 옷을 차근차근 챙겨 하원 준비를 마치고 친구들과 인사를 나누는 시간을 보냈습니다.",
         f"{actor} 하원 준비를 마치고 친구들과 인사를 나누는 시간을 보냈을 것입니다."),
        ("통합 보육",
         f"{actor} 통합 보육 시간에 다른 반 친구들과 어울려 함께 활동하며 하루의 마무리를 보냈습니다.",
         f"{actor} 통합 보육 시간에 다른 반 친구들과 어울리며 하루를 마무리했을 것입니다."),
    ]
    for needle, past, spec in keyword_templates:
        if needle and needle in slot:
            return past if has_attendance else spec
    # 마지막 fallback: 슬롯 이름을 그대로 끼워서 살짝 풀어 쓴다.
    if slot:
        tail = "보냈습니다." if has_attendance else "보냈을 것입니다."
        return f"{actor} 「{slot}」 시간을 차분히 {tail}"
    tail = "보냈습니다." if has_attendance else "보냈을 것입니다."
    return f"{actor} 차분한 분위기 속에서 시간을 {tail}"


def enforce_skeleton_on_events(
    skeleton: list[SkeletonRow],
    llm_events: list[dict[str, Any]],
    *,
    no_data_text: str = "데이터가 없습니다",
    address_name: str = "",
    has_attendance: bool = True,
) -> list[dict[str, Any]]:
    """LLM 출력 events 를 골격에 맞춰 재정렬·검증. 골격에 없는 row 는 버리고, 누락된 row 는 채운다.

    역할별 텍스트 처리:
    - no-data-start/end: 항상 `no_data_text` 강제 (LLM 출력 무시).
    - attendance-in/out: `address_name` 기반 서버 생성 문장으로 강제 (DB 사실이라 LLM 환각 회피).
    - photo-cluster / schedule / schedule-end: LLM 출력을 photo_id → time 순으로 매칭해 채택.
      LLM 이 schedule row 에 "데이터가 없습니다" 를 잘못 써 보내면 fallback 으로 대체한다.

    매칭 우선순위 (photo-cluster / schedule):
    1. 골격의 (time, photo_id) 와 LLM event 의 (time, photo_id) 가 같으면 매칭.
    2. 사진 row 끼리는 photo_id 만 같아도 매칭 (LLM 이 time 을 바꾼 경우 흡수).
    3. 사진이 없는 row 는 time 만 같아도 매칭.
    4. 매칭 실패 시 슬롯 라벨 기반 fallback (`_slot_aware_fallback`) 으로 채움.
    """
    by_pid: dict[int, dict[str, Any]] = {}
    by_time: dict[str, dict[str, Any]] = {}
    for ev in llm_events:
        if not isinstance(ev, dict):
            continue
        t = str(ev.get("time", "")).strip()
        text = str(ev.get("text", "")).strip()
        if not t or not text:
            continue
        try:
            t_n = _canonical_hhmm(t)
        except ValueError:
            continue
        pid = ev.get("photo_id")
        if isinstance(pid, int):
            by_pid.setdefault(pid, ev)
        by_time.setdefault(t_n, ev)

    name = (address_name or "").strip()
    subject = subject_particle_phrase(name) if name else ""
    topic = topic_particle_phrase(name) if name else ""

    def _attendance_text(row: SkeletonRow, kind: str) -> str:
        """role=attendance-in/out 의 본문을 서버에서 직접 만든다 — DB 사실이라 LLM 에 맡기지 않음.

        kind: "in" → 등원, "out" → 하원.
        row 의 `attendance_time_clamped` 가 True 면 (DB 시각이 일과표 밖이라 boundary 로 끌어붙임)
        시각 표기는 생략한다 — 잘못된 시각을 노출하지 않기 위해.
        """
        verb = "등원" if kind == "in" else "하원"
        time_s = row.get("time", "")
        clamped = bool(row.get("attendance_time_clamped"))
        if clamped:
            return f"{subject} {verb}했습니다." if subject else f"{verb}했습니다."
        if subject:
            return f"{subject} {time_s}에 {verb}했습니다."
        return f"{time_s}에 {verb}했습니다."

    out: list[dict[str, Any]] = []
    for row in skeleton:
        role = row.get("role", "")
        # no-data anchor 는 LLM 이 무엇을 썼든 항상 「데이터가 없습니다」 한 문장으로 강제.
        if role in ("no-data-start", "no-data-end"):
            ev_out_nd: dict[str, Any] = {
                "time": row["time"],
                "photo_id": row.get("photo_id"),
                "text": no_data_text,
            }
            pids_nd = row.get("photo_ids") or []
            if pids_nd:
                ev_out_nd["photo_ids"] = list(pids_nd)
            out.append(ev_out_nd)
            continue
        # attendance row 도 서버 생성 문장으로 강제 — LLM 이 「오전 간식」 같은 슬롯 활동을 쓰면 사실 왜곡.
        if role in ("attendance-in", "attendance-out"):
            kind = "in" if role == "attendance-in" else "out"
            ev_out_att: dict[str, Any] = {
                "time": row["time"],
                "photo_id": row.get("photo_id"),
                "text": _attendance_text(row, kind),
            }
            pids_att = row.get("photo_ids") or []
            if pids_att:
                ev_out_att["photo_ids"] = list(pids_att)
            out.append(ev_out_att)
            continue
        text = ""
        pid = row.get("photo_id")
        if isinstance(pid, int) and pid in by_pid:
            text = str(by_pid[pid].get("text", "")).strip()
        if not text:
            t = row.get("time", "")
            if t in by_time:
                text = str(by_time[t].get("text", "")).strip()
        # 비-anchor row 에서 LLM 이 잘못 적은 "데이터가 없습니다" 는 거부 → 슬롯 기반 풀어쓰기 fallback.
        if text == no_data_text or text == no_data_text + ".":
            text = ""
        # 너무 짧은 본문은 보호자가 읽기에 빈약함 — 슬롯 기반 fallback 으로 교체.
        # 35자 미만은 「오전 간식을 먹었습니다」(11자) 류로 보고, 이 한도를 너무 올리면 멀쩡한 LLM
        # 한 문장도 잘릴 수 있으므로 보수적으로 잡는다.
        if text and len(text) < 35:
            text = ""
        if not text:
            text = _slot_aware_fallback(row, topic, has_attendance)

        ev_out: dict[str, Any] = {
            "time": row["time"],
            "photo_id": row.get("photo_id"),
            "text": text,
        }
        pids = row.get("photo_ids") or []
        if pids:
            ev_out["photo_ids"] = list(pids)
        out.append(ev_out)
    return out


def render_skeleton_for_prompt(skeleton: list[SkeletonRow]) -> str:
    """프롬프트에 넣을 텍스트 — LLM 이 보고 채우기 쉬운 한 row 한 줄 형식.

    photo-cluster row 에는 한국어로 변환된 로봇/모드/감정 메타를 같이 넣어 LLM 이 영문 id 를
    "노리아르마" 같이 음역하지 않게 한다.
    """
    if not skeleton:
        return "(빈 골격)"
    lines: list[str] = []
    for r in skeleton:
        role = r.get("role", "")
        time_s = r.get("time", "")
        label = r.get("slot_label") or "-"
        pid = r.get("photo_id")
        pids = r.get("photo_ids") or []
        if pids and len(pids) > 1:
            pid_s = f"photo_ids={pids} (대표 photo_id={pid})"
        elif pid is not None:
            pid_s = f"photo_id={pid}"
        else:
            pid_s = "photo_id=null"
        role_tag = f"[{role}]"
        line = f"  {role_tag} time={time_s} slot=「{label}」 {pid_s}"
        if role == "photo-cluster":
            robot_ko = r.get("photo_robot_ko") or ""
            mode_ko = r.get("photo_mode_ko") or ""
            emo = r.get("photo_emotion") or ""
            score = r.get("photo_score") or ""
            meta_bits = []
            if robot_ko:
                meta_bits.append(f"로봇={robot_ko}")
            if mode_ko:
                meta_bits.append(f"모드={mode_ko}")
            if emo:
                meta_bits.append(f"감정={emo}")
            if score:
                meta_bits.append(f"강도={score}")
            if meta_bits:
                line += "\n      " + ", ".join(meta_bits)
        lines.append(line)
    return "\n".join(lines)


def _minutes_to_hhmm(m: int) -> str:
    h, mm = divmod(int(m), 60)
    return f"{h:02d}:{mm:02d}"
