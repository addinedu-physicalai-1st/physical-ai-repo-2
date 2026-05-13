"""보고서 한국어 후처리 (소유격 교정)."""

import json

from server.ai.korean_postprocess import (
    CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT,
    augment_summary_with_child_notes,
    collapse_legacy_class_scope_disclaimer,
    collapse_redundant_class_scope_participation_prefixes,
    merge_same_session_photo_clusters_to_single_rows,
    dedupe_timeline_near_duplicate_texts,
    ensure_canonical_photo_rows,
    fill_timeline_schedule_gaps,
    fix_common_report_korean_typos,
    fix_truncated_class_name_ideul,
    fix_class_name_as_timeline_subject,
    fix_address_name_hangul_near_miss,
    fix_garbled_first_syllable_name_particle,
    fix_expression_record_possessive_phrase,
    fix_timeline_child_focus_events,
    fix_missing_subject_josa_after_name,
    fix_name_gwa_different_children_glitch,
    fix_possessive_name_glitch,
    fix_report_time_josa_artifacts,
    fix_stacked_josa_glitch,
    fix_subject_josa_glitch,
    fix_wrong_josa_particle_pair,
    merge_attendance_timeline_events,
    merge_final_schedule_slot_timeline_rows,
    ensure_class_scope_timeline_end_no_data_row,
    normalize_class_scope_dismissal_slots_to_no_data,
    repair_extraneous_class_scope_no_data_rows,
    normalize_report_subject_openers_to_topic,
    object_particle_phrase,
    polish_report_json_content,
    polish_report_korean_josa,
    formalize_parent_facing_report_korean,
    report_address_name,
    retain_top_k_photo_timeline,
    sanitize_photo_event_placements,
    scrub_llm_emotion_score_and_paren_tags,
    scrub_participation_disclaimer_attendance_verbs,
    scrub_registered_name_in_report_text,
    scrub_expression_meta_without_photos,
    scrub_unrecorded_arrival_departure_claims,
    slot_label_for_schedule_time,
    soften_dismissal_no_data_when_intraday_narrative_in_slot,
    strip_cjk_ideographs_from_report_text,
    strip_photo_capture_heading_echo,
    subject_particle_phrase,
    topic_particle_phrase,
    use_dismissal_no_data_anchor_cleanup,
    use_class_scope_timeline,
    ensure_class_scope_attendance_disclaimer,
    rewrite_class_collective_subject_to_child,
    rewrite_class_scope_timeline_child_topic,
    strip_lunch_menu_from_non_lunch_events,
    remove_timeline_raw_emotion_dump_lines,
)
from server.ai.llm import _schedule_prompt_block


def test_remove_timeline_raw_emotion_dump_lines_drops_prompt_echo() -> None:
    ev = [
        {"time": "10:30", "photo_id": None, "text": "happy (강도 1.00)의 표정을 지었습니다."},
        {"time": "10:31", "photo_id": None, "text": "Sad (강도 0.5) 표정을 지었다."},
        {"time": "12:00", "photo_id": None, "text": "점심을 먹었습니다."},
    ]
    out = remove_timeline_raw_emotion_dump_lines(ev)
    assert len(out) == 1
    assert out[0]["time"] == "12:00"


def test_polish_report_json_content_strips_raw_emotion_dump_lines() -> None:
    raw = json.dumps(
        {
            "events": [
                {"time": "10:30", "photo_id": None, "text": "happy (강도 1.00)의 표정을 지었습니다"},
                {"time": "12:00", "photo_id": None, "text": "점심이었습니다"},
            ],
            "summary": "요약.",
        },
        ensure_ascii=False,
    )
    out = polish_report_json_content(raw, "정우", None, class_name="햇님반")
    data = json.loads(out)
    assert len(data["events"]) == 1
    assert data["events"][0]["time"] == "12:00"


def test_fix_possessive_name_glitch_이의() -> None:
    s = "박우림이의 일상은 활동적이었습니다."
    assert fix_possessive_name_glitch("박우림", s) == "박우림의 일상은 활동적이었습니다."
    s = "민주가의 하루는 즐거웠습니다."
    assert fix_possessive_name_glitch("민주", s) == "민주의 하루는 즐거웠습니다."


def test_fix_possessive_name_glitch_noop() -> None:
    s = "박우림의 일상은 괜찮았습니다."
    assert fix_possessive_name_glitch("박우림", s) == s


def test_fix_possessive_name_glitch_all_occurrences() -> None:
    s = "A이의 낮, A이의 저녁"
    assert fix_possessive_name_glitch("A", s) == "A의 낮, A의 저녁"


def test_schedule_prompt_block_lists_slots() -> None:
    sched = {"09:00-10:00": "등원 및 자유놀이", "12:00-13:00": "점심시간"}
    out = _schedule_prompt_block(sched)
    assert "09:00-10:00" in out and "등원 및 자유놀이" in out
    assert "점심시간" in out


def test_schedule_prompt_block_empty() -> None:
    out = _schedule_prompt_block(None)
    assert "불러오지" in out


def test_report_address_name_three_syllables() -> None:
    assert report_address_name("박우림") == "우림"


def test_report_address_name_two_syllables_kept() -> None:
    assert report_address_name("지수") == "지수"


def test_scrub_registered_name_in_report_text() -> None:
    s = "박우림의 하루는 즐거웠다."
    assert scrub_registered_name_in_report_text(s, "박우림", "우림") == "우림의 하루는 즐거웠다."


def test_subject_particle_phrase_batchim() -> None:
    assert subject_particle_phrase("민성") == "민성이"


def test_subject_particle_phrase_no_batchim() -> None:
    assert subject_particle_phrase("민주") == "민주가"


def test_fix_wrong_josa_particle_pair_subject() -> None:
    assert fix_wrong_josa_particle_pair("우림", "우림가 등원했다.") == "우림이 등원했다."


def test_fix_wrong_josa_particle_pair_topic() -> None:
    assert fix_wrong_josa_particle_pair("우림", "우림는 즐거웠다.") == "우림은 즐거웠다."


def test_fix_wrong_josa_particle_pair_no_batchim() -> None:
    assert fix_wrong_josa_particle_pair("민주", "민주이 왔다.") == "민주가 왔다."


def test_fix_report_time_josa_artifacts() -> None:
    assert fix_report_time_josa_artifacts("점심시간은 지나 휴식") == "점심시간이 지나 휴식"


def test_fix_report_time_josa_artifacts_jinaha_glitch() -> None:
    assert (
        fix_report_time_josa_artifacts("민성은 점심시간을 지나했다.")
        == "민성은 점심시간을 지냈다."
    )


def test_fix_report_time_josa_artifacts_iga_jinaha_glitch() -> None:
    assert (
        fix_report_time_josa_artifacts("우림은 참여 미확인. 「햇님반」 일과로 점심시간이 지나했다.")
        == "우림은 참여 미확인. 「햇님반」 일과로 점심시간을 지냈다."
    )


def test_collapse_legacy_class_scope_disclaimer() -> None:
    long_ = (
        "오늘 DB 에 우림의 등원·하원 시각이 없어 … "
        "개별 출석·참여 여부는 DB 만으로는 판단할 수 없다. … "
        "이 아이의 실제 참여와 같다고 볼 수 없다."
    )
    assert collapse_legacy_class_scope_disclaimer(long_) == CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT
    assert collapse_legacy_class_scope_disclaimer("민성은 놀았다.") == "민성은 놀았다."


