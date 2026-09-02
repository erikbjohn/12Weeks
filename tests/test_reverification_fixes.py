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


# ═════════════════════════ batch 4 ═════════════════════════

def test_one_clock_for_checkin_gate_and_weigh_in_dates():
    src = open("static/app.js").read()
    assert "'popup_' + key + '_' + todayStr()" not in src
    assert "date: todayStr(), weight:" not in src
    assert "date: todayStr(), sleep_quality:" not in src


def test_index_no_longer_nukes_caches_and_login_clears_data_cache():
    assert "caches.delete(n)" not in open("templates/index.html").read()
    assert "caches.delete" in open("templates/login.html").read()
    sw = open("static/sw.js").read()
    assert "data: { url: data.url || '/' }" in sw and "clients.openWindow(target)" in sw


def test_athlete_routes_never_echo_exception_text(app_ctx, monkeypatch):
    app_, db = app_ctx
    u, client = _login(app_, db, "s138b@test.com")
    import app as appmod
    def boom(*a, **k): raise RuntimeError("psycopg2 secret detail")
    monkeypatch.setattr(appmod, "compute_body_comp", boom, raising=False)
    for path in ("/api/stats/body-comp", "/api/stats/projection-inputs", "/api/stats/aerobic-efficiency"):
        r = client.get(path)
        assert "psycopg2" not in r.get_data(as_text=True) and "Traceback" not in r.get_data(as_text=True), path


def test_chat_coach_context_carries_z2_trend(app_ctx):
    app_, db = app_ctx
    u, _ = _login(app_, db, "s136@test.com")
    from models import RunLog
    from datetime import date, timedelta
    RunLog.query.filter_by(user_id=u.id).delete(); db.session.commit()
    for i in range(3):
        db.session.add(RunLog(user_id=u.id, week=1, day_idx=i, log_date=date(2026, 8, 24) + timedelta(days=i),
                              distance_miles=4.0, duration_min=40, avg_hr=130, source="garmin"))
    db.session.commit()
    with app_.test_request_context():
        from flask_login import login_user; login_user(u)
        from coach_assembler import _build_runs, _format_athlete_data
        ctx = _build_runs()
        assert ctx["z2_pace_trend"], ctx
        txt = _format_athlete_data(ctx, ["runs"])
    assert "<z2_pace_trend>" in txt


def test_run_planner_block_cites_pace_and_peak_hr(app_ctx):
    app_, db = app_ctx
    u, _ = _login(app_, db, "s067@test.com")
    from models import RunLog
    from datetime import date
    from coach_planning_runs import _build_run_history_block
    RunLog.query.filter_by(user_id=u.id).delete(); db.session.commit()
    db.session.add(RunLog(user_id=u.id, week=1, day_idx=0, log_date=date(2026, 8, 30), distance_miles=4.0,
                          duration_min=40, avg_hr=132, max_hr=168, source="garmin"))
    db.session.commit()
    txt = _build_run_history_block(u.id, 1, today=date(2026, 9, 1))
    assert "pace=10:00/mi" in txt and "peakHR=168" in txt


def test_sunday_recap_states_lifts_and_weigh_ins():
    src = open("weekly_report.py").read()
    assert '"lifts_done": metrics.get("workouts_completed")' in src and 'f"weigh-ins {data[\'weigh_in_days\']}/7"' in src


def test_specialists_have_timeouts():
    import glob
    for f in glob.glob("coach_specialists/*.py"):
        src = open(f).read()
        assert "max_retries=5" not in src, f


# ═════════════════════════ batch 5 ═════════════════════════

def test_rest_day_with_a_run_is_not_dimmed_and_planning_copy_not_monday():
    src = open("static/app.js").read()
    assert "d.isRest && !d.run ? ' rest'" in src
    assert "Monday weekly planning session" not in src


def test_api_post_has_a_timeout():
    src = open("static/app.js").read()
    assert "function _fetchWithTimeout" in src and "ctrl.abort()" in src
    body = src[src.index("function apiPost("):src.index("function apiPost(") + 400]
    assert "_fetchWithTimeout(url" in body


def test_logout_is_post_only(app_ctx):
    app_, db = app_ctx
    u, client = _login(app_, db, "s015@test.com")
    assert client.get("/logout").status_code == 405
    r = client.post("/logout")
    assert r.status_code in (302, 303)
    assert "window.location='/logout'" not in open("static/app.js").read()
    assert 'href="/logout"' not in open("templates/admin.html").read()


