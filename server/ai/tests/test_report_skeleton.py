"""report_skeleton — 일과표 기반 timeline 골격 빌더 + LLM 출력 강제 정렬 테스트."""
from __future__ import annotations

import pytest

from server.ai.report_skeleton import (
    build_timeline_skeleton,
    enforce_skeleton_on_events,
)


SHARED = {
    "09:00-10:00": "등원 및 자유놀이",
    "10:00-10:30": "오전 간식",
    "10:30-12:00": "교실 활동 및 바깥 놀이",
    "12:00-13:00": "점심시간",
    "13:00-14:30": "낮잠 및 휴식",
    "14:30-15:00": "오후 간식",
    "15:00-16:00": "오후 특별 활동",
    "16:00-18:00": "하원 및 통합 보육",
}


def _times(rows):
    return [r["time"] for r in rows]


def _roles(rows):
    return [r["role"] for r in rows]


def test_skeleton_spine_covers_every_slot_plus_end() -> None:
    rows = build_timeline_skeleton(SHARED, [], {})
    # 8 슬롯 시작 + 18:00 schedule-end = 9 row 가 기본 spine
    times = _times(rows)
    assert "09:00" in times
    assert "10:00" in times
    assert "18:00" in times
    assert times == sorted(times)


def test_skeleton_inserts_attendance_when_off_slot() -> None:
    rows = build_timeline_skeleton(
        SHARED, [], {"check_in_kst": "09:14", "check_out_kst": "16:43"}
    )
    roles_at_in = [r["role"] for r in rows if r["time"] == "09:14"]
    roles_at_out = [r["role"] for r in rows if r["time"] == "16:43"]
    assert roles_at_in == ["attendance-in"]
    assert roles_at_out == ["attendance-out"]


def test_skeleton_promotes_schedule_to_attendance_when_exact_slot_start() -> None:
    # check_in 09:00 은 슬롯 시작과 동일 — 별도 row 만들지 않고 기존 schedule role 을 교체.
    rows = build_timeline_skeleton(SHARED, [], {"check_in_kst": "09:00"})
    nine_rows = [r for r in rows if r["time"] == "09:00"]
    assert len(nine_rows) == 1
    assert nine_rows[0]["role"] == "attendance-in"


def test_skeleton_clusters_photos_into_single_row() -> None:
    photos = [
        {"photo_id": 1, "time": "10:32", "robot": "noriarm", "mode": "ox-quiz", "emotion": "happy", "score": "0.7"},
        {"photo_id": 2, "time": "10:35", "robot": "noriarm", "mode": "ox-quiz", "emotion": "happy", "score": "0.9"},
        {"photo_id": 3, "time": "10:38", "robot": "noriarm", "mode": "ox-quiz", "emotion": "happy", "score": "0.6"},
    ]
    rows = build_timeline_skeleton(SHARED, photos, {})
    cluster_rows = [r for r in rows if r["role"] == "photo-cluster"]
    assert len(cluster_rows) == 1
    c = cluster_rows[0]
    assert c["time"] == "10:32"
    assert c["photo_ids"] == [1, 2, 3]
    assert c["photo_id"] == 2  # 점수 최고
    assert c["slot_label"] == "교실 활동 및 바깥 놀이"


def test_skeleton_marks_no_data_anchors_when_no_attendance_no_photos() -> None:
    rows = build_timeline_skeleton(SHARED, [], {})
    roles = _roles(rows)
    assert roles[0] == "no-data-start"
    assert roles[-1] == "no-data-end"


def test_skeleton_no_data_anchors_apply_even_when_photos_exist() -> None:
    # 새 boundary 규칙: 첫/마지막 row 는 attendance OR no-data — 사진이 있어도 attendance 가
    # 없으면 no-data anchor 가 붙는다.
    photos = [{"photo_id": 1, "time": "10:32", "robot": "noriarm", "mode": "ox-quiz", "emotion": "happy", "score": "0.9"}]
    rows = build_timeline_skeleton(SHARED, photos, {})
    assert rows[0]["role"] == "no-data-start"
    assert rows[-1]["role"] == "no-data-end"