def test_collapse_legacy_class_scope_disclaimer_haewon_block() -> None:
    old = (
        "민성은 개별 하원·참여는 DB에 없어 확인할 수 없다. 일과표상 … "
        "(※ 보고 대상 아이의 실제 하원·참여와 같다고 볼 수 없다.)"
    )
    assert collapse_legacy_class_scope_disclaimer(old) == CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT
    old2 = (
        "민성은 개별 하원은 DB에 없다. 일과표 「하원 및 통합 보육」… "
        "(※ 실제 하원·참여와 같다고 볼 수 없다.)"
    )
    assert collapse_legacy_class_scope_disclaimer(old2) == CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT


def test_fix_name_gwa_different_children_glitch() -> None:
    s = "민성과 다른 아이들과 자유놀이를 했다."
    assert fix_name_gwa_different_children_glitch("민성", s) == "민성이 다른 아이들과 자유놀이를 했다."


def test_merge_attendance_timeline_inserts_row() -> None:
    sched = {"09:00-10:00": "등원 및 자유놀이"}
    ev = [{"time": "10:00", "photo_id": None, "text": "간식."}]
    out = merge_attendance_timeline_events(
        ev,
        "영주",
        {"check_in_kst": "09:05", "check_out_kst": None},
        sched,
    )
    assert any(e["time"] == "09:05" and "영주" in e["text"] and "등원" in e["text"] for e in out)


def test_merge_attendance_timeline_prefixes_same_time() -> None:
    ev = [{"time": "09:00", "photo_id": None, "text": "햇님반 아이들과 뛰어놀기."}]
    out = merge_attendance_timeline_events(
        ev,
        "영주",
        {"check_in_kst": "09:00", "check_out_kst": None},
        {"09:00-10:00": "등원 및 자유놀이"},
    )
    row = next(e for e in out if e["time"] == "09:00" and e.get("photo_id") is None)
    assert "영주" in row["text"] and "등원" in row["text"]


def test_slot_label_for_schedule_time() -> None:
    s = {"09:00-10:00": "등원 및 자유놀이", "10:00-10:30": "오전 간식"}
    assert slot_label_for_schedule_time(s, "09:30") == "등원 및 자유놀이"
    assert slot_label_for_schedule_time(s, "10:00") == "오전 간식"


def test_fix_subject_josa_glitch_이가() -> None:
    s = "민성이가 오전 간식 때 친구들과 놀았습니다."
    assert fix_subject_josa_glitch("민성", s) == "민성이 오전 간식 때 친구들과 놀았습니다."


def test_fix_subject_josa_glitch_ui_friends() -> None:
    s = "오전에 민성의 친구들과 함께 놀았습니다."
    assert fix_subject_josa_glitch("민성", s) == "오전에 민성이 친구들과 함께 놀았습니다."


def test_topic_and_object_particle_phrase() -> None:
    assert topic_particle_phrase("민성") == "민성은"
    assert topic_particle_phrase("민주") == "민주는"
    assert object_particle_phrase("민성") == "민성을"
    assert object_particle_phrase("민주") == "민주를"


def test_fix_missing_subject_josa_after_name() -> None:
    s = "오전에 민성 참여했습니다."
    assert fix_missing_subject_josa_after_name("민성", s) == "오전에 민성이 참여했습니다."


def test_strip_photo_capture_heading_echo_removes_similarity_boilerplate() -> None:
    raw = "정우의 감정은 오늘 포착된 표정과 유사했다."
    assert "포착" not in strip_photo_capture_heading_echo(raw)


def test_strip_photo_capture_heading_echo_removes_happiest_phrase() -> None:
    raw = "정우는 오늘 포착된 표정에서 가장 행복해 보였으며 간식을 먹었다."
    out = strip_photo_capture_heading_echo(raw)
    assert "포착" not in out
    assert "간식" in out


def test_strip_photo_capture_heading_echo_removes_leading_section_title() -> None:
    raw = "**오늘 포착된 표정:** 영주는 친구들과 함께 놀이터에서 뛰어놀았습니다."
    out = strip_photo_capture_heading_echo(raw)
    assert "포착" not in out
    assert "영주" in out
    assert "뛰어놀았" in out


def test_scrub_expression_meta_without_photos_strips_heading_and_expression_tail() -> None:
    raw = (
        "오늘 포착된 표정: 영주는 친구들과 함께 놀이터에서 뛰어놀았습니다. "
        "행복한 표정을 지었습니다."
    )
    out = scrub_expression_meta_without_photos(raw)
    assert "포착" not in out
    assert "행복한 표정" not in out
    assert "뛰어놀았" in out


def test_scrub_expression_meta_without_photos_removes_recorded_expression_phrase() -> None:
    raw = "영주의 표정이 기록되었습니다 (happy, ox-quiz). 놀이를 했습니다."
    out = scrub_expression_meta_without_photos(raw)
    assert "기록되었" not in out
    assert "놀이" in out


def test_polish_report_korean_josa_chain() -> None:
    s = "민성이의 날에 민성 참여하고 민성의 친구들과"
    assert polish_report_korean_josa("민성", s) == "민성의 날에 민성이 참여하고 민성이 친구들과"


def test_fix_garbled_first_syllable_name_particle_myig_eun() -> None:
    s = "점심시간이 지나 믞은 점심을 먹었다"
    assert fix_garbled_first_syllable_name_particle("민성", s) == "점심시간이 지나 민성은 점심을 먹었다"


def test_fix_garbled_first_syllable_name_particle_noop_same_first_char() -> None:
    """첫 글자가 맞으면 한 글자 이름과 구분 불가 — 건드리지 않음."""
    s = "민은 간식을 먹었다"
    assert fix_garbled_first_syllable_name_particle("민성", s) == s


def test_polish_report_korean_josa_chain_includes_myig_fix() -> None:
    s = polish_report_korean_josa("민성", "점심시간이 지나 믞은 점심을 먹었다")
    assert "민성은" in s
    assert "믞" not in s


def test_fix_address_name_hangul_near_miss_mue_seong() -> None:
    s = "점심시간이 지나 므성은 햇님반 친구들과 놀이를 했다."
    assert fix_address_name_hangul_near_miss("민성", s) == "점심시간이 지나 민성은 햇님반 친구들과 놀이를 했다."


def test_fix_address_name_hangul_near_miss_skips_inside_hyojeongeuro() -> None:
    """「표정으로」안의 「정으」를 호칭「정우」근접 오타로 바꾸지 않음(표정우로 방지)."""
    s = "정우는 행복한 표정으로 마무리했습니다."
    assert fix_address_name_hangul_near_miss("정우", s) == s


def test_normalize_report_subject_openers_to_topic() -> None:
    assert normalize_report_subject_openers_to_topic("민성", "민성이 간식을 먹었다.") == "민성은 간식을 먹었다."
    two = "민성이 앉았다. 민성이 일어났다."
    assert normalize_report_subject_openers_to_topic("민성", two) == "민성은 앉았다. 민성은 일어났다."


def test_fix_stacked_josa_glitch_이는() -> None:
    assert fix_stacked_josa_glitch("민성", "민성이는 점심을 먹었다.") == "민성은 점심을 먹었다."


def test_fix_stacked_josa_glitch_가는() -> None:
    assert fix_stacked_josa_glitch("민주", "민주가는 놀았다.") == "민주는 놀았다."


def test_fix_stacked_josa_glitch_이을() -> None:
    assert fix_stacked_josa_glitch("민성", "민성이을 선생님이 불렀다.") == "민성을 선생님이 불렀다."


def test_strip_cjk_ideographs_from_report_text() -> None:
    s = "우림이 낮잠을 자며 详 안온하게 쉬었습니다."
    assert strip_cjk_ideographs_from_report_text(s) == "우림이 낮잠을 자며 안온하게 쉬었습니다."


def test_polish_report_strips_cjk() -> None:
    assert "详" not in polish_report_korean_josa("우림", "우림이 详하게 쉼")