def test_single_use_invite_expires(app_ctx):
    app_, db = app_ctx
    from models import Invite
    from datetime import datetime, timezone, timedelta
    Invite.query.filter_by(code="old-code-xyz").delete(); db.session.commit()
    db.session.add(Invite(code="old-code-xyz", email_sent_to="new@test.com",
                          created_at=datetime.now(timezone.utc) - timedelta(days=30)))
    db.session.commit()
    client = app_.test_client()
    r = client.get("/invite/old-code-xyz", follow_redirects=False)
    assert r.status_code in (302, 303)
    with client.session_transaction() as s:
        flashes = s.get("_flashes") or []
    assert any("expired" in str(f).lower() for f in flashes), flashes


def test_move_sets_day_dry_run_writes_nothing(app_ctx, monkeypatch):
    app_, db = app_ctx
    u, client = _login(app_, db, "s132@test.com")
    from models import SetLog
    from datetime import date
    monkeypatch.setenv("ADMIN_API_KEY", "x" * 32)
    SetLog.query.filter_by(user_id=u.id).delete(); db.session.commit()
    db.session.add(SetLog(user_id=u.id, exercise_name="Barbell Bench Press", week=2, day_idx=4, set_number=1,
                          weight=100, reps=5, done=True, logged_date=date(2026, 8, 27)))
    db.session.commit()
    r = client.get("/api/debug/move-sets-day?email=s132@test.com&date=2026-08-27&from=4&to=3&dry_run=1",
                   headers={"X-Admin-Key": "x" * 32})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["dry_run"] is True and r.get_json()["moved_count"] == 1
    assert SetLog.query.filter_by(user_id=u.id).first().day_idx == 4


def test_overlay_errors_are_surfaced_client_side():
    src = open("static/app.js").read()
    assert "workoutData._overlay_errors" in src and "Some card data failed to load" in src


# ═════════════════════════ test sweep for PARTIALs that shipped code without a behavior test ═════

def test_on_curve_renders_and_suppresses_linear_projection():
    """S016/S035: the rendered prompt carries on_curve and never the straight-line numbers."""
    from coach_assembler import _format_athlete_data
    cs = {"goal_type": "cut", "current_weight": 212.0, "target_weight": 185.0, "on_curve": "behind",
          "curve_target_today": 210.4, "weeks_to_target": 9, "projected_week_12_weight": 199.0}
    txt = _format_athlete_data({"cut_status": cs}, ["cut_status"])
    assert "on_curve: behind" in txt and "curve_target_today: 210.4" in txt
    assert "weeks_to_target_at_pace" not in txt and "projected_week_12_weight" not in txt


def test_every_catalog_exercise_resolves_to_itself_or_nothing():
    """S131: the substring swap scan can never re-map a real catalog name."""
    from workout_data import EXERCISES, resolve_name
    from equipment_swaps import _lookup_swap
    bad = []
    for name in EXERCISES:
        hit = _lookup_swap(name)[0]
        if hit not in (name, resolve_name(name), None):   # an alias resolving to its canonical is exact, not fuzzy
            bad.append((name, hit))
    assert not bad, bad[:10]


def test_health_probe_unauthenticated_has_no_table_counts(app_ctx):
    app_, db = app_ctx
    client = app_.test_client()
    body = client.get("/api/debug/health").get_json()
    assert set(body.keys()) == {"ok", "commit"}, body


def test_sex_and_age_parser_table():
    """S099: bare 'm', a stray number, and a word containing 'f' must not change the answer."""
    from intake_profile import sex_and_age_from_intake
    convo = [{"role": "user", "content": "I'm 44 and male"},
             {"role": "user", "content": "I did 30 minutes of foam rolling"},   # stray number + 'f' word
             {"role": "assistant", "content": "female friend of mine is 22"}]   # coach turn, ignored
    sex, age = sex_and_age_from_intake(convo, default_sex="unknown", default_age=0)
    assert (sex, age) == ("male", 44), (sex, age)


def test_grocery_list_sinks_are_escaped():
    src = open("static/app.js").read()
    assert "${item.item}" not in src and "${item.total}" not in src and "${cat.category}" not in src


