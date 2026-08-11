"""Test admin debug endpoints for served-state verification.

Covers:
- GET /api/debug/serve-as-user?email=&path=
  - Allowlist enforcement: /api/workouts, /api/meals, /api/progress, etc.
  - 403 on non-allowlisted paths
  - 404 on unknown email
  - 401 on missing admin key
  - Returns {"email", "path", "status_code", "payload"}
  - GET only (no POST)

- GET /api/debug/coach-context?email=
  - Impersonated request context: calls section builders
  - Returns {"email", "context": {cut_status, protocol_status, lift_trend, garmin, today_status}}
  - Each builder wrapped in try/except: {"error": "..."} on failure
  - Preserves None semantics (absent keys when block is None)
  - 404 on unknown email
  - 401 on missing admin key
"""
import pytest
import os


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def _login_via_session(app_, email):
    """Login via test_client session (impersonation pattern for serve-as-user)."""
    from models import User
    u = User.query.filter_by(email=email).first()
    if not u:
        u = User(email=email)
        from app import db
        db.session.add(u)
        db.session.commit()
    client = app_.test_client()
    with client.session_transaction() as s:
        s["_user_id"] = str(u.id)
        s["_fresh"] = True
    return u, client


def _seed_user_with_data(email):
    """Create a user with cut goal and body weight data for testing."""
    from app import db
    from models import User, TrainingGoal, BodyWeight, AppState
    from datetime import date, timedelta

    u = User.query.filter_by(email=email).first()
    if not u:
        u = User(email=email)
        db.session.add(u)

    # Ensure clean state
    TrainingGoal.query.filter_by(user_id=u.id).delete()
    BodyWeight.query.filter_by(user_id=u.id).delete()
    AppState.query.filter_by(user_id=u.id).delete()

    # Add cut goal
    goal = TrainingGoal(
        user_id=u.id,
        goal_type="cut",
        target_weight=185,
        tdee=2500,
        daily_calories=1500
    )
    db.session.add(goal)

    # Add body weight history
    today = date.today()
    for i in range(5):
        bw = BodyWeight(
            user_id=u.id,
            log_date=today - timedelta(days=i),
            weight_lbs=220 - i
        )
        db.session.add(bw)

    # Add AppState for current week calculation
    state = AppState(user_id=u.id, current_week=6, start_date=today - timedelta(days=35))
    db.session.add(state)

    db.session.commit()
    return u


def _seed_user_with_protocol(email):
    """Create a user with peptide protocol data."""
    from app import db
    from models import User, PeptideDose
    from datetime import date

    u = User.query.filter_by(email=email).first()
    if not u:
        u = User(email=email)
        db.session.add(u)

    # Clean protocol data
    PeptideDose.query.filter_by(user_id=u.id).delete()

    # Add a dose
    dose = PeptideDose(
        user_id=u.id,
        compound="Retatrutide",
        date=date.today(),
        time="08:00",
        event_type="Injection",
        dose_mg=0.5
    )
    db.session.add(dose)
    db.session.commit()
    return u


# ── serve-as-user tests ──────────────────────────────────────────────────────

def test_serve_as_user_allowlisted_path(app_ctx, monkeypatch):
    """serve-as-user with allowlisted path returns real payload."""
    app_, db = app_ctx
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")

    u, client = _login_via_session(app_, "serve-test-1@test.com")

    with app_.test_client() as c:
        r = c.get(
            "/api/debug/serve-as-user?email=serve-test-1@test.com&path=/api/workouts",
            headers={"X-Admin-Key": "test-key"}
        )

    assert r.status_code == 200, r.get_json()
    data = r.get_json()
    assert data["email"] == "serve-test-1@test.com"
    assert data["path"] == "/api/workouts"
    assert "status_code" in data
    assert "payload" in data


def test_serve_as_user_non_allowlisted_path_403(app_ctx, monkeypatch):
    """serve-as-user rejects non-allowlisted paths with 403."""
    app_, db = app_ctx
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")

    with app_.test_client() as c:
        r = c.get(
            "/api/debug/serve-as-user?email=serve-test-2@test.com&path=/api/admin/something",
            headers={"X-Admin-Key": "test-key"}
        )

    assert r.status_code == 403
    data = r.get_json()
    assert "path not allowlisted" in data.get("error", "").lower()