def test_sanitize_photo_event_placements_wrong_time_strips_photo() -> None:
    pe = [{"photo_id": 1, "time": "11:04", "robot": "n", "mode": "ox", "emotion": "happy", "score": "0.9"}]
    ev = [
        {"time": "11:04", "photo_id": 1, "text": "촬영"},
        {"time": "13:00", "photo_id": 1, "text": "점심인데 사진 붙음"},
    ]
    out = sanitize_photo_event_placements(ev, pe)
    assert out[0]["photo_id"] == 1
    assert out[1]["photo_id"] is None


def test_sanitize_photo_event_placements_duplicate_canonical_keeps_first() -> None:
    pe = [{"photo_id": 2, "time": "10:30", "robot": "n", "mode": "m", "emotion": "a", "score": "1"}]
    ev = [
        {"time": "10:30", "photo_id": 2, "text": "첫"},
        {"time": "10:30", "photo_id": 2, "text": "둘"},
    ]
    out = sanitize_photo_event_placements(ev, pe)
    assert out[0]["photo_id"] == 2
    assert out[1]["photo_id"] is None


def test_ensure_canonical_photo_rows_inserts_missing() -> None:
    pe = [{"photo_id": 3, "time": "10:42", "robot": "r", "mode": "ox-quiz", "emotion": "happy", "score": "1"}]
    ev = [{"time": "09:00", "photo_id": None, "text": "등원"}]
    out = ensure_canonical_photo_rows(ev, pe, "정우")
    assert len(out) == 2
    row = next(e for e in out if e.get("photo_id") == 3)
    assert row["time"] == "10:42"
    assert "정우의" in row["text"]
    assert "OX 퀴즈" in row["text"]
    assert "happy" not in row["text"].lower()


def test_retain_top_k_photo_timeline_keeps_highest_score() -> None:
    pe = [
        {"photo_id": 10, "time": "10:00", "robot": "n", "mode": "m", "emotion": "a", "score": "0.5"},
        {"photo_id": 11, "time": "11:00", "robot": "n", "mode": "m", "emotion": "b", "score": "0.99"},
    ]
    ev = [
        {"time": "10:00", "photo_id": 10, "text": "a"},
        {"time": "11:00", "photo_id": 11, "text": "b"},
    ]
    out = retain_top_k_photo_timeline(ev, pe, k=1)
    assert sum(1 for e in out if e.get("photo_id") is not None) == 1
    assert next(e for e in out if e.get("photo_id") is not None)["photo_id"] == 11


def test_fix_expression_record_possessive_phrase() -> None:
    assert fix_expression_record_possessive_phrase("정우", "정우가 표정이 기록되었다.") == "정우의 표정이 기록되었다."


def test_dedupe_timeline_near_duplicate_texts_keeps_photo_row() -> None:
    dup = "정우의 표정이 기록되었다 (happy, ox-quiz)."
    ev = [
        {"time": "10:42", "photo_id": 1, "text": dup},
        {"time": "10:47", "photo_id": None, "text": dup},
    ]
    out = dedupe_timeline_near_duplicate_texts(ev)
    assert len(out) == 1
    assert out[0]["time"] == "10:42" and out[0]["photo_id"] == 1


def test_merge_photo_clusters_combines_session_start_end_and_duration() -> None:
    pe = [
        {"photo_id": 1, "time": "10:42", "robot": "noriarm", "mode": "ox-quiz", "emotion": "happy", "score": "1"},
        {"photo_id": 2, "time": "11:04", "robot": "noriarm", "mode": "ox-quiz", "emotion": "happy", "score": "0.82"},
    ]
    ev = [
        {"time": "10:42", "photo_id": 1, "text": "시작"},
        {"time": "11:04", "photo_id": None, "text": "정우는 ox-quiz를 하며 행복하다."},
    ]
    out = merge_same_session_photo_clusters_to_single_rows(ev, pe, "정우")
    row = next(e for e in out if e["time"] == "10:42" and e.get("photo_id") == 1)
    assert "10:42" in row["text"] and "11:04" in row["text"]
    assert "22" in row["text"] or "분" in row["text"]
    assert "OX 퀴즈" in row["text"]
    assert "마무리" in row["text"] or "마치" in row["text"]


def test_merge_photo_clusters_strips_ox_spam_outside_photo_window() -> None:
    pe = [
        {"photo_id": 1, "time": "10:47", "robot": "n", "mode": "ox-quiz", "emotion": "happy", "score": "0.5"},
        {"photo_id": 2, "time": "11:04", "robot": "n", "mode": "ox-quiz", "emotion": "happy", "score": "0.99"},
    ]
    ev = [
        {"time": "10:47", "photo_id": 1, "text": "정우의 표정이 기록되었다 (happy, ox-quiz)."},
        {"time": "12:00", "photo_id": None, "text": "정우는 ox-quiz를 하며 행복하게 웃었다."},
        {"time": "14:00", "photo_id": None, "text": "정우는 OX 퀴즈를 하며 매우 행복하게 웃었다."},
        {"time": "15:00", "photo_id": None, "text": "정우는 점심을 먹었다."},
    ]
    out = merge_same_session_photo_clusters_to_single_rows(ev, pe, "정우")
    assert len([e for e in out if "ox-quiz" in e["text"].lower() or "OX 퀴즈" in e["text"]]) == 1
    assert any(e["time"] == "15:00" for e in out)
    assert sum(1 for e in out if e.get("photo_id") is not None) == 1


def test_fill_timeline_schedule_gaps_covers_shared_schedule(shared_school_schedule: dict[str, str]) -> None:
    ev = [{"time": "09:15", "photo_id": None, "text": "등원 후 놀이."}]
    out = fill_timeline_schedule_gaps(ev, shared_school_schedule, "정우")
    assert len(out) == len(shared_school_schedule)
    times = {e["time"] for e in out}
    assert "12:00" in times and "13:00" in times
    lunch = next(e for e in out if e["time"] == "12:00")
    assert "점심" in lunch["text"]


def test_fill_timeline_schedule_gaps_lunch_uses_menu(shared_school_schedule: dict[str, str]) -> None:
    key = "12:00-13:00"
    assert key in shared_school_schedule
    sched = {key: shared_school_schedule[key]}
    ev: list[dict] = []
    out = fill_timeline_schedule_gaps(ev, sched, "우림", menu_items=["김밥", "국"])
    assert len(out) == 1
    assert "김밥" in out[0]["text"]


def test_fill_timeline_schedule_gaps_skips_blank_activity_label() -> None:
    sched = {"11:00-12:00": ""}
    out = fill_timeline_schedule_gaps([], sched, "정우")
    assert out == []


def test_fill_timeline_schedule_gaps_snack_line_not_shell_template() -> None:
    out = fill_timeline_schedule_gaps([], {"10:00-10:30": "오전 간식"}, "민주")
    assert len(out) == 1
    assert "활동을 했다" not in out[0]["text"]
    assert "간식" in out[0]["text"]


def test_augment_summary_with_child_notes_appends_when_short() -> None:
    s = augment_summary_with_child_notes(
        "햇님반 정우는 하루 전체를 보냈습니다.",
        "낯가림이 심하다. 그러나 게임 시간에는 말이 많아진다.",
        "정우",
        "햇님반",
    )
    assert "「" not in s and "」" not in s
    assert "한편" in s and "모습" in s and "보였습니다" in s
    assert "쪽과" not in s and "번갈아" not in s


def test_augment_summary_with_child_notes_single_line_no_brackets() -> None:
    s = augment_summary_with_child_notes(
        "짧은 요약.",
        "간식을 잘 챙겨 먹는 편이다",
        "우림",
        "",
    )
    assert "「" not in s
    assert "우림" in s
    assert "메모에 적힌" not in s
    assert "엿보인" in s or "간식" in s


