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


# ═════════════════════════ batch 2 ═════════════════════════

# ── S052: the 16:8 filter keeps the meal the fasted-dose rail placed ─────────

def test_16_8_filter_honours_rail_cutoff(app_ctx, monkeypatch):
    app_, db = app_ctx
    u, client = _login(app_, db, "s052@test.com")
    from models import TrainingGoal
    import app as appmod
    TrainingGoal.query.filter_by(user_id=u.id).delete(); db.session.commit()
    db.session.add(TrainingGoal(user_id=u.id, goal_type="cut", fasting_protocol="16:8")); db.session.commit()
    with app_.test_request_context():
        from flask_login import login_user
        login_user(u)
        days = [{"mealPlan": {"note": "Retatrutide at 10pm requires 2h fasted — last meal ends by 8pm",
                              "meals": [{"time": "7:30pm", "name": "Dinner", "foods": [{"item": "Chicken breast"}]}]}},
                {"mealPlan": {"meals": [{"time": "7:30pm", "name": "Dinner", "foods": [{"item": "Chicken breast"}]}]}}]
        monkeypatch.setattr(appmod, "_FOOD_NAME_TO_ID", {}, raising=False)
        out = appmod._filter_meals_by_food_selections(days, set())
    rail_meals = out[0]["mealPlan"]["meals"]
    assert rail_meals and rail_meals[0]["foods"][0]["item"] == "Chicken breast"   # rail day: 7:30pm meal kept
    assert out[1]["mealPlan"]["meals"] == []                                        # plain 16:8 day: 7:30pm stripped


# ── S153: no credential login from the server ───────────────────────────────

def test_garmin_login_disabled_on_render(app_ctx, monkeypatch):
    app_, db = app_ctx
    u, client = _login(app_, db, "s153@test.com")
    monkeypatch.setenv("RENDER", "1")
    r = client.post("/api/garmin/login", json={"email": "x@y.z", "password": "p"})
    assert r.status_code == 404


# ── S083: flags reach the coach's memories ──────────────────────────────────

def test_thumbs_down_flag_is_in_coach_memories(app_ctx):
    app_, db = app_ctx
    u, client = _login(app_, db, "s083@test.com")
    r = client.post("/api/coach/flag", json={"coach_text": "You're done lifting for today.",
                                             "category": "wrong_state", "note": "I had logged one set"})
    assert r.status_code == 200, r.get_data(as_text=True)
    with app_.test_request_context():
        from flask_login import login_user
        login_user(u)
        from coach_assembler import _build_coach_memories
        mems = _build_coach_memories()["coach_memories"]
    flagged = [m for m in mems if m["type"] == "flagged"]
    assert flagged and "wrong_state" in flagged[0]["content"] and "I had logged one set" in flagged[0]["content"]


# ── S023: one week formula ──────────────────────────────────────────────────

def test_no_inline_week_formula_outside_program_calendar():
    import re, glob
    pat = re.compile(r"//\s*7\s*\)\s*\+\s*1|// 7 \+ 1")
    for f in glob.glob("*.py"):
        if f in ("program_calendar.py", "goal_engine.py"):   # goal_engine: curve-day → rate-week, not the program week
            continue
        for i, line in enumerate(open(f), 1):
            if "rate-week" in line:      # block-3 curve day → rate bucket, explicitly not the program week
                continue
            assert not pat.search(line), (f, i, line.strip())


# ── S100: one e1RM formula ──────────────────────────────────────────────────

def test_no_inline_epley_outside_lift_history():
    import glob
    for f in glob.glob("*.py"):
        if f == "lift_history.py":
            continue
        assert "/ 30.0" not in open(f).read() and "/30.0" not in open(f).read(), f


# ── S121: the run planner block cites the real columns ──────────────────────

def test_run_history_block_uses_activity_columns(app_ctx):
    app_, db = app_ctx
    u, _ = _login(app_, db, "s121@test.com")
    from models import RunLog
    from datetime import date
    from coach_planning_runs import _build_run_history_block
    RunLog.query.filter_by(user_id=u.id).delete(); db.session.commit()
    db.session.add(RunLog(user_id=u.id, week=1, day_idx=0, log_date=date(2026, 8, 30), distance_miles=4.5,
                          duration_min=50, avg_hr=132, elevation_ft=100, source="garmin",
                          activity_type="running", activity_name="Z2 50 min"))
    db.session.commit()
    txt = _build_run_history_block(u.id, 1, today=date(2026, 9, 1))
    assert "type=running" in txt and "watch_workout=Z2 50 min" in txt


# ── S008: the briefing runs on the assembler path; no legacy context ────────

def test_legacy_briefing_context_is_gone():
    src = open("app.py").read()
    assert "def _build_coach_context" not in src
    assert "get_coach_response(" not in src
    assert "def get_coach_response" not in open("coach.py").read()


