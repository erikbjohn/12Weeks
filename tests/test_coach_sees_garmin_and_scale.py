"""2026-08-28: "Why has the coach degraded so much?"

Four days of the coach nagging for a weigh-in that was already logged,
saying "I can't pull Garmin" while last night's sleep sat in garmin_wellness,
conceding REAL Garmin numbers were "fabricated", quoting -1.4 lb/wk to an
athlete losing ~1 lb/day, and parroting a "weigh-in tomorrow or Sunday"
string written for weekly weighers.

Root cause: the trigger agents (chat_opened, end_of_day, conversation) never
received the bodyweight / cut_status / garmin sections, the garmin section
made a live API call instead of reading the synced row, recent_pace was a
3-ROW window (2 days at daily cadence), and the sodium note was a hardcoded
weekly-weigh-in string. These tests pin every piece of the fix.
"""
import json
from datetime import date, datetime, timedelta, timezone

import pytest


# ─── 1. agent wiring ────────────────────────────────────────────────────────

def test_chat_opened_sees_scale_cut_and_garmin():
    from coach_agents import AGENTS
    req = AGENTS["chat_opened"]["requires"]
    assert "bodyweight" in req
    assert "cut_status" in req
    assert "garmin" in req


def test_conversation_sees_garmin():
    from coach_agents import AGENTS
    assert "garmin" in AGENTS["conversation"]["requires"]


def test_end_of_day_sees_scale():
    from coach_agents import AGENTS
    assert "bodyweight" in AGENTS["end_of_day"]["requires"]


# ─── 2. recent pace at DAILY cadence ────────────────────────────────────────

class _BW:
    def __init__(self, d, w):
        self.log_date, self.weight_lbs = d, w


def test_recent_pace_daily_weighins_is_a_weekly_slope_not_a_two_day_delta():
    """Erik's real rows: 205.4, 203.2, 203.8, 202.8 on four consecutive days.
    The old last-3-rows math gave -1.4 lb/wk; the true slope is ~-5 lb/wk."""
    from coach_assembler import recent_pace_lb_per_week
    d0 = date(2026, 8, 24)
    rows = [_BW(d0 + timedelta(days=i), w)
            for i, w in enumerate([205.4, 203.2, 203.8, 202.8])]
    pace = recent_pace_lb_per_week(rows)
    assert pace is not None
    assert pace < -4.0, pace


def test_recent_pace_falls_back_to_last_two_when_window_is_sparse():
    """Weekly weighers: 206 (7d ago) -> 212 (today) must still read as +6/wk."""
    from coach_assembler import recent_pace_lb_per_week
    rows = [_BW(date(2026, 6, 15), 208.0), _BW(date(2026, 6, 22), 206.0),
            _BW(date(2026, 6, 29), 212.0)]
    assert recent_pace_lb_per_week(rows) == pytest.approx(6.0, abs=0.01)


def test_recent_pace_single_row_is_none():
    from coach_assembler import recent_pace_lb_per_week
    assert recent_pace_lb_per_week([_BW(date(2026, 6, 29), 212.0)]) is None


# ─── 3. sodium note: Sunday is MEASUREMENT day, weigh-ins are daily ────────

def test_sodium_note_names_sunday_measurement_not_a_weekly_weighin():
    from coach_assembler import sodium_prep_note
    for wd in (4, 5):  # Fri, Sat
        note = sodium_prep_note(wd)
        assert "Sunday" in note
        assert "measurement" in note.lower()
        assert "daily" in note.lower()
        assert "Weigh-in tomorrow" not in note
    assert sodium_prep_note(0) is None


# ─── 4. garmin section reads the synced row before calling Garmin ──────────

class _WRow:
    def __init__(self, d, raw, pulled_at, **cols):
        self.date, self.raw_json, self.pulled_at = d, raw, pulled_at
        self.sleep_score = cols.get("sleep_score")
        self.hrv_last_night = cols.get("hrv_last_night")
        self.body_battery = cols.get("body_battery")
        self.resting_hr = cols.get("resting_hr")


_RAW = {"hrv": {"lastNight": 56, "weeklyAvg": 53, "status": "UNBALANCED"},
        "sleep": {"durationHours": 6.5, "score": 78},
        "bodyBattery": {"current": 22}, "trainingReadiness": None,
        "trainingStatus": None, "stress": {"overall": None}, "restingHr": 45}


def test_garmin_today_from_synced_row_has_summary_shape():
    from coach_assembler import garmin_today_from_wellness_row
    row = _WRow(date(2026, 8, 28), json.dumps(_RAW),
                datetime(2026, 8, 28, 13, 36, tzinfo=timezone.utc),
                sleep_score=78, hrv_last_night=56)
    g = garmin_today_from_wellness_row(row)
    assert g["date"] == "2026-08-28"
    assert g["sleep"]["score"] == 78 and g["sleep"]["durationHours"] == 6.5
    assert g["hrv"]["lastNight"] == 56
    assert g["synced_at"].startswith("2026-08-28T13:36")