def test_fix_timeline_child_focus_events_rewrites_class_arrival_when_checked_in() -> None:
    sched = {"09:00-10:00": "등원 및 자유놀이"}
    ev = [{"time": "09:00", "photo_id": None, "text": "반 이름 햇님반 아이들은 등원했다."}]
    out = fix_timeline_child_focus_events(
        ev,
        "정우",
        "햇님반",
        sched,
        attendance={"check_in_kst": "09:00", "check_out_kst": None},
    )
    assert "정우" in out[0]["text"]
    assert "아이들은 등원" not in out[0]["text"]
    assert "반 이름" not in out[0]["text"]
    assert "등원해" in out[0]["text"] or "등원했다" in out[0]["text"]


def test_fix_timeline_child_focus_events_no_false_arrival_without_check_in() -> None:
    sched = {"09:00-10:00": "등원 및 자유놀이"}
    ev = [{"time": "09:00", "photo_id": None, "text": "반 이름 햇님반 아이들은 등원했다."}]
    out = fix_timeline_child_focus_events(
        ev,
        "영주",
        "햇님반",
        sched,
        attendance={"check_in_kst": None, "check_out_kst": None},
    )
    assert "영주" in out[0]["text"]
    assert "등원해" not in out[0]["text"] and "등원했다" not in out[0]["text"]
    assert "등원 기록이 없" in out[0]["text"]


def test_scrub_unrecorded_arrival_rewrites_direct_llm_line() -> None:
    sched = {"09:00-10:00": "등원 및 자유놀이"}
    ev = [{"time": "09:00", "photo_id": None, "text": "영주가 등원해 「등원 및 자유놀이」를 시작했다."}]
    out = scrub_unrecorded_arrival_departure_claims(
        ev,
        "영주",
        {"check_in_kst": None, "check_out_kst": None},
        sched,
    )
    assert "등원해" not in out[0]["text"]
    assert "등원 기록이 없" in out[0]["text"]


def test_fill_timeline_schedule_gaps_first_slot_no_check_in_skips_arrival_phrase() -> None:
    sched = {"09:00-10:00": "등원 및 자유놀이"}
    out = fill_timeline_schedule_gaps(
        [],
        sched,
        "영주",
        attendance={"check_in_kst": None, "check_out_kst": None},
    )
    assert len(out) == 1
    assert "등원한 뒤" not in out[0]["text"]


def test_scrub_replaces_no_checkin_boilerplate_when_photos_infer_presence() -> None:
    sched = {"09:00-10:00": "등원 및 자유놀이"}
    ev = [
        {
            "time": "09:00",
            "photo_id": None,
            "text": (
                "정우가 오늘 등원 기록이 없어 개별 출석은 단정할 수 없다. "
                "같은 시간대 반 일과는 「등원 및 자유놀이」에 맞춰 진행되었다."
            ),
        },
    ]
    out = scrub_unrecorded_arrival_departure_claims(
        ev,
        "정우",
        {"check_in_kst": None, "check_out_kst": None},
        sched,
        infer_presence_from_photos=True,
    )
    assert "등원 기록이 없" not in out[0]["text"]
    assert "등원해" in out[0]["text"]


def test_fix_timeline_photos_infer_presence_without_db_check_in() -> None:
    sched = {"09:00-10:00": "등원 및 자유놀이"}
    ev = [{"time": "09:00", "photo_id": None, "text": "햇님반 아이들은 등원했다."}]
    out = fix_timeline_child_focus_events(
        ev,
        "정우",
        "햇님반",
        sched,
        attendance={"check_in_kst": None, "check_out_kst": None},
        infer_presence_from_photos=True,
    )
    assert "등원 기록이 없" not in out[0]["text"]
    assert "등원해" in out[0]["text"]


def test_fill_first_slot_infer_presence_from_photos_uses_arrival_filler() -> None:
    sched = {"09:00-10:00": "등원 및 자유놀이"}
    out = fill_timeline_schedule_gaps(
        [],
        sched,
        "정우",
        attendance={"check_in_kst": None, "check_out_kst": None},
        infer_presence_from_photos=True,
    )
    assert len(out) == 1
    assert "등원한 뒤" in out[0]["text"]


def test_scrub_unrecorded_dismissal_rewrites_when_no_check_out() -> None:
    sched = {"16:00-18:00": "하원 및 통합 보육"}
    ev = [{"time": "16:00", "photo_id": None, "text": "영주가 하원했다."}]
    out = scrub_unrecorded_arrival_departure_claims(
        ev,
        "영주",
        {"check_in_kst": "09:00", "check_out_kst": None},
        sched,
    )
    assert "하원했다" not in out[0]["text"]
    assert "하원 기록이 아직 없" in out[0]["text"]


def test_scrub_group_dismissal_line_when_no_check_out() -> None:
    sched = {"16:00-18:00": "하원 및 통합 보육"}
    ev = [{"time": "18:00", "photo_id": None, "text": "햇님반 아이들은 하원했다."}]
    out = scrub_unrecorded_arrival_departure_claims(
        ev,
        "민성",
        {"check_in_kst": None, "check_out_kst": None},
        sched,
    )
    assert "아이들은 하원" not in out[0]["text"]
    assert "하원했다" not in out[0]["text"]
    assert "하원 기록이 아직 없" in out[0]["text"]
    assert "「하원 및 통합 보육」" in out[0]["text"]
    assert "민성" in out[0]["text"]


def test_fix_timeline_group_dismissal_when_no_check_out() -> None:
    sched = {"16:00-18:00": "하원 및 통합 보육"}
    ev = [{"time": "18:00", "photo_id": None, "text": "햇님반 아이들은 하원했다."}]
    out = fix_timeline_child_focus_events(
        ev,
        "민성",
        "햇님반",
        sched,
        attendance={"check_in_kst": "09:00", "check_out_kst": None},
    )
    assert "하원 기록이 아직 없" in out[0]["text"]
    assert "민성" in out[0]["text"]


def test_fill_haewn_slot_no_check_out_uses_record_template() -> None:
    sched = {"16:00-18:00": "하원 및 통합 보육"}
    out = fill_timeline_schedule_gaps(
        [],
        sched,
        "민성",
        attendance={"check_in_kst": "09:00", "check_out_kst": None},
    )
    assert len(out) == 1
    assert "하원 기록이 아직 없" in out[0]["text"]
    assert "「하원 및 통합 보육」" in out[0]["text"]


def test_use_class_scope_timeline_when_individual_attendance_missing() -> None:
    att = {"check_in_kst": None, "check_out_kst": None}
    assert use_class_scope_timeline(att, infer_presence_from_photos=False) is True
    assert use_class_scope_timeline(att, infer_presence_from_photos=True) is False
    assert (
        use_class_scope_timeline(
            {"check_in_kst": "09:00", "check_out_kst": None},
            infer_presence_from_photos=False,
        )
        is False
    )


def test_use_dismissal_no_data_anchor_cleanup_without_db_attendance_even_if_photos() -> None:
    att = {"check_in_kst": None, "check_out_kst": None}
    assert use_dismissal_no_data_anchor_cleanup(att) is True
    assert use_dismissal_no_data_anchor_cleanup({"check_in_kst": "09:00", "check_out_kst": None}) is False


def test_fill_timeline_class_scope_leads_with_child_topic() -> None:
    sched = {"12:00-13:00": "점심시간"}
    out = fill_timeline_schedule_gaps(
        [],
        sched,
        "영주",
        attendance={"check_in_kst": None, "check_out_kst": None},
        class_scope=True,
        class_name="햇님반",
    )
    assert len(out) == 1
    assert "영주" in out[0]["text"]
    assert "「햇님반」" in out[0]["text"]
    assert "일과표" in out[0]["text"]
    assert "햇님반 아이들은" not in out[0]["text"]