def test_serve_as_user_path_prefix_matching(app_ctx, monkeypatch):
    """serve-as-user allows query strings with allowlisted prefix."""
    app_, db = app_ctx
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")

    u, client = _login_via_session(app_, "serve-test-3@test.com")

    with app_.test_client() as c:
        # /api/progress is in the allowlist
        r = c.get(
            "/api/debug/serve-as-user?email=serve-test-3@test.com&path=/api/progress?some_param=value",
            headers={"X-Admin-Key": "test-key"}
        )

    assert r.status_code == 200, r.get_json()


def test_serve_as_user_unknown_email_404(app_ctx, monkeypatch):
    """serve-as-user returns 404 for unknown email."""
    app_, db = app_ctx
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")

    with app_.test_client() as c:
        r = c.get(
            "/api/debug/serve-as-user?email=nonexistent@test.com&path=/api/workouts",
            headers={"X-Admin-Key": "test-key"}
        )

    assert r.status_code == 404
    data = r.get_json()
    assert "not found" in data.get("error", "").lower()


def test_serve_as_user_no_admin_key_401(app_ctx):
    """serve-as-user returns 401 without admin key."""
    app_, db = app_ctx

    with app_.test_client() as c:
        r = c.get(
            "/api/debug/serve-as-user?email=serve-test-4@test.com&path=/api/workouts"
        )

    # Should be 401 or 403 depending on admin_required logic
    assert r.status_code in (401, 403)


def test_serve_as_user_invalid_path_prefix_403(app_ctx, monkeypatch):
    """serve-as-user rejects path not matching any allowlist prefix."""
    app_, db = app_ctx
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")

    with app_.test_client() as c:
        r = c.get(
            "/api/debug/serve-as-user?email=serve-test-5@test.com&path=/etc/passwd",
            headers={"X-Admin-Key": "test-key"}
        )

    assert r.status_code == 403


# ── coach-context tests ──────────────────────────────────────────────────────

def test_coach_context_cut_status_non_null(app_ctx, monkeypatch):
    """coach-context returns non-null cut_status for seeded cut-goal user."""
    app_, db = app_ctx
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")

    email = "coach-cut@test.com"
    _seed_user_with_data(email)

    with app_.test_client() as c:
        r = c.get(
            f"/api/debug/coach-context?email={email}",
            headers={"X-Admin-Key": "test-key"}
        )

    assert r.status_code == 200, r.get_json()
    data = r.get_json()
    assert data["email"] == email
    assert "context" in data
    context = data["context"]
    assert "cut_status" in context
    assert context["cut_status"] is not None
    assert "current_weight" in context["cut_status"]


def test_coach_context_protocol_status_non_null(app_ctx, monkeypatch):
    """coach-context returns protocol_status block for seeded PeptideDose rows."""
    app_, db = app_ctx
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")

    email = "coach-protocol@test.com"
    _seed_user_with_protocol(email)

    with app_.test_client() as c:
        r = c.get(
            f"/api/debug/coach-context?email={email}",
            headers={"X-Admin-Key": "test-key"}
        )

    assert r.status_code == 200, r.get_json()
    data = r.get_json()
    assert data["email"] == email
    context = data["context"]
    assert "protocol_status" in context
    assert context["protocol_status"] is not None


def test_coach_context_protocol_status_none_when_empty(app_ctx, monkeypatch):
    """coach-context returns protocol_status: None when no protocol rows."""
    app_, db = app_ctx
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")

    # Create a fresh user with no protocol data
    email = "coach-no-protocol@test.com"
    from models import User
    u = User.query.filter_by(email=email).first()
    if not u:
        u = User(email=email)
        db.session.add(u)
        db.session.commit()

    with app_.test_client() as c:
        r = c.get(
            f"/api/debug/coach-context?email={email}",
            headers={"X-Admin-Key": "test-key"}
        )

    assert r.status_code == 200, r.get_json()
    data = r.get_json()
    context = data["context"]
    # When no protocol rows exist, protocol_status should be None (key may not be present or be None)
    assert context.get("protocol_status") is None or "protocol_status" not in context