def test_prescription_marker_is_clamped_to_min_sets(app_ctx):
    """S054: a chat [PRESCRIPTION] with 2 sets lands as MIN_SETS, same rail as the planner."""
    app_, db = app_ctx
    u, _ = _login(app_, db, "s054@test.com")
    from models import WeeklyPrescription
    from coach_planning_program import MIN_SETS
    import app as appmod
    WeeklyPrescription.query.filter_by(user_id=u.id).delete(); db.session.commit()
    with app_.test_request_context():
        from flask_login import login_user; login_user(u)
        appmod._parse_coach_markers("[PRESCRIPTION: day=0, exercise=Barbell Bench Press, sets=2, reps=8, weight=135, reason=test]", u.id, 3)
    rx = WeeklyPrescription.query.filter_by(user_id=u.id, week=3, day_idx=0).first()
    assert rx is not None, "marker did not persist"
    assert rx.sets >= MIN_SETS, rx.sets


# ═════════════════════════ missing-test sweep (findings whose code shipped untested) ═════

def test_generate_status_ignores_a_stale_running_job(app_ctx):
    """S017: a hung job older than GEN_JOB_STALE_S must not read as 'running' forever."""
    app_, db = app_ctx
    u, client = _login(app_, db, "s017@test.com")
    import app as appmod, time
    with appmod._GEN_JOBS_LOCK:
        appmod._GEN_JOBS[(u.id, 9)] = {"status": "running", "started_at": time.time() - appmod.GEN_JOB_STALE_S - 60}
    r = client.get("/api/weekly-program/generate-status?week=9")
    assert r.status_code == 200
    assert r.get_json().get("status") != "running", r.get_json()


def test_dead_garmin_token_alerts_once_per_day(app_ctx, monkeypatch):
    """S037: an OAuth2 expired >2h ago logs ERROR and pushes exactly once (PushSent ledger)."""
    app_, db = app_ctx
    u, _ = _login(app_, db, "s037@test.com")
    import app as appmod, garmin_client, time
    from models import PushSent
    PushSent.query.filter_by(user_id=u.id).delete(); db.session.commit()
    monkeypatch.setattr(garmin_client, "stored_oauth2_expires_at", lambda uid: time.time() - 3 * 3600)
    sent = []
    monkeypatch.setattr(appmod, "push_to_user", lambda uid, title, body, **k: sent.append(body) or 1)
    appmod._garmin_dead_token_alert(u.id)
    appmod._garmin_dead_token_alert(u.id)
    rows = PushSent.query.filter_by(user_id=u.id, kind="garmin_auth").all()
    assert len(rows) == 1 and len(sent) == 1 and "Garmin auth expired" in sent[0]


def test_today_status_render_shows_prescribed_run_beside_actual():
    """S041: the debrief sees plan and actual side by side."""
    from coach_assembler import _format_athlete_data
    ts = {"workout_state": "not_started", "run_logged": True, "run_distance_today": 4.55,
          "run_duration_today": 50, "run_avg_hr_today": 132, "run_detail": "50 min easy Z2, HR 120-140",
          "run_label": "Easy Z2", "run_duration": "50 min"}
    txt = _format_athlete_data({"today_status": ts}, ["today_status"])
    assert "run: DONE" in txt and "run_prescribed: Easy Z2 50 min — 50 min easy Z2" in txt


def test_chase_body_is_none_when_nothing_is_owed(app_ctx):
    """S046: the 09:30 chase sends nothing when the weigh-in is logged and no morning dose is open."""
    app_, db = app_ctx
    u, _ = _login(app_, db, "s046@test.com")
    import app as appmod
    from models import BodyWeight, PeptideDose
    from datetime import date
    d = date(2026, 9, 1)
    BodyWeight.query.filter_by(user_id=u.id).delete(); PeptideDose.query.filter_by(user_id=u.id).delete(); db.session.commit()
    assert appmod._chase_body(u.id, d) == "No weigh-in yet."
    db.session.add(BodyWeight(user_id=u.id, log_date=d, weight_lbs=210.0)); db.session.commit()
    assert appmod._chase_body(u.id, d) is None
    db.session.add(PeptideDose(user_id=u.id, date=d, compound="Retatrutide", dose_mg=2.0, time="07:00", event_type="dose")); db.session.commit()
    assert "1 dose unchecked: Retatrutide." in appmod._chase_body(u.id, d)