def test_enforce_skeleton_fills_missing_text_with_slot_fallback() -> None:
    skeleton = build_timeline_skeleton(SHARED, [], {})
    # LLM 이 일부 row 만 돌려준 경우 — 나머지는 슬롯 라벨 기반 fallback 으로 채워진다.
    llm = [
        {"time": "10:00", "photo_id": None, "text": "오늘 첫 row"},
        {"time": "12:00", "photo_id": None, "text": "점심"},
    ]
    out = enforce_skeleton_on_events(skeleton, llm, address_name="정우", has_attendance=False)
    assert len(out) == len(skeleton)
    by_time = {e["time"]: e["text"] for e in out}
    # 누락된 14:30 (오후 간식) 은 slot fallback — "활동을 이어갔습니다." 이런 일반 문장이 아니라 슬롯-aware.
    afternoon = by_time["14:30"]
    assert "오후 간식" in afternoon
    assert "활동을 이어갔습니다." not in afternoon
    # 골격이 no-data-end 인 18:00 은 정확히 「데이터가 없습니다」 로.
    assert by_time["18:00"] == "데이터가 없습니다"
    # 골격이 no-data-end 인 18:00 은 정확히 「데이터가 없습니다」 로.
    assert by_time["18:00"] == "데이터가 없습니다"


def test_enforce_skeleton_drops_llm_rows_not_in_skeleton() -> None:
    skeleton = build_timeline_skeleton(SHARED, [], {"check_in_kst": "09:00", "check_out_kst": "16:00"})
    llm = [
        # 골격에 없는 11:11 row — drop 대상.
        {"time": "11:11", "photo_id": None, "text": "엉뚱한 시각 row"},
        {"time": "09:00", "photo_id": None, "text": "등원했습니다."},
    ]
    out = enforce_skeleton_on_events(skeleton, llm)
    times = [e["time"] for e in out]
    assert "11:11" not in times
    assert "09:00" in times


def test_enforce_skeleton_picks_up_text_by_photo_id_even_if_llm_changes_time() -> None:
    photos = [{"photo_id": 42, "time": "10:32", "robot": "noriarm", "mode": "ox-quiz", "emotion": "happy", "score": "0.9"}]
    skeleton = build_timeline_skeleton(SHARED, photos, {"check_in_kst": "09:00", "check_out_kst": "16:00"})
    rich = "정우는 노리암 로봇과 OX 퀴즈를 함께하며 즐겁고 활발한 표정으로 활동에 참여했습니다."
    llm = [
        {"time": "10:30", "photo_id": 42, "text": rich},  # time 살짝 다름
    ]
    out = enforce_skeleton_on_events(skeleton, llm)
    pid_row = next(e for e in out if e.get("photo_id") == 42)
    assert pid_row["text"] == rich
    assert pid_row["time"] == "10:32"  # 골격 시각으로 강제됨


def test_enforce_skeleton_preserves_photo_ids_array() -> None:
    photos = [
        {"photo_id": 1, "time": "10:32", "robot": "noriarm", "mode": "ox-quiz", "emotion": "happy", "score": "0.7"},
        {"photo_id": 2, "time": "10:35", "robot": "noriarm", "mode": "ox-quiz", "emotion": "happy", "score": "0.9"},
    ]
    skeleton = build_timeline_skeleton(SHARED, photos, {"check_in_kst": "09:00", "check_out_kst": "16:00"})
    rich = "정우는 노리암 로봇과 OX 퀴즈를 즐기며 활짝 웃는 표정을 남겼습니다."
    llm = [{"time": "10:32", "photo_id": 2, "text": rich}]
    out = enforce_skeleton_on_events(skeleton, llm)
    pid_row = next(e for e in out if isinstance(e.get("photo_id"), int))
    assert pid_row["photo_ids"] == [1, 2]


def test_skeleton_uses_shared_school_schedule(shared_school_schedule: dict[str, str]) -> None:
    # 실제 shared/school_schedule.json 으로도 빌드 가능해야 한다.
    rows = build_timeline_skeleton(shared_school_schedule, [], {})
    assert rows, "골격이 비면 안 됨"
    assert rows[0]["time"] == "09:00"


