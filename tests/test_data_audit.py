"""The lightweight data audit must catch the fabrications we already paid for."""
import sys, os
from datetime import date
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from data_audit import audit


def _checks(F):
    return {(f["table"], f["check"]) for f in F}


def test_constant_soreness_and_full_chat_rows_are_high():
    ci = [{"user_id": 1, "log_date": f"2026-08-{d:02d}", "sleep_quality": 4, "stress_level": 7, "soreness": 5,
           "mood": 4, "motivation": 5, "anxiety": 6, "notes": "[Coach conversation check-in] [AI-extracted values]"}
          for d in range(19, 27)]
    F = audit({"morning_checkin": ci}, 1, date(2026, 9, 1))
    assert ("morning_checkin", "constant_score") in _checks(F)
    assert ("morning_checkin", "all_six_scores_from_chat") in _checks(F)
    assert all(f["sev"] == "HIGH" for f in F if f["table"] == "morning_checkin")


def test_phantom_set_target_is_high():
    sl = [{"user_id": 1, "logged_date": "2026-09-01", "exercise_name": "KB Swing", "set_number": 0,
           "weight": 35, "reps": 10, "done": True, "target_weight": 145}]
    F = audit({"set_log": sl}, 1, date(2026, 9, 1))
    assert ("set_log", "target_far_above_logged") in _checks(F)


def test_prescription_far_above_best_and_missing_schedule():
    sl = [{"user_id": 1, "logged_date": "2026-08-30", "exercise_name": "Leg Press", "set_number": 0,
           "weight": 180, "reps": 12, "done": True, "target_weight": None}]
    wp = [{"user_id": 1, "week": 4, "day_idx": 4, "exercise_name": "Leg Press", "sets": 4, "reps": "12",
           "target_weight": 360, "source": "coach"}]
    st = [{"user_id": 1, "start_date": "2026-08-10", "current_week": 4}]
    F = audit({"set_log": sl, "weekly_prescription": wp, "app_state": st, "weekly_day_schedule": [], "weekly_run_plan": []}, 1, date(2026, 9, 1))
    c = _checks(F)
    assert ("weekly_prescription", "target_far_above_best") in c
    assert ("weekly_day_schedule", "missing_schedule_row") in c
    assert ("weekly_run_plan", "runless_day_in_planned_week") in c


def test_manual_run_row_blocking_garmin_is_high():
    rl = [{"user_id": 1, "log_date": "2026-08-31", "source": "manual", "distance_miles": None, "duration_min": None, "avg_hr": None, "notes": "x"}]
    ga = [{"user_id": 1, "activity_date": "2026-08-31", "distance_miles": 4.5}]
    F = audit({"run_log": rl, "garmin_activity": ga}, 1, date(2026, 9, 1))
    assert ("run_log", "manual_row_blocking_garmin") in _checks(F)


def test_clean_data_is_quiet():
    ci = [{"user_id": 1, "log_date": "2026-09-01", "sleep_quality": 3, "stress_level": None, "soreness": None,
           "mood": None, "motivation": None, "anxiety": None, "notes": "[Coach conversation check-in] [self-report extracted: sleep_quality]"}]
    sl = [{"user_id": 1, "logged_date": "2026-09-01", "exercise_name": "KB Swing", "set_number": 0,
           "weight": 35, "reps": 10, "done": True, "target_weight": 40}]
    F = audit({"morning_checkin": ci, "set_log": sl}, 1, date(2026, 9, 1))
    assert not [f for f in F if f["sev"] == "HIGH"], F