def test_fix_timeline_class_scope_disclaimer_covers_both_in_out() -> None:
    sched = {"09:00-10:00": "등원 및 자유놀이"}
    ev = [{"time": "09:00", "photo_id": None, "text": "햇님반 아이들은 등원했다."}]
    out = fix_timeline_child_focus_events(
        ev,
        "영주",
        "햇님반",
        sched,
        attendance={"check_in_kst": None, "check_out_kst": None},
        infer_presence_from_photos=False,
        class_scope=True,
    )
    assert out[0]["text"] == CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT


def test_scrub_group_dismissal_class_scope_child_fronted() -> None:
    sched = {"16:00-18:00": "하원 및 통합 보육"}
    ev = [{"time": "18:00", "photo_id": None, "text": "햇님반 아이들은 하원했다."}]
    out = scrub_unrecorded_arrival_departure_claims(
        ev,
        "영주",
        {"check_in_kst": None, "check_out_kst": None},
        sched,
        class_scope=True,
        class_name="햇님반",
    )
    assert out[0]["text"] == CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT
    assert "햇님반 아이들은" not in out[0]["text"]


def test_fill_haewon_slot_class_scope_no_check_out_short_line() -> None:
    sched = {"16:00-18:00": "하원 및 통합 보육"}
    out = fill_timeline_schedule_gaps(
        [],
        sched,
        "민성",
        attendance={"check_in_kst": None, "check_out_kst": None},
        class_scope=True,
        class_name="햇님반",
    )
    assert len(out) == 1
    assert out[0]["text"] == CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT


def test_rewrite_class_scope_timeline_child_topic_rewrites_llm_class_line() -> None:
    ev = [{"time": "10:00", "photo_id": None, "text": "햇님반 아이들은 오전 간식을 먹었다."}]
    out = rewrite_class_scope_timeline_child_topic(ev, "영주", "햇님반", class_scope=True)
    assert "영주" in out[0]["text"]
    assert "참여 미확인" in out[0]["text"]
    assert "햇님반 아이들은" not in out[0]["text"]


def test_rewrite_class_scope_timeline_rewrites_when_not_class_scope() -> None:
    ev = [{"time": "10:00", "photo_id": None, "text": "햇님반 아이들은 오전 간식을 먹었다."}]
    out = rewrite_class_scope_timeline_child_topic(ev, "영주", "햇님반", class_scope=False)
    assert "영주" in out[0]["text"]
    assert "참여 미확인" not in out[0]["text"]
    assert "햇님반 아이들은" not in out[0]["text"]


def test_rewrite_class_collective_subject_아이들이_line_start() -> None:
    s = rewrite_class_collective_subject_to_child(
        "햇님반 아이들이 오전 간식을 먹었다.",
        "민성",
        "햇님반",
        class_scope=True,
    )
    assert "민성" in s
    assert "참여 미확인" in s
    assert "햇님반 아이들" not in s


def test_rewrite_class_collective_subject_comma_second_clause() -> None:
    s = rewrite_class_collective_subject_to_child(
        "정우는 낮잠을 잤고, 햇님반 아이들은 휴식을 했다.",
        "정우",
        "햇님반",
        class_scope=False,
    )
    assert "햇님반 아이들은" not in s
    assert "정우는" in s


def test_rewrite_class_collective_subject_에서는_아이들이() -> None:
    s = rewrite_class_collective_subject_to_child(
        "햇님반에서는 아이들이 교실 활동을 했다.",
        "영주",
        "햇님반",
        class_scope=True,
    )
    assert "에서는 아이들" not in s
    assert "「햇님반」 반에서" in s


def test_rewrite_class_collective_preserves_아이들과_object() -> None:
    s = rewrite_class_collective_subject_to_child(
        "정우는 햇님반 아이들과 함께 블록을 쌓았다.",
        "정우",
        "햇님반",
        class_scope=False,
    )
    assert "햇님반 아이들과" in s


def test_ensure_class_scope_disclaimer_sets_first_slot_when_missing() -> None:
    sched = {"09:00-10:00": "등원 및 자유놀이", "10:00-10:30": "오전 간식"}
    ev = [
        {
            "time": "09:00",
            "photo_id": None,
            "text": "햇님반에서는 아이들이 자유롭게 놀았다.",
        },
    ]
    out = ensure_class_scope_attendance_disclaimer(
        ev,
        sched,
        "영주",
        "햇님반",
        attendance={"check_in_kst": None, "check_out_kst": None},
        infer_presence_from_photos=False,
    )
    assert len(out) == 1
    assert out[0]["text"] == CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT


def test_ensure_class_scope_inserts_row_if_first_slot_missing() -> None:
    sched = {"09:00-10:00": "등원 및 자유놀이"}
    ev = [{"time": "10:30", "photo_id": None, "text": "다른 줄."}]
    out = ensure_class_scope_attendance_disclaimer(
        ev,
        sched,
        "영주",
        "햇님반",
        attendance={"check_in_kst": None, "check_out_kst": None},
        infer_presence_from_photos=False,
    )
    assert len(out) == 2
    first = next(e for e in out if e["time"] == "09:00")
    assert first["text"] == CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT


def test_ensure_start_anchor_noop_when_db_check_in_present() -> None:
    ev = [{"time": "09:00", "photo_id": None, "text": "그대로."}]
    out = ensure_class_scope_attendance_disclaimer(
        ev,
        {"09:00-10:00": "등원"},
        "영주",
        "햇님반",
        attendance={"check_in_kst": "09:00", "check_out_kst": None},
        infer_presence_from_photos=False,
    )
    assert len(out) == 1 and out[0]["text"] == "그대로."


def test_augment_summary_with_child_notes_noop_when_overlap() -> None:
    base = "정우는 집중력이 좋은 편으로 오늘 활동에 임했다."
    assert augment_summary_with_child_notes(base, "집중력이 좋음", "정우", "") == base


def test_augment_summary_with_child_notes_noop_without_notes() -> None:
    assert augment_summary_with_child_notes("요약만.", None, "정우", "") == "요약만."


def test_fill_timeline_schedule_gaps_noop_without_schedule() -> None:
    ev = [{"time": "10:00", "photo_id": None, "text": "x"}]
    assert fill_timeline_schedule_gaps(ev, None, "정우") == ev


def test_strip_lunch_menu_from_non_lunch_events() -> None:
    sched = {"12:00-13:00": "점심시간", "15:00-15:30": "오후 간식"}
    menu = ["닭곰탕", "쌀밥", "깍두기"]
    ev = [
        {"time": "12:00", "photo_id": None, "text": "정우는 점심을 먹었다 (닭곰탕, 쌀밥, 깍두기)"},
        {"time": "15:00", "photo_id": None, "text": "정우는 간식을 먹었다 (닭곰탕, 쌀밥, 깍두기)"},
    ]
    out = strip_lunch_menu_from_non_lunch_events(ev, sched, menu)
    assert "닭곰탕" in out[0]["text"]
    assert "닭곰탕" not in out[1]["text"]
    assert "간식" in out[1]["text"]


def test_formalize_parent_facing_report_korean_per_sentence() -> None:
    assert formalize_parent_facing_report_korean(
        "우림은 간식을 먹었다. 하루를 보냈다."
    ) == "우림은 간식을 먹었습니다. 하루를 보냈습니다."
    assert formalize_parent_facing_report_korean(CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT) == (
        CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT
    )