def test_skeleton_clamps_early_photo_to_morning_activity_slot() -> None:
    # 01:49 같은 새벽 사진은 등원 슬롯(09:00) 이 아닌 오전 활동 슬롯 중간으로 옮긴다.
    # SHARED 에서 첫 활동 슬롯은 10:30-12:00 → 중간 = 11:15.
    photos = [{"photo_id": 99, "time": "01:49", "robot": "noriarm", "mode": "ox-quiz", "emotion": "happy", "score": "0.9"}]
    rows = build_timeline_skeleton(SHARED, photos, {})
    cluster = next(r for r in rows if r["role"] == "photo-cluster")
    assert cluster["time"] == "11:15"
    # 첫 row 는 boundary (no-data-start) 가 차지.
    assert rows[0]["time"] == "09:00"
    assert rows[0]["role"] == "no-data-start"


def test_skeleton_clamps_late_photo_to_afternoon_activity_slot() -> None:
    # 23:50 PM 사진은 오후 활동 슬롯 중간 (15:00-16:00 → 15:30) 으로.
    photos = [{"photo_id": 7, "time": "23:50", "robot": "noriarm", "mode": "ox-quiz", "emotion": "happy", "score": "0.9"}]
    rows = build_timeline_skeleton(SHARED, photos, {})
    cluster = next(r for r in rows if r["role"] == "photo-cluster")
    assert cluster["time"] == "15:30"
    # 마지막 row 는 18:00 boundary (no-data-end) 가 차지.
    assert rows[-1]["time"] == "18:00"
    assert rows[-1]["role"] == "no-data-end"


def test_skeleton_keeps_in_range_photo_at_real_time() -> None:
    # 윈도우 안 사진은 그 시각 그대로 (점심·낮잠 슬롯이어도 옮기지 않는다).
    photos = [{"photo_id": 5, "time": "13:30", "robot": "noriarm", "mode": "ox-quiz", "emotion": "happy", "score": "0.9"}]
    rows = build_timeline_skeleton(SHARED, photos, {})
    cluster = next(r for r in rows if r["role"] == "photo-cluster")
    assert cluster["time"] == "13:30"


def test_skeleton_first_row_is_attendance_when_check_in_off_slot() -> None:
    # check-in 09:14 in-window: 09:00 boundary row 는 drop, 첫 row 는 09:14 attendance-in.
    rows = build_timeline_skeleton(SHARED, [], {"check_in_kst": "09:14"})
    assert rows[0]["time"] == "09:14"
    assert rows[0]["role"] == "attendance-in"


def test_skeleton_first_row_is_attendance_when_check_in_exact_slot_start() -> None:
    # check-in 09:00: 첫 row 는 attendance-in (dedup 으로 schedule 흡수).
    rows = build_timeline_skeleton(SHARED, [], {"check_in_kst": "09:00"})
    assert rows[0]["time"] == "09:00"
    assert rows[0]["role"] == "attendance-in"


def test_skeleton_last_row_is_attendance_when_check_out_off_slot() -> None:
    # check-out 16:43 in-window: 18:00 no-data-end 는 drop, 마지막 row 는 16:43 attendance-out.
    rows = build_timeline_skeleton(SHARED, [], {"check_out_kst": "16:43"})
    assert rows[-1]["time"] == "16:43"
    assert rows[-1]["role"] == "attendance-out"


def test_skeleton_last_row_attendance_clamped_when_check_out_outside_window() -> None:
    # check-out 20:37 (또는 00:13 같은 새벽 시각) 같이 윈도우 밖이어도 attendance row 자체는 살린다.
    rows = build_timeline_skeleton(SHARED, [], {"check_out_kst": "20:37"})
    assert rows[-1]["time"] == "18:00"
    assert rows[-1]["role"] == "attendance-out"
    assert rows[-1].get("attendance_time_clamped") is True