def test_coach_context_includes_all_builders(app_ctx, monkeypatch):
    """coach-context includes all required builder blocks."""
    app_, db = app_ctx
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")

    email = "coach-all@test.com"
    _seed_user_with_data(email)

    with app_.test_client() as c:
        r = c.get(
            f"/api/debug/coach-context?email={email}",
            headers={"X-Admin-Key": "test-key"}
        )

    assert r.status_code == 200, r.get_json()
    data = r.get_json()
    context = data["context"]
    # All these builder keys should be present
    for key in ["cut_status", "protocol_status", "lift_trend", "garmin", "today_status"]:
        assert key in context, f"Missing builder key: {key}"


def test_coach_context_builder_error_handling(app_ctx, monkeypatch):
    """coach-context wraps builder exceptions in error objects, returns 200."""
    app_, db = app_ctx
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")

    email = "coach-error@test.com"
    from models import User
    u = User.query.filter_by(email=email).first()
    if not u:
        u = User(email=email)
        from app import db as flask_db
        flask_db.session.add(u)
        flask_db.session.commit()

    # Monkeypatch a builder to raise an error
    from coach_assembler import _SECTION_BUILDERS
    original_cut_status = _SECTION_BUILDERS.get("cut_status")

    def broken_cut_status():
        raise ValueError("Intentional test error")

    _SECTION_BUILDERS["cut_status"] = broken_cut_status

    try:
        with app_.test_client() as c:
            r = c.get(
                f"/api/debug/coach-context?email={email}",
                headers={"X-Admin-Key": "test-key"}
            )

        assert r.status_code == 200  # Should NOT be 500
        data = r.get_json()
        context = data["context"]
        # cut_status should have an error key
        assert isinstance(context["cut_status"], dict)
        assert "error" in context["cut_status"]
        # Other builders should still be present
        assert "today_status" in context
    finally:
        # Restore
        if original_cut_status:
            _SECTION_BUILDERS["cut_status"] = original_cut_status


def test_coach_context_unknown_email_404(app_ctx, monkeypatch):
    """coach-context returns 404 for unknown email."""
    app_, db = app_ctx
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")

    with app_.test_client() as c:
        r = c.get(
            "/api/debug/coach-context?email=nonexistent-coach@test.com",
            headers={"X-Admin-Key": "test-key"}
        )

    assert r.status_code == 404


def test_coach_context_no_admin_key_401(app_ctx):
    """coach-context returns 401 without admin key."""
    app_, db = app_ctx

    with app_.test_client() as c:
        r = c.get("/api/debug/coach-context?email=some@test.com")

    assert r.status_code in (401, 403)


# ── Method enforcement tests (POST → 405) ────────────────────────────────────

def test_serve_as_user_post_405(app_ctx, monkeypatch):
    """serve-as-user rejects POST with 405."""
    app_, db = app_ctx
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")

    with app_.test_client() as c:
        r = c.post(
            "/api/debug/serve-as-user?email=test@test.com&path=/api/workouts",
            headers={"X-Admin-Key": "test-key"}
        )

    assert r.status_code == 405


def test_coach_context_post_405(app_ctx, monkeypatch):
    """coach-context rejects POST with 405."""
    app_, db = app_ctx
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")

    with app_.test_client() as c:
        r = c.post(
            "/api/debug/coach-context?email=test@test.com",
            headers={"X-Admin-Key": "test-key"}
        )

    assert r.status_code == 405


# ── Allowlist boundary enforcement tests ───────────────────────────────────

def test_serve_as_user_allowlist_exact_match(app_ctx, monkeypatch):
    """serve-as-user allows exact allowlist match."""
    app_, db = app_ctx
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")

    u, _ = _login_via_session(app_, "boundary-exact@test.com")

    with app_.test_client() as c:
        r = c.get(
            "/api/debug/serve-as-user?email=boundary-exact@test.com&path=/api/workouts",
            headers={"X-Admin-Key": "test-key"}
        )

    assert r.status_code == 200