def test_sync_activities_maps_peak_hr(app_ctx):
    """S047: Garmin maxHR lands on GarminActivity + RunLog.max_hr."""
    app_, db = app_ctx
    u, _ = _login(app_, db, "s047@test.com")
    from models import AppState, RunLog, GarminActivity
    from datetime import date
    from garmin_sync import sync_activities
    AppState.query.filter_by(user_id=u.id).delete(); RunLog.query.filter_by(user_id=u.id).delete()
    GarminActivity.query.filter_by(user_id=u.id).delete(); db.session.commit()
    db.session.add(AppState(user_id=u.id, start_date=date(2026, 8, 10), current_week=4)); db.session.commit()
    class _GC:
        def get_activities_between(self, a, b):
            return [{"activityId": 991, "activityType": {"typeKey": "running"}, "startTimeLocal": "2026-08-31 06:10:00",
                     "distance": 7242.0, "duration": 3000.0, "averageHR": 132, "maxHR": 172, "elevationGain": 30.0,
                     "activityName": "Z2 50"}]
    sync_activities(_GC(), u.id, days_back=3, today=date(2026, 9, 1))
    act = GarminActivity.query.filter_by(user_id=u.id).first()
    assert act and act.max_hr == 172
    rl = RunLog.query.filter_by(user_id=u.id, log_date=date(2026, 8, 31)).first()
    assert rl and rl.max_hr == 172 and rl.source == "garmin"


def test_protocol_status_render_names_unchecked_doses():
    """S059: a scheduled, past-due, unchecked dose is named once in the prompt."""
    from coach_assembler import _format_athlete_data
    ps = {"summary": [{"compound": "Retatrutide", "dose_mg": 2.0, "time": "07:00", "taken": False}],
          "today_unchecked": [{"compound": "Retatrutide", "time": "07:00"}]}
    txt = _format_athlete_data({"protocol_status": ps}, ["protocol_status"])
    assert "Retatrutide 2.0mg @ 07:00 — UNCHECKED" in txt
    assert "today_unchecked_past_due: 1 — Retatrutide @ 07:00" in txt


def test_day_resolver_is_memoized_per_request(app_ctx):
    """S103: the second resolve of the same day in one request issues zero SQL."""
    app_, db = app_ctx
    u, _ = _login(app_, db, "s103@test.com")
    from sqlalchemy import event
    from coach_assembler import _resolve_workout_for_day
    counts = []
    def _count(conn, cursor, statement, parameters, context, executemany): counts.append(statement)
    event.listen(db.engine, "before_cursor_execute", _count)
    try:
        with app_.test_request_context():
            from flask_login import login_user; login_user(u)
            _resolve_workout_for_day(1, 0)
            n1 = len(counts)
            _resolve_workout_for_day(1, 0)
            n2 = len(counts)
    finally:
        event.remove(db.engine, "before_cursor_execute", _count)
    assert n1 > 0 and n2 == n1, (n1, n2)


def test_source_pins_for_shipped_but_untested_partials():
    """S093/S108/S141/S159/S161: the mechanism each closure claimed is still in the source."""
    app_src = open("app.py").read()
    reg = app_src[app_src.index("def api_regenerate_meals"):app_src.index("def api_regenerate_meals") + 6000]
    assert "day_date(" in reg, "S093: regenerate must derive the week from AppState.start_date, not the calendar Monday"
    ca = open("coach_assembler.py").read()
    ts = ca[ca.index("def _build_today_status"):ca.index("def _build_today_status") + 4000]
    assert "start_date" in ts, "S108: today_status must gate rows on block start_date"
    cd = ca[ca.index("def _build_completed_days"):ca.index("def _build_completed_days") + 4000]
    assert "_resolve_workout_for_day(week, di)" in cd, "S161: completed_days title from the resolver, not the template"
    js = open("static/app.js").read()
    assert "_weightsCache && _weightsCache[exName] && _weightsCache[exName].current > 0" in js, "S141: typo guard reads the live cache"
    assert "window._weightsCache[exName]" not in js
    assert "Fast day. Water, black coffee, electrolytes only." not in js, "S159: no hardcoded fast-day literal"
    assert "escapeHtml(String(activePlan.note))" in js


# ═════════════════════════ mechanism batch ═════════════════════════