def test_garmin_today_from_thin_row_does_not_emit_none_duration():
    """A row with sleep_score but no sleep_seconds and no raw_json must not
    hand assess_readiness a durationHours=None (TypeError on `< 5`)."""
    from coach_assembler import garmin_today_from_wellness_row
    from overtraining import assess_readiness
    row = _WRow(date(2026, 8, 19), None, None, sleep_score=77, hrv_last_night=61)
    g = garmin_today_from_wellness_row(row)
    assert "durationHours" not in g["sleep"]
    assert assess_readiness(g)["score"] is not None


def test_garmin_today_from_all_null_row_is_none():
    from coach_assembler import garmin_today_from_wellness_row
    row = _WRow(date(2026, 8, 28), None, None)
    assert garmin_today_from_wellness_row(row) is None
    assert garmin_today_from_wellness_row(None) is None


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def _user(db, email):
    from models import User
    u = User.query.filter_by(email=email).first()
    if not u:
        u = User(email=email, password_hash="x")
        db.session.add(u)
        db.session.commit()
    return u


def test_build_garmin_uses_db_row_and_skips_live_call(app_ctx, monkeypatch):
    app_, db = app_ctx
    import coach_assembler as ca
    from models import GarminWellness
    from flask_login import login_user
    u = _user(db, "garminrow@test.com")
    GarminWellness.query.filter_by(user_id=u.id).delete()
    db.session.add(GarminWellness(
        user_id=u.id, date=date(2026, 8, 28), sleep_score=78, sleep_seconds=23280,
        hrv_last_night=56, body_battery=22, resting_hr=45,
        raw_json=json.dumps(_RAW), pulled_at=datetime(2026, 8, 28, 13, 36)))
    db.session.commit()

    class _NeverLive:
        connected = True
        def get_today_summary(self, *a, **k):
            raise AssertionError("live Garmin call made despite a synced row")
        def try_restore_tokens(self, *a, **k):
            return False

    import app as app_mod
    monkeypatch.setattr(app_mod, "_get_garmin", lambda uid=None: _NeverLive())
    with app_.test_request_context():
        login_user(u, force=True)
        monkeypatch.setattr(ca, "_user_today", lambda: date(2026, 8, 28))
        out = ca._build_garmin()
    assert out["garmin"]["sleep"]["score"] == 78
    assert out["garmin"]["hrv"]["lastNight"] == 56


# ─── 5. get_garmin_wellness tool ────────────────────────────────────────────

def test_tool_registered():
    from coach_tools import TOOLS, _DISPATCH
    assert any(t["name"] == "get_garmin_wellness" for t in TOOLS)
    assert "get_garmin_wellness" in _DISPATCH


def test_get_garmin_wellness_returns_synced_days(app_ctx, monkeypatch):
    app_, db = app_ctx
    from models import GarminWellness
    from coach_tools import execute_tool
    import coach_tools as ct
    u = _user(db, "garmintool@test.com")
    GarminWellness.query.filter_by(user_id=u.id).delete()
    for i, (score, secs, hrv) in enumerate([(78, 23280, 56), (72, 23820, 43)]):
        db.session.add(GarminWellness(
            user_id=u.id, date=date(2026, 8, 28) - timedelta(days=i),
            sleep_score=score, sleep_seconds=secs, hrv_last_night=hrv,
            hrv_weekly_avg=54, body_battery=20, resting_hr=45,
            pulled_at=datetime(2026, 8, 28, 13, 36)))
    db.session.commit()
    monkeypatch.setattr(ct, "_user_local_today", lambda uid: date(2026, 8, 28))
    out = json.loads(execute_tool("get_garmin_wellness", {}, user_id=u.id))
    assert out["days"][0]["date"] == "2026-08-28"
    assert out["days"][0]["sleep_hours"] == 6.5
    assert out["days"][0]["sleep_score"] == 78
    assert out["days"][0]["hrv_last_night"] == 56
    assert out["days"][1]["date"] == "2026-08-27"
    assert out["today_synced"] is True
    assert "auto" in out["note"].lower()


def test_get_garmin_wellness_says_not_synced_when_today_missing(app_ctx, monkeypatch):
    app_, db = app_ctx
    from models import GarminWellness
    from coach_tools import execute_tool
    import coach_tools as ct
    u = _user(db, "garmintool2@test.com")
    GarminWellness.query.filter_by(user_id=u.id).delete()
    db.session.commit()
    monkeypatch.setattr(ct, "_user_local_today", lambda uid: date(2026, 8, 28))
    out = json.loads(execute_tool("get_garmin_wellness", {}, user_id=u.id))
    assert out["today_synced"] is False
    assert out["days"] == []
    assert "not synced" in out["note"].lower()


# ─── 6. prompt rules ────────────────────────────────────────────────────────

