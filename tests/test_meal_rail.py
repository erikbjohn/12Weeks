"""tests/test_meal_rail.py — TDD for the fasted-dose meal-timing rail
(Task 10 of docs/superpowers/specs/2026-08-10-peptide-protocol-integration-
design.md §4): a nightly fasted dose (>=21:00, e.g. 22:00 Tesamorelin) needs
2+ hours fasted before it, so the day's LAST meal — whichever one that is,
under whatever fasting protocol — must end by ~20:00.

Covered:
  (a) generate_meal_plan() with eating_window_end_override under the "none"
      protocol: every meal time (including the last snack, normally 9:00pm,
      and a forced protein-supplement meal, normally 8:00pm) parses <= 7:30pm.
  (b) no override -> times unchanged vs. the same call without it.
  (c) fasting_note is appended to the plan's "note" field.
  (d) endpoint-level: /api/meals/regenerate with a seeded 22:00 Tesamorelin
      dose on the target date clamps every served meal time and carries the
      note.
  (e) zero PeptideDose rows -> no rail, no crash (times match the raw
      protocol window).
  (f) reconciliation: /api/admin/import-protocol adding fasted doses over an
      existing current-week plan regenerates only the unlogged, non-past
      day; a logged day and a past day (even though also newly fasted) are
      left untouched; the response lists exactly the regenerated day_idx.
  (g) the actual card-serving payload (/api/workouts, which embeds
      WeeklyMealPlan.meal_data as day["mealPlan"] — the same JSON the UI
      reads, per the no-UI-contradiction rule) reflects the clamp too, not
      just the DB row.
  (h) /api/weekly-program/generate's meal loop (the SECOND caller,
      _weekly_generation_impl) resolves day_date from AppState.start_date +
      target_week — NOT from "today's calendar week" — because this path
      routinely plans a FUTURE week ("Plan Next Week" defaults target_week
      to current_week+1). Pins that a fasted dose on a future week's date
      still clamps that week's meals.

Short-lived per-request app contexts, no held-open module context across
test-client requests — mirrors tests/test_protocol_api.py's documented
flask-login/current_user leak trap.
"""
from datetime import date, timedelta

import pytest

from meal_generator import generate_meal_plan, _parse_time_minutes


# ── shared fixtures / helpers (mirrors tests/test_protocol_api.py) ─────────

@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
    yield app, db


def _app_do(app_, fn):
    with app_.app_context():
        return fn()


def _make_user(app_, db, email, tz="America/Los_Angeles"):
    def _do():
        from models import (User, PeptideDose, TrainingGoal, UserFoodSelections,
                            BodyWeight, AppState, WeeklyMealPlan, MealLog)
        u = User.query.filter_by(email=email).first()
        if not u:
            u = User(email=email, timezone=tz)
            db.session.add(u)
            db.session.commit()
        else:
            u.timezone = tz
            db.session.commit()
        for model in (PeptideDose, TrainingGoal, UserFoodSelections, BodyWeight,
                      AppState, WeeklyMealPlan, MealLog):
            model.query.filter_by(user_id=u.id).delete()
        db.session.commit()
        return u.id
    return _app_do(app_, _do)


def _client_for(app_, user_id):
    client = app_.test_client()
    with client.session_transaction() as s:
        s["_user_id"] = str(user_id)
        s["_fresh"] = True
    return client


def _add_dose(app_, db, user_id, d, time_s, compound="Tesamorelin", dose_mg=2,
              event_type="Injection"):
    def _do():
        from models import PeptideDose
        row = PeptideDose(user_id=user_id, date=d, time=time_s, event_type=event_type,
                          compound=compound, dose_mg=dose_mg, syringe_units="20u",
                          site="Abdomen", notes=None, taken_at=None)
        db.session.add(row)
        db.session.commit()
        return row.id
    return _app_do(app_, _do)