def test_schedule_gap_heals_from_coach_prescriptions(app_ctx):
    """S028: a week with coach lifts but no WeeklyDaySchedule rows gets them back."""
    app_, db = app_ctx
    u, _ = _login(app_, db, "s028@test.com")
    from models import WeeklyPrescription, WeeklyDaySchedule
    import app as appmod
    WeeklyPrescription.query.filter_by(user_id=u.id).delete(); WeeklyDaySchedule.query.filter_by(user_id=u.id).delete(); db.session.commit()
    for i, ex in enumerate(["Barbell Back Squat", "Romanian Deadlift", "Leg Press"]):
        db.session.add(WeeklyPrescription(user_id=u.id, week=7, day_idx=0, exercise_order=i, exercise_name=ex,
                                          sets=3, reps="8", target_weight=100, source="coach"))
    db.session.commit()
    with app_.test_request_context():
        from flask_login import login_user; login_user(u)
        added = appmod._fill_missing_week_schedule(u.id, 7)
    assert added == list(range(7))
    d0 = WeeklyDaySchedule.query.filter_by(user_id=u.id, week=7, day_idx=0).first()
    assert d0 and not d0.is_rest and d0.lift_name and "quads" in (d0.muscle_groups or [])
    d1 = WeeklyDaySchedule.query.filter_by(user_id=u.id, week=7, day_idx=1).first()
    assert d1.is_rest
    assert appmod._fill_missing_week_schedule(u.id, 7) == []   # idempotent


def test_temperature_threaded_to_multiagent_and_specialists():
    src = open("coach_multi_agent.py").read()
    assert src.count('"temperature": persona["temperature"]') == 2
    import glob
    for f in ("coach_specialists/strength.py", "coach_specialists/running.py", "coach_specialists/nutritionist.py"):
        assert '"temperature": _PERSONA["temperature"]' in open(f).read(), f
    assert '"temperature": fm.get("temperature")' in open("coach_specialists/loader.py").read()


def test_invite_request_throttle_is_db_backed(app_ctx):
    app_, db = app_ctx
    from models import SystemFlag
    SystemFlag.query.filter(SystemFlag.key.like("invite_req:%")).delete(synchronize_session=False); db.session.commit()
    import app as appmod
    appmod._invite_request_attempts.clear()
    client = app_.test_client()
    codes = [client.post("/api/request-invite", json={"name": "x", "email": "a@b.co"}).status_code for _ in range(4)]
    assert codes[-1] == 429, codes
    assert SystemFlag.query.filter(SystemFlag.key.like("invite_req:%")).first() is not None


def test_div_controls_are_keyboard_reachable():
    import re
    src = open("static/app.js").read()
    bare = [m.group(0) for m in re.finditer(r"<div [^>]*onclick=", src) if "role=" not in m.group(0)]
    assert not bare, bare[:3]
    assert "t.getAttribute('role') === 'button'" in src
    assert "renderSundaySection" not in src   # S134 dead chain


def test_today_status_carries_executed_plan_flag():
    from coach_assembler import _format_athlete_data
    ts = {"workout_state": "not_started", "run_logged": True, "run_distance_today": 4.0, "run_duration_today": 40,
          "run_followed_pushed_plan": True, "run_activities_today": [{"start": "06:10", "followed_plan": True, "name": "12W Wk3 Tue"}]}
    txt = _format_athlete_data({"today_status": ts}, ["today_status"])
    assert "run_executed_pushed_plan: yes" in txt


def test_claims_block_is_gated_on_multiagent(monkeypatch):
    from coach_assembler import _format_athlete_data
    monkeypatch.delenv("MULTIAGENT_ENABLED", raising=False)
    txt = _format_athlete_data({"today_status": {"workout_state": "not_started"}}, ["today_status"])
    assert "claim_id" not in txt and "<claims>" not in txt


def test_llm_usage_is_recorded_and_queryable(app_ctx, monkeypatch):
    app_, db = app_ctx
    from llm_client import record_usage
    from models import LlmUsage
    class _U: input_tokens = 1200; output_tokens = 80; cache_read_input_tokens = 900; cache_creation_input_tokens = 0
    class _R: usage = _U(); model = "claude-test"
    LlmUsage.query.delete(); db.session.commit()
    record_usage(_R(), "unit_test")
    assert LlmUsage.query.filter_by(agent="unit_test").count() == 1
    monkeypatch.setenv("ADMIN_READ_KEY", "r" * 32)
    r = app_.test_client().get("/api/admin/debug/llm-usage?days=1", headers={"X-Admin-Key": "r" * 32})
    assert r.status_code == 200, r.get_data(as_text=True)
    row = [x for x in r.get_json()["rows"] if x["agent"] == "unit_test"][0]
    assert row["calls"] == 1 and row["cache_hit_ratio"] == round(900 / 2100, 3)