def test_serve_as_user_allowlist_with_query_string(app_ctx, monkeypatch):
    """serve-as-user allows path with query string (?pattern)."""
    app_, db = app_ctx
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")

    u, _ = _login_via_session(app_, "boundary-query@test.com")

    with app_.test_client() as c:
        r = c.get(
            "/api/debug/serve-as-user?email=boundary-query@test.com&path=/api/workouts?week=6",
            headers={"X-Admin-Key": "test-key"}
        )

    assert r.status_code == 200, r.get_json()


def test_serve_as_user_allowlist_rejects_substring_match(app_ctx, monkeypatch):
    """serve-as-user rejects substring matches like /api/workoutsEVIL."""
    app_, db = app_ctx
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")

    with app_.test_client() as c:
        r = c.get(
            "/api/debug/serve-as-user?email=test@test.com&path=/api/workoutsEVIL",
            headers={"X-Admin-Key": "test-key"}
        )

    assert r.status_code == 403
    assert "not allowlisted" in r.get_json().get("error", "").lower()


def test_serve_as_user_allowlist_rejects_superpath(app_ctx, monkeypatch):
    """serve-as-user rejects /api/progress/dashboardx (not just /api/progress,
    and not a substring/prefix match against the now-allowlisted
    /api/progress/dashboard either)."""
    app_, db = app_ctx
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")

    with app_.test_client() as c:
        r = c.get(
            "/api/debug/serve-as-user?email=test@test.com&path=/api/progress/dashboardx",
            headers={"X-Admin-Key": "test-key"}
        )

    # /api/progress/dashboardx is neither /api/progress nor /api/progress/dashboard
    # (exact match requires equality or a "?query" suffix) -- REJECTED by the
    # boundary rule.
    assert r.status_code == 403, r.get_json()


# ── Engagement-features allowlist additions (Task 9) ────────────────────────

def test_serve_as_user_protocol_calendar_path(app_ctx, monkeypatch):
    """serve-as-user proxies /api/protocol/calendar for a seeded user."""
    app_, db = app_ctx
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")

    u, client = _login_via_session(app_, "serve-test-calendar@test.com")

    with app_.test_client() as c:
        r = c.get(
            "/api/debug/serve-as-user?email=serve-test-calendar@test.com&path=/api/protocol/calendar",
            headers={"X-Admin-Key": "test-key"}
        )

    assert r.status_code == 200, r.get_json()
    data = r.get_json()
    assert data["email"] == "serve-test-calendar@test.com"
    assert data["path"] == "/api/protocol/calendar"
    assert data["status_code"] == 200


def _seed_block3_scoreboard_user(db, email):
    """Seed a minimal block-3 user (TrainingGoal + AppState.start_date +
    BodyWeight + the block3 SystemFlags) so /api/progress/dashboard serves a
    non-null 'scoreboard' key. Cribbed from tests/test_scoreboard.py's
    _seed_goal_and_state / _set_weights / _set_block3_flags helpers."""
    from models import User, TrainingGoal, AppState, BodyWeight, SystemFlag
    from datetime import date

    u = User.query.filter_by(email=email).first()
    if not u:
        u = User(email=email)
        db.session.add(u)
        db.session.commit()

    TrainingGoal.query.filter_by(user_id=u.id).delete()
    AppState.query.filter_by(user_id=u.id).delete()
    BodyWeight.query.filter_by(user_id=u.id).delete()
    db.session.commit()

    start = date(2026, 8, 10)
    db.session.add(TrainingGoal(
        user_id=u.id, goal_type="recomp", target_weight=195.0,
        daily_calories=1800, tdee=2800,
    ))
    db.session.add(AppState(user_id=u.id, current_week=1, start_date=start))
    db.session.add(BodyWeight(user_id=u.id, weight_lbs=220.0, log_date=start))
    db.session.commit()

    SystemFlag.query.filter(
        SystemFlag.key.in_(["projection_mode", "block3_anchor"])
    ).delete(synchronize_session=False)
    db.session.add(SystemFlag(key="projection_mode", value="piecewise_block3"))
    db.session.add(SystemFlag(key="block3_anchor", value="220.0"))
    db.session.commit()
    return u