def _set_goal(app_, db, user_id, fasting_protocol="none", daily_calories=2400,
              protein_grams=200, carb_grams=200, fat_grams=70, goal_type="cut"):
    def _do():
        from models import TrainingGoal
        g = TrainingGoal(user_id=user_id, goal_type=goal_type,
                         daily_calories=daily_calories, protein_grams=protein_grams,
                         carb_grams=carb_grams, fat_grams=fat_grams,
                         fasting_protocol=fasting_protocol)
        db.session.add(g)
        db.session.commit()
        return g.id
    return _app_do(app_, _do)


_FOODS = {
    "proteins": ["chicken_breast", "whey_protein"],
    "carbs": ["white_rice", "sweet_potato"],
    "fats": ["olive_oil", "avocado"],
    "vegetables": ["broccoli", "spinach"],
}


def _set_food_selections(app_, db, user_id, foods=None):
    def _do():
        from models import UserFoodSelections
        fs = UserFoodSelections(user_id=user_id, selected_foods=foods or _FOODS, completed=True)
        db.session.add(fs)
        db.session.commit()
    return _app_do(app_, _do)


def _add_bodyweight(app_, db, user_id, d, lbs=200):
    def _do():
        from models import BodyWeight
        db.session.add(BodyWeight(user_id=user_id, log_date=d, weight_lbs=lbs))
        db.session.commit()
    return _app_do(app_, _do)


def _set_app_state(app_, db, user_id, start_date):
    def _do():
        from models import AppState
        s = AppState.query.filter_by(user_id=user_id).first()
        if not s:
            s = AppState(user_id=user_id)
            db.session.add(s)
        s.start_date = start_date
        s.current_week = 1
        s.baseline_done = True
        db.session.commit()
    return _app_do(app_, _do)


def _seed_meal_plan(app_, db, user_id, week, day_idx, meal_data, day_type="moderate"):
    def _do():
        from models import WeeklyMealPlan
        db.session.add(WeeklyMealPlan(user_id=user_id, week=week, day_idx=day_idx,
                                      meal_data=meal_data, daily_calories=meal_data.get("targetCal", 0),
                                      daily_protein=meal_data.get("targetProtein", 0),
                                      day_type=day_type, source="generator"))
        db.session.commit()
    return _app_do(app_, _do)


def _seed_meal_log(app_, db, user_id, d, eaten):
    def _do():
        from models import MealLog
        db.session.add(MealLog(user_id=user_id, log_date=d, eaten=eaten))
        db.session.commit()
    return _app_do(app_, _do)


def _get_meal_plan(app_, user_id, week, day_idx):
    def _do():
        from models import WeeklyMealPlan
        row = WeeklyMealPlan.query.filter_by(user_id=user_id, week=week, day_idx=day_idx).first()
        return dict(row.meal_data) if row else None
    return _app_do(app_, _do)


def _set_today(monkeypatch, d):
    import app as appmod
    monkeypatch.setattr(appmod, "_user_today", lambda: d)


def _set_today_for(monkeypatch, d):
    import app as appmod
    monkeypatch.setattr(appmod, "_user_today_for", lambda user: d)


def _admin_client(app_, monkeypatch, admin_key="test-admin-key"):
    monkeypatch.setenv("ADMIN_API_KEY", admin_key)
    return app_.test_client(), admin_key


_SEVEN_THIRTY_PM = _parse_time_minutes("7:30pm")


def _assert_all_times_clamped(meal_plan, cutoff_min=_SEVEN_THIRTY_PM):
    """Every real (non-'Anytime') meal time in the plan parses <= cutoff."""
    assert meal_plan is not None and meal_plan.get("meals"), meal_plan
    for m in meal_plan["meals"]:
        t = m.get("time")
        if t in (None, "Anytime"):
            continue
        assert _parse_time_minutes(t) <= cutoff_min, (
            f"{m.get('name')!r} at {t!r} exceeds the 7:30pm rail cutoff")