def test_enforce_skeleton_replaces_short_llm_text_with_slot_fallback() -> None:
    # LLM 이 「오전 간식을 먹었습니다」같은 짧은 한 줄을 보내면 슬롯 기반 풀어쓰기로 교체.
    skeleton = build_timeline_skeleton(SHARED, [], {"check_in_kst": "09:00", "check_out_kst": "16:00"})
    llm = [
        {"time": "10:00", "photo_id": None, "text": "오전 간식을 먹었습니다."},  # 12자 — 너무 짧음
    ]
    out = enforce_skeleton_on_events(skeleton, llm, address_name="정우")
    ten = next(e for e in out if e["time"] == "10:00")
    # 짧은 LLM 본문은 거부되고 슬롯 fallback 으로 대체됨 — 30자 넘는 풍부한 묘사.
    assert len(ten["text"]) >= 35
    assert "오전 간식" in ten["text"]


def test_enforce_skeleton_omits_time_for_clamped_attendance() -> None:
    # clamped attendance 의 텍스트는 시각을 생략 ("정우가 하원했습니다." 처럼).
    rows = build_timeline_skeleton(SHARED, [], {"check_out_kst": "00:13"})
    out = enforce_skeleton_on_events(rows, [], address_name="정우")
    last = out[-1]
    assert "하원" in last["text"]
    assert "정우" in last["text"]
    assert "00:13" not in last["text"]
    assert "18:00" not in last["text"]


def test_enforce_skeleton_writes_attendance_text_from_server() -> None:
    # attendance row 는 LLM 이 슬롯 활동을 써 보내도 서버 생성 문장으로 강제 교체.
    skeleton = build_timeline_skeleton(SHARED, [], {"check_in_kst": "09:00", "check_out_kst": "16:43"})
    llm = [
        {"time": "09:00", "photo_id": None, "text": "오전 간식을 먹었습니다"},   # LLM 의 잘못된 텍스트
        {"time": "16:43", "photo_id": None, "text": "오후 활동을 했습니다"},     # 마찬가지
    ]
    out = enforce_skeleton_on_events(skeleton, llm, address_name="정우")
    in_row = next(e for e in out if e["time"] == "09:00")
    out_row = next(e for e in out if e["time"] == "16:43")
    assert "등원" in in_row["text"]
    assert "정우" in in_row["text"]
    assert "하원" in out_row["text"]


def test_enforce_skeleton_rejects_llm_no_data_on_non_anchor_rows() -> None:
    # LLM 이 schedule 줄에 "데이터가 없습니다" 를 잘못 써 보내면 fallback 으로 대체.
    skeleton = build_timeline_skeleton(SHARED, [], {"check_in_kst": "09:00", "check_out_kst": "16:00"})
    llm = [
        {"time": "16:00", "photo_id": None, "text": "데이터가 없습니다"},  # 16:00 은 attendance-out 이므로 거부
        {"time": "12:00", "photo_id": None, "text": "데이터가 없습니다"},  # 12:00 은 schedule 이므로 거부 후 fallback
    ]
    out = enforce_skeleton_on_events(skeleton, llm, address_name="정우")
    twelve = next(e for e in out if e["time"] == "12:00")
    sixteen = next(e for e in out if e["time"] == "16:00")
    assert "데이터가 없습니다" not in twelve["text"]
    assert "하원" in sixteen["text"]


def test_skeleton_clamps_outside_window_attendance_to_boundary() -> None:
    # 20:32/20:37 같은 윈도우 밖 등하원은 row 자체를 drop 하지 않고, boundary(09:00/18:00) 에
    # attendance row 를 박되 `attendance_time_clamped=True` 로 표시해 시각 노출은 막는다.
    rows = build_timeline_skeleton(SHARED, [], {"check_in_kst": "20:32", "check_out_kst": "20:37"})
    first = rows[0]
    last = rows[-1]
    assert first["time"] == "09:00"
    assert first["role"] == "attendance-in"
    assert first.get("attendance_time_clamped") is True
    assert last["time"] == "18:00"
    assert last["role"] == "attendance-out"
    assert last.get("attendance_time_clamped") is True


def test_skeleton_keeps_attendance_inside_window() -> None:
    rows = build_timeline_skeleton(SHARED, [], {"check_in_kst": "09:14", "check_out_kst": "16:43"})
    times_in = [r["time"] for r in rows if r["role"] == "attendance-in"]
    times_out = [r["time"] for r in rows if r["role"] == "attendance-out"]
    assert times_in == ["09:14"]
    assert times_out == ["16:43"]