def test_briefing_never_defaults_checkin_scores(app_ctx, monkeypatch):
    app_, db = app_ctx
    u, client = _login(app_, db, "s008@test.com")
    import coach_assembler, coach_with_tools
    monkeypatch.setattr(coach_assembler, "build_filtered_context", lambda name: {})
    monkeypatch.setattr(coach_assembler, "assemble_prompt", lambda name, ctx: "SYS")
    seen = []
    monkeypatch.setattr(coach_with_tools, "coach_chat",
                        lambda uid, system, messages, **kw: (seen.append(messages[0]["content"]) or "ok"))
    r = client.post("/api/morning-briefing", json={"notes": "tired"})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert "5/10" not in seen[0] and "3/10" not in seen[0]
    assert "no numeric self-report" in seen[0]


# ── readiness chip: the word next to the score is the RISK level, say so ────

def test_readiness_chip_labels_risk_not_readiness():
    src = open("static/app.js").read()
    assert "overtraining risk" in src
    assert "Readiness ${escapeHtml(String(readinessData.risk_level" not in src


# ═════════════════════════ batch 3 ═════════════════════════

def test_context_build_failure_is_loud_not_a_stub(app_ctx, monkeypatch):
    """S062: the coach must never run on a {"week": 1} stub."""
    app_, db = app_ctx
    u, client = _login(app_, db, "s062@test.com")
    import coach_assembler
    def boom(name): raise RuntimeError("db down")
    monkeypatch.setattr(coach_assembler, "build_filtered_context", boom)
    import time; import app as appmod
    appmod._chat_rate_limit[u.id] = 0
    r = client.post("/api/chat", json={"message": "how am I doing"})
    assert r.status_code == 503, (r.status_code, r.get_data(as_text=True)[:200])
    assert "week\": 1" not in r.get_data(as_text=True)


def test_expired_exception_leaves_critical():
    from coach import _format_memories
    mems = [{"type": "exception", "content": "Exception granted: skip Saturday run through 2020-01-05 — travel", "date": "2020-01-02"},
            {"type": "exception", "content": "Exception granted: late weigh-in through 2999-01-01 — lab", "date": "2026-09-01"}]
    txt = _format_memories(mems)
    crit = txt.split("CRITICAL")[1].split("EXPIRED")[0]
    assert "late weigh-in" in crit and "(expires 2999-01-01)" in crit
    assert "skip Saturday run" not in crit
    assert "EXPIRED, history only" in txt and "skip Saturday run" in txt


def test_strength_planner_prompt_carries_recovery_rule():
    src = open("coach_planning_program.py").read()
    assert "RECOVERY CONTEXT (S058)" in src and "never cut lifting sets or load" in src


def test_readiness_line_carries_decision_rule():
    from coach_assembler import _format_athlete_data
    txt = _format_athlete_data({"readiness": {"score": 30, "risk_level": "high", "flags": ["HRV 30 vs 45"]}}, ["garmin"])
    assert "may NOT cut lifting sets" in txt and "[RUN]" in txt


def test_no_engine_language_in_coach_prompts():
    for f in ("coach.py", "coach_assembler.py"):
        src = open(f).read()
        assert "engine-computed" not in src
        assert "training engine's prescription" not in src


def test_all_none_wellness_fetch_is_not_a_sync(app_ctx):
    from garmin_sync import wellness_fields
    src = open("garmin_sync.py").read()
    assert 'result["wellness_empty"]' in src and "if not _any_metric:" in src


def test_model_ids_live_only_in_llm_client():
    import glob, re
    pat = re.compile(r'"claude-(opus|sonnet|haiku)-[0-9][^"]*"')
    for f in glob.glob("*.py") + glob.glob("coach_specialists/*.py"):
        if f == "llm_client.py":
            continue
        for i, line in enumerate(open(f), 1):
            assert not pat.search(line), (f, i, line.strip())


def test_chat_note_persists_confirmation(app_ctx):
    app_, db = app_ctx
    u, client = _login(app_, db, "s129@test.com")
    from models import ChatMessage
    r = client.post("/api/chat/note", json={"message": "yes", "mode": "planning"})
    assert r.status_code == 200
    row = ChatMessage.query.filter_by(user_id=u.id, content="yes").first()
    assert row and row.role == "user" and row.message_type == "planning"


def test_public_app_url_never_trusts_host_on_render(app_ctx, monkeypatch):
    app_, db = app_ctx
    import app as appmod
    monkeypatch.delenv("APP_URL", raising=False); monkeypatch.setenv("RENDER", "1")
    with app_.test_request_context(headers={"Host": "evil.example"}):
        with pytest.raises(RuntimeError):
            appmod._public_app_url()
    monkeypatch.setenv("APP_URL", "https://one2weeks-9ewf.onrender.com/")
    with app_.test_request_context(headers={"Host": "evil.example"}):
        assert appmod._public_app_url() == "https://one2weeks-9ewf.onrender.com"
    assert "request.host_url" not in open("app.py").read().split("def _public_app_url")[1].split("def _header_key_ok")[1]