# ── (a) generator-level: override clamps every meal, incl. forced supplement ─

def test_override_clamps_last_snack_and_supplement_under_none_protocol():
    # protocol "none" -> 4 meals, last one normally 9:00pm (a rail violator);
    # big protein target forces the shortfall-closer supplement (normally
    # hardcoded 8:00pm — the other violator named in the task brief).
    targets = {"calories": 4200, "protein": 500, "carbs": 300, "fat": 110}
    plan = generate_meal_plan(
        _FOODS, "moderate", targets, fasting_protocol="none",
        targets_pre_adjusted=True, eating_window_end_override="7:30pm",
    )
    supplement_meals = [m for m in plan["meals"] if "Supplement" in m.get("name", "")]
    assert supplement_meals, "test setup should have forced a protein-shortfall supplement meal"
    _assert_all_times_clamped(plan)


# ── (b) no override -> identical output to the pre-existing call shape ──────

def test_no_override_leaves_times_unchanged():
    targets = {"calories": 2400, "protein": 200, "carbs": 200, "fat": 70}
    baseline = generate_meal_plan(_FOODS, "moderate", targets, fasting_protocol="none",
                                  targets_pre_adjusted=True)
    explicit_none = generate_meal_plan(_FOODS, "moderate", targets, fasting_protocol="none",
                                       targets_pre_adjusted=True,
                                       eating_window_end_override=None, fasting_note=None)
    baseline_times = [m["time"] for m in baseline["meals"]]
    explicit_times = [m["time"] for m in explicit_none["meals"]]
    assert baseline_times == explicit_times
    # The un-overridden "none" protocol's last meal is still 9:00pm — proves
    # this test would actually catch an accidental always-on clamp.
    assert baseline_times[-1] == "9:00pm"
    assert baseline["note"] == explicit_none["note"]


# ── (c) fasting_note lands verbatim in the plan's note field ────────────────

def test_fasting_note_appended_to_plan_note():
    targets = {"calories": 2200, "protein": 180, "carbs": 180, "fat": 60}
    note_text = "Tesamorelin at 10pm requires 2h fasted — last meal ends by 8pm"
    plan = generate_meal_plan(_FOODS, "moderate", targets, fasting_protocol="16_8",
                              targets_pre_adjusted=True,
                              eating_window_end_override="7:30pm", fasting_note=note_text)
    assert note_text in plan["note"]


def test_fasting_note_appended_on_fast_day_too():
    plan = generate_meal_plan(_FOODS, "fast_day", {"calories": 0, "protein": 0, "carbs": 0, "fat": 0},
                              fasting_note="Tesamorelin at 10pm requires 2h fasted — last meal ends by 8pm")
    assert "requires 2h fasted" in plan["note"]


# ── (d) endpoint-level: /api/meals/regenerate clamps + carries the note ────

def test_regenerate_endpoint_clamps_and_notes_fasted_date(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "rail-d@test.com")
    d = date(2026, 10, 5)  # Monday
    _set_today(monkeypatch, d)
    _add_dose(app_, db, uid, d, "22:00")
    _set_goal(app_, db, uid, fasting_protocol="none")
    _set_food_selections(app_, db, uid)
    _add_bodyweight(app_, db, uid, d - timedelta(days=1))

    client = _client_for(app_, uid)
    r = client.post("/api/meals/regenerate", json={"week": 1})
    assert r.status_code == 200, r.get_data(as_text=True)

    plan = _get_meal_plan(app_, uid, 1, 0)  # Oct 5 == week_monday -> day_idx 0
    _assert_all_times_clamped(plan)
    assert "requires 2h fasted" in plan["note"]
    assert "Tesamorelin" in plan["note"]


# ── (e) zero PeptideDose rows -> no rail, no crash ───────────────────────────