def test_core_prompt_forbids_asking_for_garmin_numbers_and_false_confessions():
    from coach_assembler import CORE_PROMPT
    p = CORE_PROMPT
    assert "GARMIN IS AUTO-SYNCED" in p
    assert "never ask the athlete" in p.lower()
    assert "can't pull garmin" in p.lower() or "can't access garmin" in p.lower()
    assert "re-check" in p.lower()
    assert "fabricat" in p.lower()


def test_tool_addendum_points_at_garmin_tool():
    from coach_with_tools import _tool_addendum
    a = _tool_addendum()
    assert "get_garmin_wellness" in a
    assert "sleep" in a.lower()


# ─── 7. today_status: name the short exercise; honest run wording ──────────

def _ts(**over):
    base = {
        "weekday": "Friday", "date": "2026-08-28",
        "workout_prescribed": True, "workout_state": "in_progress",
        "workout_logged": True,
        "workout_logged_exercises": ["Leg Press", "Dead Bug"],
        "workout_remaining_exercises": [],
        "workout_short_exercises": [{"name": "Dead Bug", "done": 2, "need": 3}],
        "sets_done": 18, "sets_logged": 18,
        "run_prescribed": "z2", "run_label": "Recovery Jog",
        "run_duration": "20 min", "run_logged": False,
    }
    base.update(over)
    return "\n".join(__import__("coach_assembler")._format_today_status_block(base))


def test_in_progress_names_the_exercise_that_is_short():
    block = _ts()
    assert "Dead Bug 2/3" in block, block


def test_pending_run_says_not_synced_not_go_run():
    block = _ts()
    assert "run: NOT LOGGED YET" in block, block
    low = block.lower()
    assert "garmin" in low and "sync" in low, block
    assert "already ran" in low, block


def test_multiple_runs_today_are_listed_separately():
    block = _ts(run_logged=True, run_distance_today=9.41, run_duration_today=103,
                run_avg_hr_today=126,
                run_activities_today=[
                    {"start": "07:07", "distance_miles": 4.11, "duration_min": 40, "avg_hr": 136},
                    {"start": "15:44", "distance_miles": 5.3, "duration_min": 63, "avg_hr": 120},
                ])
    assert "2 separate runs" in block, block
    assert "4.11mi" in block and "5.3mi" in block, block
    assert "do not describe" in block.lower() and "ran long" in block.lower(), block


def test_build_today_status_reports_short_exercises_and_activities(app_ctx, monkeypatch):
    app_, db = app_ctx
    import coach_assembler as ca
    from models import SetLog, GarminActivity, RunLog, AppState
    from flask_login import login_user
    u = _user(db, "tsshort@test.com")
    for M in (SetLog, GarminActivity, RunLog, AppState):
        M.query.filter_by(user_id=u.id).delete()
    today = date(2026, 8, 28)
    db.session.add(AppState(user_id=u.id, start_date=date(2026, 8, 10), current_week=3))
    for i in range(2):
        db.session.add(SetLog(user_id=u.id, week=3, day_idx=4, exercise_name="Dead Bug",
                              set_number=i, reps=10, weight=0, done=True, logged_date=today))
    for i in range(3):
        db.session.add(SetLog(user_id=u.id, week=3, day_idx=4, exercise_name="Leg Press",
                              set_number=i, reps=12, weight=180, done=True, logged_date=today))
    db.session.add(RunLog(user_id=u.id, week=3, day_idx=4, log_date=today,
                          distance_miles=9.41, duration_min=103, avg_hr=126, source="garmin"))
    for aid, st, dist, dur, hr in (("a1", "2026-08-28 07:07:53", 4.11, 40, 136),
                                   ("a2", "2026-08-28 15:44:36", 5.3, 63, 120)):
        db.session.add(GarminActivity(user_id=u.id, garmin_activity_id=aid, type_key="running",
                                      start_time_local=st, activity_date=today, week=3, day_idx=4,
                                      distance_miles=dist, duration_min=dur, avg_hr=hr))
    db.session.commit()
    with app_.test_request_context():
        login_user(u, force=True)
        monkeypatch.setattr(ca, "_user_today", lambda: today)
        monkeypatch.setattr(ca, "_current_week", lambda: 3)
        monkeypatch.setattr(ca, "_resolve_workout_for_day", lambda w, d: {
            "isRest": False, "name": "Heavy Lower",
            "exercises": [{"name": "Leg Press", "sets": 3}, {"name": "Dead Bug", "sets": 3}],
        })
        ts = ca._build_today_status()["today_status"]
    assert ts["workout_state"] == "in_progress"
    assert ts["workout_short_exercises"] == [{"name": "Dead Bug", "done": 2, "need": 3}]
    assert [a["distance_miles"] for a in ts["run_activities_today"]] == [4.11, 5.3]
    assert ts["run_activities_today"][0]["start"] == "07:07"
