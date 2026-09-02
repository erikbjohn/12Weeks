"""Behavior tests for the closures the 2026-09-01 re-verification found thin.
Each test feeds the bad input the original finding described and asserts the
bad outcome cannot happen."""
import json
import pytest


@pytest.fixture
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def _login(app_, db, email):
    from models import User
    u = User.query.filter_by(email=email).first()
    if not u:
        u = User(email=email)
        db.session.add(u); db.session.commit()
    client = app_.test_client()
    with client.session_transaction() as s:
        s["_user_id"] = str(u.id); s["_fresh"] = True
    return u, client


# ── S036: editing a Garmin run with one blank field must not null it ─────────

def test_run_edit_merges_and_keeps_garmin_source(app_ctx):
    app_, db = app_ctx
    u, client = _login(app_, db, "s036@test.com")
    from models import RunLog
    RunLog.query.filter_by(user_id=u.id).delete(); db.session.commit()
    row = RunLog(user_id=u.id, week=3, day_idx=1, distance_miles=4.55, duration_min=50,
                 avg_hr=132, elevation_ft=210, source="garmin")
    db.session.add(row); db.session.commit()
    # Athlete corrects only the notes; every other box is blank.
    r = client.post("/api/run-log", json={"week": 3, "day_idx": 1, "distance_miles": "",
                                          "duration_min": None, "avg_hr": "", "elevation_ft": "",
                                          "notes": "felt heavy"})
    assert r.status_code == 200, r.get_data(as_text=True)
    row = RunLog.query.filter_by(user_id=u.id, week=3, day_idx=1).first()
    assert (row.distance_miles, row.duration_min, row.avg_hr, row.elevation_ft) == (4.55, 50, 132, 210)
    assert row.source == "garmin"           # sync is not locked out
    assert "felt heavy" in row.notes and "[manual edit: notes]" in row.notes
    # A typed value does replace the stored one.
    client.post("/api/run-log", json={"week": 3, "day_idx": 1, "elevation_ft": 250})
    row = RunLog.query.filter_by(user_id=u.id, week=3, day_idx=1).first()
    assert row.elevation_ft == 250 and row.distance_miles == 4.55


# ── S053: a bodyweight (0) progression target is stored, not dropped ────────

def test_set_save_stores_zero_target_weight(app_ctx, monkeypatch):
    app_, db = app_ctx
    u, client = _login(app_, db, "s053@test.com")
    import app as appmod
    monkeypatch.setattr(appmod, "compute_next_targets",
                        lambda uid, ex, w, d: {"target_weight": 0, "target_reps": 12})
    r = client.post("/api/sets", json={"exercise": "Push-Up", "week": 2, "day_idx": 0,
                                       "set_number": 1, "weight": 0, "reps": 12, "done": True})
    assert r.status_code == 200, r.get_data(as_text=True)
    from models import SetLog
    row = SetLog.query.filter_by(user_id=u.id, week=2, day_idx=0).first()   # name canonicalizes
    assert row is not None and row.target_weight == 0 and row.target_reps == 12


# ── S069: no demo keyword can force the coach's anger level ─────────────────

def test_good_enough_keyword_has_no_hook():
    src = open("app.py").read() + open("coach_assembler.py").read()
    assert "_force_angry" not in src
    assert '"good enough" in user_msg' not in src


# ── S130: the unbounded all-sets dump is gone ────────────────────────────────

def test_get_api_sets_dump_is_gone(app_ctx):
    app_, db = app_ctx
    u, client = _login(app_, db, "s130@test.com")
    assert client.get("/api/sets").status_code == 405


# ── S134/S135: the photo prompt asks for no fabricated numbers ──────────────

def test_photo_prompt_requests_no_bodyfat_or_score():
    src = open("app.py").read()
    assert "Estimated body fat percentage" not in src
    assert "Aesthetic score" not in src
    assert "Do NOT estimate body fat percentage" in src


# ── S137: the review agent grades from the codified verdict ─────────────────

def test_weekly_review_grades_from_codified_verdict():
    from coach_assembler import _format_athlete_data, PROTOCOL_MAP as PROTOCOLS
    ctx = {"lift_trend": {"lift_decline_suspected": False, "weeks_compared": [3, 4]},
           "week_verdict": "SCALE_ONLY"}
    txt = _format_athlete_data(ctx, ["lift_trend"])
    assert "<week_verdict>SCALE_ONLY</week_verdict>" in txt
    proto = PROTOCOLS["weekly_review"] if isinstance(PROTOCOLS, dict) else ""
    assert "COMPLIANT, PARTIAL, or OFF-TRACK" not in proto
    assert "never invent a grade" in proto


# ── S139: request paths never fire the OAuth2 exchange ──────────────────────

def test_garmin_usable_false_when_token_expired():
    from garmin_client import GarminClient
    gc = GarminClient.__new__(GarminClient)
    gc._connected = True
    class _Tok: expired = True
    class _Garth: oauth2_token = _Tok()
    class _Api: garth = _Garth()
    gc.api = _Api()
    assert gc.connected is True
    assert gc.usable() is False
    _Tok.expired = False
    assert gc.usable() is True


def test_request_paths_gate_on_usable():
    import re
    for path in ("app.py", "coach_assembler.py"):
        src = open(path).read()
        for m in re.finditer(r"get_today_summary\([^)]*\)\s*if\s+gc\.(\w+)", src):
            assert m.group(1) == "usable", (path, m.group(0))
        assert "if gc.connected:\n        garmin_data = gc.get_today_summary" not in src


# ── S138: traceback endpoints need the admin key ────────────────────────────

def test_traceback_debug_endpoints_are_admin_only(app_ctx):
    app_, db = app_ctx
    u, client = _login(app_, db, "s138@test.com")
    assert client.get("/api/debug/workouts-error").status_code in (401, 403)
    assert client.post("/api/debug/goal-error", json={}).status_code in (401, 403)


# ── S089: no live specialist call under plain pytest ────────────────────────

def test_specialist_smoke_is_live_llm_marked():
    src = open("tests/coach_audit/test_specialist_audit.py").read()
    assert "@pytest.mark.live_llm" in src