def test_formalize_parent_facing_report_korean_irregular_pasts_and_paren() -> None:
    assert formalize_parent_facing_report_korean("친구와 이야기도 나눴다.") == (
        "친구와 이야기도 나누었습니다."
    )
    assert formalize_parent_facing_report_korean("낮잠을 잤다.") == "낮잠을 잤습니다."
    assert formalize_parent_facing_report_korean("활동을 마무리했다 (happy).") == (
        "활동을 마무리했습니다 (happy)."
    )
    assert formalize_parent_facing_report_korean("(메뉴) 점심시간을 가졌다.") == (
        "(메뉴) 점심시간을 가졌습니다."
    )
    assert formalize_parent_facing_report_korean("두 모습이 번갈아 드러났다.") == (
        "두 모습이 번갈아 드러났습니다."
    )


def test_polish_report_korean_josa_scrubs_stale_memo_meta_phrase() -> None:
    s = "지수는 하원했다. 지수는 햇님반에서 메모에 적힌 바와 겹치는 점도 있었다. 엘리베이터를 좋아한다."
    out = polish_report_korean_josa("지수", s)
    assert "메모에 적힌" not in out
    assert "엘리베이터" in out


def test_scrub_llm_emotion_score_and_paren_tags_removes_inline_grade_chunk() -> None:
    s = "교실 활동을 했으며, happy (강도 1.00)의 표정을 지었습니다."
    assert scrub_llm_emotion_score_and_paren_tags(s) == "교실 활동을 했으며."


def test_scrub_llm_emotion_score_and_paren_tags_removes_grade_with_jimeo() -> None:
    s = (
        "자유놀이와 교실 활동을 하였고 happy (강도 1.00)의 표정을 지으며 "
        "즐거운 낮잠을 잤습니다."
    )
    assert scrub_llm_emotion_score_and_paren_tags(s) == (
        "자유놀이와 교실 활동을 하였고 즐거운 낮잠을 잤습니다."
    )


def test_scrub_llm_emotion_score_and_paren_tags_repairs_glue_go_ui_fragment() -> None:
    assert scrub_llm_emotion_score_and_paren_tags("하였고의 표정을 지으며 즐거운") == "하였고 즐거운"


def test_scrub_llm_emotion_score_and_paren_tags_removes_emotion_paren_tail() -> None:
    assert scrub_llm_emotion_score_and_paren_tags("마무리했습니다 (happy).") == "마무리했습니다."


def test_scrub_llm_emotion_score_and_paren_tags_keeps_korean_menu_parens() -> None:
    s = "점심을 먹었다 (닭곰탕)."
    assert scrub_llm_emotion_score_and_paren_tags(s) == s


def test_polish_report_korean_josa_strips_summary_emotion_grade_echo() -> None:
    s = "오늘 정우는 등원을 했으며, happy (강도 1.00)의 표정을 지었습니다."
    out = polish_report_korean_josa("정우", s)
    assert "강도" not in out
    assert "happy" not in out.lower()


def test_polish_report_korean_josa_strips_emotion_paren_before_formalize() -> None:
    out = polish_report_korean_josa("정우", "정우는 활동을 마무리했다 (happy).")
    assert "(happy)" not in out
    assert "마무리했습니다" in out


def test_polish_report_korean_josa_dedupes_adjacent_topic_markers() -> None:
    s = "엘리베이터를 좋아하는 경향이 지수는 지수는 활동에 적극적이었다."
    out = polish_report_korean_josa("지수", s)
    assert "지수는 지수는" not in out
    assert "지수는 활동에" in out


def test_polish_report_korean_josa_fixes_noat_typo() -> None:
    out = polish_report_korean_josa("강택", "강택은 떡을 좋아하며 노았습니다.")
    assert "노았습니다" not in out
    assert "놀았습니다" in out


def test_fix_common_report_korean_typos_meal_present_to_past() -> None:
    assert fix_common_report_korean_typos("점심을 먹습니다 (닭곰탕).") == "점심을 먹었습니다 (닭곰탕)."
    assert fix_common_report_korean_typos("오후 간식을 먹습니다.") == "오후 간식을 먹었습니다."


def test_fix_common_report_korean_typos_repairs_hyojeong_uro_merge() -> None:
    out = fix_common_report_korean_typos("행복한 표정우로 마무리했습니다.")
    assert "표정으로" in out
    assert "표정우로" not in out


def test_scrub_participation_disclaimer_attendance_verbs_rewrites_arrival() -> None:
    s = "참여 미확인입니다. 「햇님반」 일과로 등원했습니다."
    out = scrub_participation_disclaimer_attendance_verbs(s)
    assert "등원했습니다" not in out
    assert "등원 시간대에 맞춰" in out


def test_scrub_participation_disclaimer_attendance_verbs_rewrites_departure() -> None:
    s = "참여 미확인입니다. 「햇님반」 일과로 하원했습니다."
    out = scrub_participation_disclaimer_attendance_verbs(s)
    assert "하원했습니다" not in out
    assert "하원·통합 보육" in out


def test_polish_report_korean_josa_scrubs_contradictory_participation_anchors() -> None:
    in_arrival = "참여 미확인입니다. 「햇님반」 일과로 등원했습니다."
    assert "등원했습니다" not in polish_report_korean_josa("영주", in_arrival)
    departure = "참여 미확인입니다. 「햇님반」 일과로 하원했습니다."
    assert "하원했습니다" not in polish_report_korean_josa("영주", departure)


def test_polish_report_korean_josa_fixes_meogeul_name_food_glitch() -> None:
    s = (
        "점심과 오후 간식에는 닭곰탕, 쌀밥 등 먹을 강택이 풍성했지만, "
        "등원과 하원의 정확한 시간은 확인되지 않았습니다."
    )
    out = polish_report_korean_josa("강택", s)
    assert "먹을 강택이" not in out
    assert "먹거리가 풍성" in out


def test_polish_report_json_content_summary_gets_dedupe() -> None:
    raw = (
        '{"events": [], "summary": "경향이 지수는 지수는 활동에 잘 참여했다."}'
    )
    out = polish_report_json_content(raw, "지수", "김지수")
    data = json.loads(out)
    assert "지수는 지수는" not in data["summary"]


def test_fix_class_name_as_timeline_subject_haetnim_ban_i() -> None:
    s = fix_class_name_as_timeline_subject("민성", "햇님반", "햇님반이 점심시간에 먹었다.", class_scope=None)
    assert "햇님반이" not in s
    assert s.startswith("민성은")
    assert "점심시간에" in s


def test_fix_class_name_as_timeline_subject_stacked_ineun_class_scope() -> None:
    s = fix_class_name_as_timeline_subject(
        "우림", "햇님반", "햇님반이는 낮잠을 자고 휴식을 했다.", class_scope=True
    )
    assert "햇님반이는" not in s
    assert s.startswith("우림은 참여 미확인.")
    assert "낮잠을 자고" in s


def test_normalize_class_scope_dismissal_slots_sets_no_data_at_day_end() -> None:
    sched = {"16:00-18:00": "하원 및 통합 보육"}
    ev = [
        {
            "time": "16:00",
            "photo_id": None,
            "text": "민성은 참여 미확인. 「햇님반」 일과로 하원하며 통합 보육을 했다.",
        },
        {"time": "18:00", "photo_id": None, "text": "x"},
    ]
    out = normalize_class_scope_dismissal_slots_to_no_data(
        ev,
        sched,
        apply_end_slot_no_data=True,
    )
    assert out[0]["text"] == ev[0]["text"]
    assert out[1]["text"] == CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT


def test_normalize_class_scope_dismissal_only_day_end_row() -> None:
    sched = {
        "16:00-17:00": "하원 준비",
        "17:00-18:00": "통합 보육",
    }
    ev = [
        {"time": "16:00", "photo_id": None, "text": "keep sixteen"},
        {"time": "17:00", "photo_id": None, "text": "keep seventeen"},
        {"time": "18:00", "photo_id": None, "text": "replace eighteen"},
    ]
    out = normalize_class_scope_dismissal_slots_to_no_data(
        ev,
        sched,
        apply_end_slot_no_data=True,
    )
    assert out[0]["text"] == "keep sixteen"
    assert out[1]["text"] == "keep seventeen"
    assert out[2]["text"] == CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT


def test_repair_extraneous_class_scope_no_data_rows_keeps_top_and_bottom_only() -> None:
    sched = {
        "09:00-10:00": "등원 및 자유놀이",
        "12:00-13:00": "점심 및 양치",
        "16:00-17:00": "하원 준비",
        "17:00-18:00": "통합 보육",
    }
    att = {"check_in_kst": None, "check_out_kst": None}
    ev = [
        {"time": "09:00", "photo_id": None, "text": CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT},
        {"time": "13:00", "photo_id": None, "text": CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT},
        {"time": "17:00", "photo_id": None, "text": CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT},
        {"time": "18:00", "photo_id": None, "text": CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT},
    ]
    out = repair_extraneous_class_scope_no_data_rows(
        ev,
        sched,
        "민성",
        "햇님반",
        ["쌀밥", "국"],
        att,
        infer_presence_from_photos=False,
        narrative_class_scope=True,
    )
    by_t = {e["time"]: e["text"] for e in out}
    assert by_t["09:00"] == CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT
    assert by_t["18:00"] == CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT
    assert by_t["17:00"] != CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT
    assert by_t["13:00"] != CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT


def test_repair_extraneous_no_data_tolerates_trailing_period() -> None:
    """마침표·ZWSP 가 붙어도 앵커가 아닌 줄은 일과 채움으로 바뀐다."""
    sched = {
        "09:00-10:00": "등원 및 자유놀이",
        "16:00-18:00": "하원 및 통합 보육",
    }
    att = {"check_in_kst": None, "check_out_kst": None}
    ev = [
        {"time": "09:00", "photo_id": None, "text": CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT},
        {"time": "16:00", "photo_id": None, "text": CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT},
        {
            "time": "18:00",
            "photo_id": None,
            "text": CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT + ".\u200b",
        },
    ]
    out = repair_extraneous_class_scope_no_data_rows(
        ev,
        sched,
        "영주",
        "햇님반",
        [],
        att,
        infer_presence_from_photos=False,
        narrative_class_scope=True,
    )
    by_t = {e["time"]: e["text"] for e in out}
    assert by_t["09:00"] == CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT
    assert by_t["16:00"] != CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT
    assert "하원" in by_t["16:00"] or "일과표" in by_t["16:00"]
    t18 = by_t["18:00"].replace("\u200b", "").strip().rstrip(".")
    assert t18 == CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT


def test_normalize_dismissal_matches_unpadded_hhmm_at_day_end() -> None:
    sched = {"16:00-18:00": "하원 및 통합 보육"}
    ev = [{"time": "18:00", "photo_id": None, "text": "x"}]
    out = normalize_class_scope_dismissal_slots_to_no_data(
        ev,
        sched,
        apply_end_slot_no_data=True,
    )
    assert out[0]["text"] == CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT
    ev2 = [{"time": "6:00", "photo_id": None, "text": "wrong hour"}]
    out2 = normalize_class_scope_dismissal_slots_to_no_data(
        ev2,
        sched,
        apply_end_slot_no_data=False,
    )
    assert out2[0]["text"] != CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT


def test_repair_keeps_datos_when_time_unpadded_matches_anchor() -> None:
    sched = {
        "09:00-10:00": "등원 및 자유놀이",
        "16:00-18:00": "하원 및 통합 보육",
    }
    att = {"check_in_kst": None, "check_out_kst": None}
    ev = [
        {"time": "9:00", "photo_id": None, "text": CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT},
        {"time": "16:00", "photo_id": None, "text": CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT},
        {"time": "18:00", "photo_id": None, "text": CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT},
    ]
    out = repair_extraneous_class_scope_no_data_rows(
        ev,
        sched,
        "영주",
        "햇님반",
        [],
        att,
        infer_presence_from_photos=False,
        narrative_class_scope=True,
    )
    by_t = {e["time"]: e["text"] for e in out}
    assert by_t["9:00"] == CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT
    assert by_t["18:00"] == CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT
    assert by_t["16:00"] != CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT


def test_repair_extraneous_uses_child_filler_when_photos_infer_without_class_scope_narrative() -> None:
    """사진으로 등원은 추정되나 DB 등·하원이 없을 때 — 중간 시각의 「데이터가 없습니다」만 호칭 중심 채움으로 바꾼다."""
    sched = {
        "09:00-10:00": "등원 및 자유놀이",
        "16:00-18:00": "하원 및 통합 보육",
    }
    att = {"check_in_kst": None, "check_out_kst": None}
    ev = [
        {"time": "09:00", "photo_id": None, "text": CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT},
        {"time": "16:00", "photo_id": None, "text": CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT},
        {"time": "18:00", "photo_id": None, "text": CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT},
    ]
    out = repair_extraneous_class_scope_no_data_rows(
        ev,
        sched,
        "영주",
        "햇님반",
        [],
        att,
        infer_presence_from_photos=True,
        narrative_class_scope=False,
    )
    by_t = {e["time"]: e["text"] for e in out}
    assert by_t["09:00"] != CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT
    assert by_t["18:00"] == CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT
    assert by_t["16:00"] != CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT


def test_ensure_start_anchor_runs_when_only_end_had_datos() -> None:
    """맨 끝에만 「데이터가 없습니다」가 있어도 첫 시각 앵커는 넣는다."""
    sched = {"09:00-10:00": "등원", "16:00-18:00": "하원"}
    ev = [
        {"time": "09:00", "photo_id": None, "text": "등원했다."},
        {"time": "18:00", "photo_id": None, "text": CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT},
    ]
    out = ensure_class_scope_attendance_disclaimer(
        ev,
        sched,
        "영주",
        "햇님반",
        attendance={"check_in_kst": None, "check_out_kst": None},
        infer_presence_from_photos=False,
    )
    first = next(e for e in out if e["time"] == "09:00")
    assert first["text"] == CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT


def test_timeline_anchor_allowed_only_end_when_check_in_db() -> None:
    from server.ai.korean_postprocess import timeline_no_data_anchor_allowed_times

    sched = {"09:00-10:00": "등원", "16:00-18:00": "하원"}
    att = {"check_in_kst": "09:00", "check_out_kst": None}
    allowed = timeline_no_data_anchor_allowed_times(
        sched, att, infer_presence_from_photos=False
    )
    assert allowed == {"18:00"}
    s = fix_class_name_as_timeline_subject(
        "민성", "햇님반", "민성반 아이들은 활동했다.", class_scope=None
    )
    assert "민성반" not in s
    assert "햇님반 아이들" in s


def test_rewrite_class_scope_timeline_haetnim_ban_i_subject() -> None:
    ev = [{"time": "12:00", "photo_id": None, "text": "햇님반이 점심시간에 음식을 먹었다."}]
    out_t = rewrite_class_scope_timeline_child_topic(ev, "민성", "햇님반", class_scope=True)
    assert "햇님반이" not in out_t[0]["text"]
    assert "민성은" in out_t[0]["text"] and "참여 미확인" in out_t[0]["text"]
    out_f = rewrite_class_scope_timeline_child_topic(ev, "민성", "햇님반", class_scope=False)
    assert "햇님반이" not in out_f[0]["text"]
    assert out_f[0]["text"].startswith("민성은")
    assert "참여 미확인" not in out_f[0]["text"]