def test_every_messages_create_site_records_usage():
    import glob, re
    for f in glob.glob("*.py") + glob.glob("coach_specialists/*.py"):
        if f in ("llm_client.py",):
            continue
        src = open(f).read()
        n_create = len(re.findall(r"\.messages\.create\(", src))
        if not n_create:
            continue
        n_rec = src.count("record_usage(") + (src.count("_log_usage(") - 1 if "def _log_usage(" in src else 0)
        assert n_rec >= n_create, (f, n_create, n_rec)


def test_swap_refresh_fetches_one_week_and_onboarding_is_one_call(app_ctx):
    src = open("static/app.js").read()
    fn = src[src.index("async function refreshWorkoutDataAfterSwap"):src.index("async function refreshWorkoutDataAfterSwap") + 900]
    assert "fetch('/api/workouts/' + currentWeek)" in fn and "fetch('/api/workouts')" not in fn
    assert "fetch('/api/onboarding/status')" in src
    app_, db = app_ctx
    u, client = _login(app_, db, "s073@test.com")
    r = client.get("/api/onboarding/status")
    assert r.status_code == 200 and r.get_json()["complete"] is False


def test_judge_batch_uses_batches_api_with_cached_system():
    src = open("tests/coach_audit/judge.py").read()
    assert "client.messages.batches.create(requests=part)" in src
    assert '"cache_control": {"type": "ephemeral"}' in src
    assert "out[r.custom_id]" in src


# ═════════════════════════ swapped-slot targets (found in Erik's data 2026-09-01) ═════

def test_next_targets_use_the_exercises_own_history_not_a_swap_sibling(app_ctx):
    """KB Swing that replaced an RDL must progress from KB Swing rows (30 lb), never inherit RDL 135."""
    app_, db = app_ctx
    u, _ = _login(app_, db, "kbswing@test.com")
    from models import SetLog
    from datetime import date
    from training_engine import compute_next_targets
    SetLog.query.filter_by(user_id=u.id).delete(); db.session.commit()
    for i in range(4):
        db.session.add(SetLog(user_id=u.id, exercise_name="Romanian Deadlift", week=4, day_idx=1, set_number=i,
                              weight=135, reps=10, done=True, logged_date=date(2026, 9, 1)))
        db.session.add(SetLog(user_id=u.id, exercise_name="KB Swing", week=3, day_idx=5, set_number=i,
                              weight=30, reps=10, done=True, logged_date=date(2026, 8, 29)))
    db.session.commit()
    t = compute_next_targets(u.id, "KB Swing", 5, 1, allow_llm=False)
    assert t["target_weight"] is not None and t["target_weight"] <= 45, t


def test_next_targets_fall_back_to_scaled_sibling_history_when_none_of_its_own(app_ctx):
    app_, db = app_ctx
    u, _ = _login(app_, db, "rdlfallback@test.com")
    from models import SetLog
    from datetime import date
    from training_engine import compute_next_targets
    SetLog.query.filter_by(user_id=u.id).delete(); db.session.commit()
    for i in range(4):
        db.session.add(SetLog(user_id=u.id, exercise_name="Single-Leg Romanian Deadlift", week=2, day_idx=1, set_number=i,
                              weight=50, reps=10, done=True, logged_date=date(2026, 8, 18)))
    db.session.commit()
    t = compute_next_targets(u.id, "Romanian Deadlift", 4, 1, allow_llm=False)
    assert t["target_weight"] is not None and t["target_weight"] >= 50, t