def test_serve_as_user_progress_dashboard_path(app_ctx, monkeypatch):
    """serve-as-user proxies /api/progress/dashboard for a block-3-seeded user
    and the JSON payload includes the 'scoreboard' key (final review I-4: the
    allowlist previously rejected this path entirely, making the mandated
    post-deploy served-check of the block-3 scoreboard impossible)."""
    app_, db = app_ctx
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")

    email = "serve-test-dashboard@test.com"
    _seed_block3_scoreboard_user(db, email)

    try:
        with app_.test_client() as c:
            r = c.get(
                f"/api/debug/serve-as-user?email={email}&path=/api/progress/dashboard",
                headers={"X-Admin-Key": "test-key"}
            )

        assert r.status_code == 200, r.get_json()
        data = r.get_json()
        assert data["email"] == email
        assert data["path"] == "/api/progress/dashboard"
        assert data["status_code"] == 200
        assert "scoreboard" in data["payload"]
        assert data["payload"]["scoreboard"] is not None
    finally:
        # SystemFlag is a GLOBAL table shared across the whole test session's
        # DB -- clean up so later modules' non-block-3 assertions don't see
        # this leak (mirrors tests/test_scoreboard.py's clean_block3_flags).
        from models import SystemFlag
        SystemFlag.query.filter(
            SystemFlag.key.in_(["projection_mode", "block3_anchor"])
        ).delete(synchronize_session=False)
        db.session.commit()


def test_serve_as_user_aerobic_efficiency_path(app_ctx, monkeypatch):
    """serve-as-user proxies /api/stats/aerobic-efficiency for a seeded user."""
    app_, db = app_ctx
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")

    u, client = _login_via_session(app_, "serve-test-aerobic@test.com")

    with app_.test_client() as c:
        r = c.get(
            "/api/debug/serve-as-user?email=serve-test-aerobic@test.com&path=/api/stats/aerobic-efficiency",
            headers={"X-Admin-Key": "test-key"}
        )

    assert r.status_code == 200, r.get_json()
    data = r.get_json()
    assert data["email"] == "serve-test-aerobic@test.com"
    assert data["path"] == "/api/stats/aerobic-efficiency"
    assert data["status_code"] == 200


def test_serve_as_user_run_log_path(app_ctx, monkeypatch):
    """serve-as-user proxies /api/run-log for a seeded user."""
    app_, db = app_ctx
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")

    u, client = _login_via_session(app_, "serve-test-runlog@test.com")

    with app_.test_client() as c:
        r = c.get(
            "/api/debug/serve-as-user?email=serve-test-runlog@test.com&path=/api/run-log",
            headers={"X-Admin-Key": "test-key"}
        )

    assert r.status_code == 200, r.get_json()
    data = r.get_json()
    assert data["email"] == "serve-test-runlog@test.com"
    assert data["path"] == "/api/run-log"
    assert data["status_code"] == 200


def test_serve_as_user_sunday_recap_path(app_ctx, monkeypatch):
    """serve-as-user proxies /api/sunday-recap for a seeded user."""
    app_, db = app_ctx
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")

    u, client = _login_via_session(app_, "serve-test-recap@test.com")

    with app_.test_client() as c:
        r = c.get(
            "/api/debug/serve-as-user?email=serve-test-recap@test.com&path=/api/sunday-recap",
            headers={"X-Admin-Key": "test-key"}
        )

    assert r.status_code == 200, r.get_json()
    data = r.get_json()
    assert data["email"] == "serve-test-recap@test.com"
    assert data["path"] == "/api/sunday-recap"
    assert data["status_code"] == 200


def test_serve_as_user_allowlist_rejects_run_log_suffix(app_ctx, monkeypatch):
    """serve-as-user rejects /api/run-logx (prefix-only match on /api/run-log)."""
    app_, db = app_ctx
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")

    with app_.test_client() as c:
        r = c.get(
            "/api/debug/serve-as-user?email=test@test.com&path=/api/run-logx",
            headers={"X-Admin-Key": "test-key"}
        )

    assert r.status_code == 403, r.get_json()
    assert "not allowlisted" in r.get_json().get("error", "").lower()