def test_polish_report_json_content_fixes_class_as_subject() -> None:
    raw = (
        '{"events": [{"time": "12:00", "photo_id": null, "text": "햇님반이 점심을 먹었다"}], '
        '"summary": "민성반 아이들은 하루를 보냈다."}'
    )
    out = polish_report_json_content(raw, "민성", "최민성", class_name="햇님반")
    data = json.loads(out)
    assert "햇님반이" not in data["events"][0]["text"]
    assert data["events"][0]["text"].startswith("민성")
    assert "민성반" not in data["summary"]


def test_fix_truncated_class_name_ideul() -> None:
    assert fix_truncated_class_name_ideul("햇님반", "민성은 햇님이들과 점심") == "민성은 햇님반 아이들과 점심"
    assert fix_truncated_class_name_ideul("햇님반", "햇님이들의 하루") == "햇님반 아이들의 하루"
    assert fix_truncated_class_name_ideul("햇님반", "이미 햇님반 아이들") == "이미 햇님반 아이들"


def test_polish_report_json_content_truncated_class_ideul() -> None:
    raw = (
        '{"events": [{"time": "12:00", "photo_id": null, "text": "우림은 햇님이들과 점심"}], '
        '"summary": "햇님이들의 하루"}'
    )
    out = polish_report_json_content(raw, "우림", "박우림", class_name="햇님반")
    data = json.loads(out)
    assert "햇님이들" not in data["events"][0]["text"]
    assert "햇님반 아이들과" in data["events"][0]["text"]
    assert "햇님반 아이들의" in data["summary"]


def test_polish_report_json_content_collapses_legacy_class_scope_haewon() -> None:
    long_text = (
        "민성은 개별 하원·참여는 DB에 없어 확인할 수 없다. 일과표상 이 시간대는 "
        "「하원 및 통합 보육」에 해당하며, 「햇님반」 반에서는 … "
        "(※ 보고 대상 아이의 실제 하원·참여와 같다고 볼 수 없다.)"
    )
    raw = json.dumps(
        {"events": [{"time": "18:00", "photo_id": None, "text": long_text}], "summary": "요약."},
        ensure_ascii=False,
    )
    out = polish_report_json_content(raw, "민성", "최민성", class_name="햇님반")
    data = json.loads(out)
    assert data["events"][0]["text"] == CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT


def test_polish_report_json_content_collapses_legacy_class_scope_disclaimer() -> None:
    long_text = (
        "오늘 DB 에 우림의 등원·하원 시각이 없어 개별 출석·참여 여부는 "
        "DB 만으로는 판단할 수 없다. 아래는 일과표 흐름이며 "
        "이 아이의 실제 참여와 같다고 볼 수 없다."
    )
    raw = json.dumps(
        {"events": [{"time": "09:00", "photo_id": None, "text": long_text}], "summary": "요약."},
        ensure_ascii=False,
    )
    out = polish_report_json_content(raw, "우림", "박우림", class_name="햇님반")
    data = json.loads(out)
    assert data["events"][0]["text"] == CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT


def test_polish_report_json_content_strips_cjk_in_events_and_summary() -> None:
    raw = (
        '{"events": [{"time": "13:00", "photo_id": null, "text": "박우림이 낮잠을 자며 안详해한다."}], '
        '"summary": "박우림의 详한 하루"}'
    )
    out = polish_report_json_content(raw, "우림", "박우림")
    data = json.loads(out)
    assert "详" not in data["events"][0]["text"]
    assert "详" not in data["summary"]
    assert "박우림" not in data["events"][0]["text"]
    assert "박우림" not in data["summary"]
    assert "우림" in data["events"][0]["text"]


def test_slot_label_at_time_sorted_prefers_later_slot_at_hour_boundary() -> None:
    from server.ai.korean_postprocess import _slot_label_at_time_sorted

    sched = {
        "12:00-13:00": "점심시간",
        "13:00-14:30": "낮잠 및 휴식",
    }
    assert _slot_label_at_time_sorted(sched, "13:00") == "낮잠 및 휴식"
    assert _slot_label_at_time_sorted(sched, "12:59") == "점심시간"


def test_rewrite_class_collective_guillemet_children_opener() -> None:
    out = rewrite_class_collective_subject_to_child(
        "「햇님반」 아이들이 오전 간식을 먹었다.",
        "민성",
        "햇님반",
        class_scope=True,
    )
    assert "참여 미확인" in out
    assert "민성" in out
    assert "아이들이" not in out


def test_collapse_redundant_participation_prefix_after_first_line() -> None:
    ev = [
        {"time": "10:00", "photo_id": None, "text": "민성은 참여 미확인. 「햇님반」 일과로 간식을 먹었다."},
        {"time": "10:30", "photo_id": None, "text": "참여 미확인입니다. 「햇님반」 아이들이 놀았다."},
    ]
    out = collapse_redundant_class_scope_participation_prefixes(
        ev, "민성", "햇님반", class_scope=True
    )
    assert "참여 미확인" in out[0]["text"]
    assert "참여 미확인" not in out[1]["text"]
    assert "일과로" in out[1]["text"]


def test_soften_dismissal_datos_when_intraday_narrative_in_slot() -> None:
    sched = {"16:00-18:00": "하원 및 통합 보육"}
    att = {"check_in_kst": None, "check_out_kst": None}
    ev = [
        {"time": "16:00", "photo_id": None, "text": CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT},
        {
            "time": "16:30",
            "photo_id": None,
            "text": "민성은 하원 준비를 하고 있습니다.",
        },
    ]
    out = soften_dismissal_no_data_when_intraday_narrative_in_slot(
        ev,
        sched,
        att,
        "민성",
        "햇님반",
        [],
        infer_presence_from_photos=False,
        narrative_class_scope=True,
    )
    assert out[0]["text"] != CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT
    assert "하원" in out[0]["text"] or "일과표" in out[0]["text"]
    assert out[1]["text"].startswith("민성은")


def test_merge_final_schedule_slot_timeline_rows_merges_point_and_range() -> None:
    sched = {"16:00-18:00": "하원 및 통합 보육"}
    ev = [
        {"time": "16:00", "photo_id": None, "text": CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT},
        {
            "time": "16:00-18:00",
            "photo_id": None,
            "text": "정우는 이 시각은 일과표 구간과 맞지 않아 활동을 구체적으로 적지 못했습니다.",
        },
        {"time": "18:00", "photo_id": None, "text": CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT},
    ]
    out = merge_final_schedule_slot_timeline_rows(ev, sched)
    by_t = {e["time"]: e["text"] for e in out}
    assert "16:00-18:00" in by_t
    assert "16:00" not in by_t
    assert by_t["18:00"] == CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT
    assert "적지 못했습니다" in by_t["16:00-18:00"]


def test_ensure_class_scope_timeline_end_no_data_row_appends() -> None:
    sched = {"09:00-10:00": "등원", "16:00-18:00": "하원 및 통합 보육"}
    ev = [{"time": "09:00", "photo_id": None, "text": "x"}]
    out = ensure_class_scope_timeline_end_no_data_row(
        ev,
        sched,
        {"check_in_kst": None, "check_out_kst": None},
    )
    times = [e["time"] for e in out]
    assert "18:00" in times
    assert next(e["text"] for e in out if e["time"] == "18:00") == CLASS_SCOPE_NO_INDIVIDUAL_DATA_TEXT


def test_formalize_parent_facing_ireonatda() -> None:
    assert formalize_parent_facing_report_korean("낮잠 시간이 지나 일어났다.") == (
        "낮잠 시간이 지나 일어났습니다."
    )