def test_today_sets_target_comes_from_prescription_not_setlog_column(app_ctx):
    app_, db = app_ctx
    u, _ = _login(app_, db, "todaysets@test.com")
    from models import SetLog, WeeklyPrescription, AppState
    import coach_assembler
    from datetime import date
    today = date(2026, 9, 1)
    AppState.query.filter_by(user_id=u.id).delete(); SetLog.query.filter_by(user_id=u.id).delete()
    WeeklyPrescription.query.filter_by(user_id=u.id).delete(); db.session.commit()
    db.session.add(AppState(user_id=u.id, start_date=date(2026, 8, 10), current_week=4))
    db.session.add(WeeklyPrescription(user_id=u.id, week=4, day_idx=1, exercise_order=0, exercise_name="KB Swing",
                                      sets=4, reps="10", target_weight=40, source="coach"))
    db.session.add(SetLog(user_id=u.id, exercise_name="KB Swing", week=4, day_idx=1, set_number=0, weight=35, reps=10,
                          done=True, logged_date=today, target_weight=145, target_reps=10))
    db.session.commit()
    with app_.test_request_context():
        from flask_login import login_user; login_user(u)
        import unittest.mock as um
        with um.patch.object(coach_assembler, "_user_today", lambda: today), \
             um.patch.object(coach_assembler, "_current_week", lambda: 4):
            out = coach_assembler._build_today_sets()["today_sets"]
    assert out["KB Swing"][0]["target_weight"] == 40
    txt = coach_assembler._format_athlete_data({"today_sets": out}, ["today_sets"])
    assert "145" not in txt and "target: 40" in txt


def test_form_checkin_never_defaults_blank_scores():
    src = open("static/app.js").read()
    assert "|| 5," not in src.split("function submitMorningCheckin")[1][:1500]
    assert "|| 3," not in src.split("function submitMorningCheckin")[1][:1500]
    assert "function _mcVal" in src and ".filter(r => r.val != null)" in src


def test_regen_replaces_only_days_the_coach_returned(app_ctx, monkeypatch):
    """S122/S024: a coach reply covering days 0-4 must leave days 5-6 untouched."""
    app_, db = app_ctx
    u, _ = _login(app_, db, "s122@test.com")
    from models import AppState, WeeklyPrescription, UserEquipment, PhysicalAssessment, TrainingGoal
    from datetime import date
    import coach_planning_program, coach_planning_runs, coach_planning_meals
    import app as appmod
    AppState.query.filter_by(user_id=u.id).delete(); WeeklyPrescription.query.filter_by(user_id=u.id).delete()
    UserEquipment.query.filter_by(user_id=u.id).delete(); PhysicalAssessment.query.filter_by(user_id=u.id).delete()
    TrainingGoal.query.filter_by(user_id=u.id).delete(); db.session.commit()
    db.session.add(AppState(user_id=u.id, start_date=date(2026, 8, 10), current_week=4))
    db.session.add(UserEquipment(user_id=u.id, available_equipment=["barbell", "dumbbells", "cable_machine"], completed=True))
    db.session.add(PhysicalAssessment(user_id=u.id, has_gym=True, completed=True))
    db.session.add(TrainingGoal(user_id=u.id, goal_type="cut", daily_calories=2000, protein_grams=200, target_weight=185))
    for d in range(7):
        db.session.add(WeeklyPrescription(user_id=u.id, week=5, day_idx=d, exercise_order=0,
                                          exercise_name=["Barbell Bench Press", "Barbell Back Squat", "Lat Pulldown",
                                                         "Barbell OHP", "Romanian Deadlift", "Landmine Press", "Face Pull"][d],
                                          sets=4, reps="8", target_weight=100, source="coach"))
    db.session.commit()
    prog = {d: [{"exercise": "Incline DB Press", "sets": 3, "reps": "10", "weight": 40, "rest": "90s", "why": "t"}] for d in range(5)}
    monkeypatch.setattr(coach_planning_program, "generate_week_program", lambda **kw: (prog, [], {"deload": False}))
    monkeypatch.setattr(coach_planning_runs, "generate_week_runs", lambda **kw: {})
    monkeypatch.setattr(coach_planning_meals, "generate_week_meals", lambda **kw: {})
    with app_.test_request_context():
        from flask_login import login_user; login_user(u)
        out = appmod._weekly_generation_impl(5, True, None, {}, inline_llm=False)
    names = {r.day_idx: r.exercise_name for r in WeeklyPrescription.query.filter_by(user_id=u.id, week=5, source="coach").all()}
    assert names.get(5) == "Landmine Press" and names.get(6) == "Face Pull", names
    assert all(names.get(d) == "Incline DB Press" for d in range(5)), (names, (out or {}).get("coach_failures"))