def test_serve_as_user_allowlist_rejects_protocol_calendar_superpath(app_ctx, monkeypatch):
    """serve-as-user rejects /api/protocol/calendar/evil (not exact-or-query)."""
    app_, db = app_ctx
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")

    with app_.test_client() as c:
        r = c.get(
            "/api/debug/serve-as-user?email=test@test.com&path=/api/protocol/calendar/evil",
            headers={"X-Admin-Key": "test-key"}
        )

    assert r.status_code == 403, r.get_json()


def test_serve_as_user_allowlist_rejects_non_allowlisted_sibling(app_ctx, monkeypatch):
    """serve-as-user rejects /api/push/vapid-public-key (never allowlisted; confirms
    the Task 9 additions didn't accidentally widen matching)."""
    app_, db = app_ctx
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")

    with app_.test_client() as c:
        r = c.get(
            "/api/debug/serve-as-user?email=test@test.com&path=/api/push/vapid-public-key",
            headers={"X-Admin-Key": "test-key"}
        )

    assert r.status_code == 403, r.get_json()


# ── Garmin DB-only tests (no live HTTP calls) ────────────────────────────────

def test_coach_context_garmin_db_only_with_wellness(app_ctx, monkeypatch):
    """coach-context returns populated wellness from GarminWellness DB rows (DB-only, no live calls)."""
    app_, db = app_ctx
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")

    email = "garmin-db-only@test.com"
    from models import User, GarminWellness
    from datetime import date, timedelta

    u = User.query.filter_by(email=email).first()
    if not u:
        u = User(email=email)
        db.session.add(u)

    # Seed wellness data
    GarminWellness.query.filter_by(user_id=u.id).delete()
    today = date.today()
    for i in range(5):
        w = GarminWellness(
            user_id=u.id,
            date=today - timedelta(days=i),
            resting_hr=60 + i,
            hrv_last_night=40.0 + i,
            sleep_score=85 - i
        )
        db.session.add(w)
    db.session.commit()

    with app_.test_client() as c:
        r = c.get(
            f"/api/debug/coach-context?email={email}",
            headers={"X-Admin-Key": "test-key"}
        )

    assert r.status_code == 200, r.get_json()
    data = r.get_json()
    context = data["context"]

    # Garmin should be None (live client skipped)
    assert context["garmin"] is None
    # Readiness should be None (live client skipped)
    assert context["readiness"] is None
    # Wellness should be populated from DB
    assert context["wellness"] is not None
    assert "rhr_7d" in context["wellness"]
    # There should be a note explaining why live client is skipped
    assert "garmin_note" in context
    assert "DB-only" in context["garmin_note"]


def test_coach_context_garmin_no_live_client_calls(app_ctx, monkeypatch):
    """coach-context does NOT call live Garmin client (even if it would raise)."""
    app_, db = app_ctx
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")

    email = "garmin-no-live@test.com"
    from models import User
    from app import _get_garmin

    u = User.query.filter_by(email=email).first()
    if not u:
        u = User(email=email)
        db.session.add(u)
        db.session.commit()

    # Monkeypatch the Garmin client to raise if touched
    def broken_get_garmin(user_id):
        raise RuntimeError("Live Garmin client was called! Debug surface must be side-effect-free.")

    monkeypatch.setattr("app._get_garmin", broken_get_garmin)

    # This should still succeed with 200, because the debug endpoint uses DB-only wellness
    with app_.test_client() as c:
        r = c.get(
            f"/api/debug/coach-context?email={email}",
            headers={"X-Admin-Key": "test-key"}
        )

    # Should be 200, not 500 (live client was NOT called)
    assert r.status_code == 200, r.get_json()
    data = r.get_json()
    context = data["context"]
    assert context["garmin"] is None
    assert context["readiness"] is None
    # wellness should be present (from DB, no live calls)
    assert "wellness" in context