def test_regenerate_endpoint_no_rail_without_fasted_dose(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "rail-e@test.com")
    d = date(2026, 10, 5)  # Monday
    _set_today(monkeypatch, d)
    # No PeptideDose rows at all for this user.
    _set_goal(app_, db, uid, fasting_protocol="none")
    _set_food_selections(app_, db, uid)
    _add_bodyweight(app_, db, uid, d - timedelta(days=1))

    client = _client_for(app_, uid)
    r = client.post("/api/meals/regenerate", json={"week": 1})
    assert r.status_code == 200, r.get_data(as_text=True)

    plan = _get_meal_plan(app_, uid, 1, 0)
    times = [m["time"] for m in plan["meals"] if m["time"] != "Anytime"]
    # Protocol "none"'s raw window end (9:00pm) survives -- proves no rail
    # silently applied itself absent any fasted-dose data.
    assert "9:00pm" in times
    assert "requires 2h fasted" not in (plan.get("note") or "")


# ── (f) reconciliation: import adding fasted doses regenerates the right day ─

def test_reconcile_meal_rail_regenerates_only_open_day(app_ctx, monkeypatch, tmp_path):
    import csv as _csv
    app_, db = app_ctx
    uid = _make_user(app_, db, "rail-f@test.com")

    # today = Thu 2026-10-08; program week_monday = Mon 2026-10-05.
    # day_idx: 0/Mon,1/Tue,2/Wed = past; 3/Thu = today; 4/Fri,5/Sat,6/Sun = future.
    today = date(2026, 10, 8)
    week_monday = date(2026, 10, 5)
    start_date = date(2026, 9, 21)  # Monday, 17 days before today -> current_week == 3
    _set_today_for(monkeypatch, today)
    _set_goal(app_, db, uid, fasting_protocol="none")
    _set_food_selections(app_, db, uid)
    _add_bodyweight(app_, db, uid, today - timedelta(days=1))
    _set_app_state(app_, db, uid, start_date)

    sentinel = {"label": "Test Day", "targetCal": 2000, "targetProtein": 180,
               "targetCarbs": 150, "targetFat": 60, "note": "ORIGINAL-UNCHANGED",
               "meals": [{"time": "9:00pm", "name": "Dinner", "optional": False, "foods": []}]}
    PAST_DAY = 1     # Tue 10/06 -- past
    LOGGED_DAY = 5   # Sat 10/10 -- future but logged
    OPEN_DAY = 4     # Fri 10/09 -- future, unlogged: the only one that should regenerate
    for day_idx in (PAST_DAY, LOGGED_DAY, OPEN_DAY):
        _seed_meal_plan(app_, db, uid, 3, day_idx, dict(sentinel))
    _seed_meal_log(app_, db, uid, week_monday + timedelta(days=LOGGED_DAY), ["Dinner"])

    csv_path = tmp_path / "protocol.csv"
    fields = ["Date", "Time", "Event_Type", "Compound", "Dose_mg", "Syringe_Units", "Site", "Notes"]
    rows = [
        {"Date": (week_monday + timedelta(days=PAST_DAY)).isoformat(), "Time": "22:00",
         "Event_Type": "Injection", "Compound": "Tesamorelin", "Dose_mg": 2,
         "Syringe_Units": "20u", "Site": "Abdomen", "Notes": ""},
        {"Date": (week_monday + timedelta(days=LOGGED_DAY)).isoformat(), "Time": "22:00",
         "Event_Type": "Injection", "Compound": "Tesamorelin", "Dose_mg": 2,
         "Syringe_Units": "20u", "Site": "Abdomen", "Notes": ""},
        {"Date": (week_monday + timedelta(days=OPEN_DAY)).isoformat(), "Time": "22:00",
         "Event_Type": "Injection", "Compound": "Tesamorelin", "Dose_mg": 2,
         "Syringe_Units": "20u", "Site": "Abdomen", "Notes": ""},
    ]
    with open(csv_path, "w", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow(row)

    client, admin_key = _admin_client(app_, monkeypatch)
    r = client.post(
        f"/api/admin/import-protocol?email=rail-f@test.com",
        json={"csv_path": str(csv_path), "force_past": True},
        headers={"X-Admin-Key": admin_key},
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert body["meal_days_regenerated"] == [OPEN_DAY]

    past_plan = _get_meal_plan(app_, uid, 3, PAST_DAY)
    assert past_plan["note"] == "ORIGINAL-UNCHANGED"
    assert past_plan["meals"][0]["time"] == "9:00pm"

    logged_plan = _get_meal_plan(app_, uid, 3, LOGGED_DAY)
    assert logged_plan["note"] == "ORIGINAL-UNCHANGED"
    assert logged_plan["meals"][0]["time"] == "9:00pm"

    open_plan = _get_meal_plan(app_, uid, 3, OPEN_DAY)
    assert open_plan["note"] != "ORIGINAL-UNCHANGED"
    assert "requires 2h fasted" in open_plan["note"]
    _assert_all_times_clamped(open_plan)


def test_reconcile_meal_rail_noop_without_changed_dates(app_ctx, monkeypatch, tmp_path):
    """No fasted-status flips in the import -> nothing regenerated (also
    covers the no-goal/no-food-selections early-return: this user has
    neither)."""
    import csv as _csv
    app_, db = app_ctx
    uid = _make_user(app_, db, "rail-f-noop@test.com")
    today = date(2026, 10, 8)
    _set_today_for(monkeypatch, today)

    csv_path = tmp_path / "protocol_noop.csv"
    fields = ["Date", "Time", "Event_Type", "Compound", "Dose_mg", "Syringe_Units", "Site", "Notes"]
    rows = [{"Date": "2026-10-09", "Time": "07:00", "Event_Type": "Injection",
             "Compound": "BPC-157", "Dose_mg": 0.25, "Syringe_Units": "10u",
             "Site": "Thigh", "Notes": ""}]
    with open(csv_path, "w", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow(row)

    client, admin_key = _admin_client(app_, monkeypatch)
    r = client.post(
        "/api/admin/import-protocol?email=rail-f-noop@test.com",
        json={"csv_path": str(csv_path), "force_past": True},
        headers={"X-Admin-Key": admin_key},
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["meal_days_regenerated"] == []


# ── (g) the actual card payload (/api/workouts) reflects the clamp ──────────

def test_served_workouts_payload_shows_clamped_meal_times(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "rail-g@test.com")
    d = date(2026, 10, 5)  # Monday
    _set_today(monkeypatch, d)
    _add_dose(app_, db, uid, d, "22:00")
    _set_goal(app_, db, uid, fasting_protocol="none")
    _set_food_selections(app_, db, uid)
    _add_bodyweight(app_, db, uid, d - timedelta(days=1))

    client = _client_for(app_, uid)
    r_gen = client.post("/api/meals/regenerate", json={"week": 1})
    assert r_gen.status_code == 200, r_gen.get_data(as_text=True)

    r = client.get("/api/workouts")
    assert r.status_code == 200
    body = r.get_json()
    day = body["1"]["days"][0]  # week 1, day_idx 0 == Oct 5
    meal_plan = day.get("mealPlan")
    assert meal_plan and meal_plan.get("meals"), "served card payload is missing the meal plan"
    _assert_all_times_clamped(meal_plan)
    assert "requires 2h fasted" in meal_plan["note"]


# ── (h) caller 2: _weekly_generation_impl resolves date from target_week, ──
# ── not from today's calendar week (it commonly plans a FUTURE week) ───────

def _generate_and_wait(client, payload, timeout=30):
    """Mirrors tests/test_generate_failloud.py's helper: force_regen / fresh
    generation runs in a background thread; poll /generate-status."""
    import time
    resp = client.post("/api/weekly-program/generate", json=payload)
    if resp.status_code != 200:
        return resp.status_code, resp.get_json()
    body = resp.get_json() or {}
    if body.get("status") != "started":
        return resp.status_code, body
    week = payload.get("week")
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/weekly-program/generate-status?week={week}").get_json() or {}
        if j.get("status") in ("done", "error"):
            return 200, j
        time.sleep(0.2)
    return 200, {"status": "timeout"}


def test_weekly_generate_future_week_resolves_date_from_target_week(app_ctx, monkeypatch):
    """Real (unmocked) clock: 'today' is whatever date the test actually
    runs on. Seeds AppState.start_date == today (a Monday) and requests
    target_week=2 -- a week that does NOT contain today. A fasted dose is
    seeded on week 2's Monday. If the meal loop mistakenly derived day_date
    from TODAY's calendar week (the /api/meals/regenerate idiom) instead of
    from target_week via start_date, it would look up the wrong date and
    the rail would never fire -- this test only passes with the
    start_date-based resolution actually implemented in app.py."""
    import coach_planning_program, coach_planning_runs, coach_planning_meals
    from utils_time import user_local_today

    app_, db = app_ctx
    uid = _make_user(app_, db, "rail-h@test.com")
    today = user_local_today("America/Los_Angeles")
    start_date = today - timedelta(days=today.weekday())  # this week's Monday
    week2_monday = start_date + timedelta(days=7)
    assert week2_monday > today, "test requires week 2 to be strictly in the future"

    _set_app_state(app_, db, uid, start_date)
    _set_goal(app_, db, uid, fasting_protocol="none")
    _set_food_selections(app_, db, uid)
    _add_bodyweight(app_, db, uid, today)
    _add_dose(app_, db, uid, week2_monday, "22:00")

    monkeypatch.setattr(coach_planning_program, "generate_week_program", lambda **k: ({}, [], {"deload": False, "reason": None}))
    monkeypatch.setattr(coach_planning_runs, "generate_week_runs", lambda **k: {})
    monkeypatch.setattr(coach_planning_meals, "generate_week_meals", lambda **k: {})

    client = _client_for(app_, uid)
    status, body = _generate_and_wait(client, {"week": 2, "force_regen": True})
    assert status == 200, body

    plan = _get_meal_plan(app_, uid, 2, 0)  # week 2, day_idx 0 == week2_monday
    assert plan is not None, "meal loop did not write week 2 day 0 -- check food selections / goal wiring"
    _assert_all_times_clamped(plan)
    assert "requires 2h fasted" in plan["note"]


# ── (i) caller 3: /api/admin/generate-meals threads the rail too ───────────

def test_admin_generate_meals_clamps_fasted_day_leaves_others_alone(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "rail-i@test.com")
    start_date = date(2026, 8, 10)  # Monday
    _set_app_state(app_, db, uid, start_date)
    _set_goal(app_, db, uid, fasting_protocol="none")
    _set_food_selections(app_, db, uid)
    _add_bodyweight(app_, db, uid, start_date - timedelta(days=1))
    _add_dose(app_, db, uid, start_date, "22:00")  # only day_idx 0 (Mon) is fasted

    client, admin_key = _admin_client(app_, monkeypatch)
    r = client.post(
        "/api/admin/generate-meals",
        json={"email": "rail-i@test.com", "week": 1},
        headers={"X-Admin-Key": admin_key},
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["days_generated"] > 0

    fasted_plan = _get_meal_plan(app_, uid, 1, 0)
    _assert_all_times_clamped(fasted_plan)
    assert "requires 2h fasted" in fasted_plan["note"]

    unfasted_plan = _get_meal_plan(app_, uid, 1, 1)  # Tue -- no dose
    unfasted_times = [m["time"] for m in unfasted_plan["meals"] if m["time"] != "Anytime"]
    assert "9:00pm" in unfasted_times, "un-fasted day should keep protocol 'none''s raw 9:00pm window"
    assert "requires 2h fasted" not in (unfasted_plan.get("note") or "")
