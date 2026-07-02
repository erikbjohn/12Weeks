"""Security audit fixes (theme 1-security, 2026-07-01 whole-app audit).

Covers:
- /api/debug/* endpoints require admin auth (no more unauth ?email= dumps,
  no more account-takeover via /api/debug/coach-error).
- The hardcoded 'swap-cleanup-2026-04-30' token no longer grants destructive
  access to another user's data.
- ADMIN_API_KEY is accepted ONLY via the X-Admin-Key header, never as a
  ?admin_key= query param (which leaks into access logs / history / Referer).
- /api/test/create-user is no longer anonymous account minting.
- _intake_jobs are scoped per user + kind: one user can never consume
  another user's psych-intake / profile / report job.
- Push subscriptions are per-user: /api/push/test never fans out to other
  users' devices.

NOTE: these tests deliberately do NOT hold an app context open across client
requests — flask-login caches the loaded user on the active app context's `g`,
so a module-held context would leak one request's (anonymous) user into the
next request.
"""
import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
    yield app, db


def _user_id(app_, db, email):
    """Create (or fetch) a user and return their id (not the ORM object —
    it would be detached once the context closes)."""
    from models import User
    with app_.app_context():
        u = User.query.filter_by(email=email).first()
        if not u:
            u = User(email=email)
            db.session.add(u)
            db.session.commit()
        return u.id


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


DEBUG_GET_ENDPOINTS = [
    "/api/debug/override-day-with-actual?email=x@y.com&date=2026-07-01&week=5&day_idx=0",
    "/api/debug/realign-session-week?email=x@y.com&from_week=6&to_week=5&day_idx=0&date=2026-07-01",
    "/api/debug/api-workouts-as-user?email=x@y.com",
    "/api/debug/today-status?email=x@y.com",
    "/api/debug/copy-runplan?email=x@y.com&from_week=5&to_week=6",
    "/api/debug/full-day-state?email=x@y.com",
    "/api/debug/show-sets?email=x@y.com",
    "/api/debug/move-sets-day?email=x@y.com&date=2026-07-01&from=4&to=3",
    "/api/debug/run-plan?email=x@y.com",
    "/api/debug/clear-stale-prescriptions?email=x@y.com&week=5",
    "/api/debug/program-friday?email=x@y.com",
    "/api/debug/coach-feedback",
    "/api/debug/coach-error?email=x@y.com&msg=hi",
]


@pytest.mark.parametrize("url", DEBUG_GET_ENDPOINTS)
def test_debug_endpoints_require_auth(app_ctx, url):
    app_, db = app_ctx
    client = app_.test_client()
    r = client.get(url)
    assert r.status_code in (401, 403), f"{url} answered {r.status_code} unauthenticated"


def test_debug_endpoints_reject_non_admin_session(app_ctx):
    app_, db = app_ctx
    uid = _user_id(app_, db, "regular-user@test.com")
    client = app_.test_client()
    _login(client, uid)
    r = client.get("/api/debug/show-sets?email=someone-else@test.com")
    assert r.status_code == 403


def test_hardcoded_swap_cleanup_token_no_longer_works(app_ctx):
    """The static token committed to the repo must not gate destructive access."""
    app_, db = app_ctx
    _user_id(app_, db, "victim@test.com")
    client = app_.test_client()
    r = client.get(
        "/api/debug/clear-stale-prescriptions"
        "?email=victim@test.com&week=5&token=swap-cleanup-2026-04-30"
    )
    assert r.status_code in (401, 403)
    payload = r.get_json() or {}
    assert "deleted_rows" not in payload


def test_admin_key_rejected_as_query_param_accepted_as_header(app_ctx, monkeypatch):
    app_, db = app_ctx
    monkeypatch.setenv("ADMIN_API_KEY", "sekrit-test-key")
    _user_id(app_, db, "erik-test@test.com")
    client = app_.test_client()
    # Query param must NOT authenticate (it leaks into access logs).
    r = client.get("/api/debug/show-sets?email=erik-test@test.com&admin_key=sekrit-test-key")
    assert r.status_code in (401, 403)
    # Header must authenticate.
    r = client.get(
        "/api/debug/show-sets?email=erik-test@test.com",
        headers={"X-Admin-Key": "sekrit-test-key"},
    )
    assert r.status_code == 200


def test_test_create_user_requires_admin(app_ctx):
    app_, db = app_ctx
    client = app_.test_client()
    r = client.post("/api/test/create-user", json={})
    assert r.status_code in (401, 403)
    from models import User
    with app_.app_context():
        assert User.query.filter_by(email="test@12weeks.com").first() is None


# ---- _intake_jobs scoping ---------------------------------------------------

def test_intake_result_job_is_owner_scoped(app_ctx):
    app_, db = app_ctx
    import app as app_module
    a = _user_id(app_, db, "intake-owner@test.com")
    b = _user_id(app_, db, "intake-thief@test.com")
    app_module._intake_jobs["jobA1234"] = {
        "status": "done", "response_text": "private to A", "is_complete": False,
        "kind": "intake", "user_id": a,
    }
    try:
        client = app_.test_client()
        _login(client, b)
        r = client.get("/api/psych-intake/result/jobA1234")
        assert r.status_code == 404
        # B's poll must not have consumed A's job.
        assert "jobA1234" in app_module._intake_jobs
    finally:
        app_module._intake_jobs.pop("jobA1234", None)


def test_full_profile_result_rejects_other_users_and_other_kinds(app_ctx):
    app_, db = app_ctx
    import app as app_module
    a = _user_id(app_, db, "profile-owner@test.com")
    b = _user_id(app_, db, "profile-thief@test.com")
    app_module._intake_jobs["jobP1234"] = {
        "status": "done", "profile": "A's profile",
        "kind": "profile", "user_id": a,
    }
    try:
        client = app_.test_client()
        _login(client, b)
        assert client.get("/api/full-profile/result/jobP1234").status_code == 404
        # Even the owner cannot consume it through a different-kind endpoint.
        client_a = app_.test_client()
        _login(client_a, a)
        assert client_a.get("/api/psych-intake/result/jobP1234").status_code == 404
        assert "jobP1234" in app_module._intake_jobs
    finally:
        app_module._intake_jobs.pop("jobP1234", None)


def test_pending_intake_job_of_other_user_is_not_handed_back(app_ctx, monkeypatch):
    """User B sending an intake message must never be handed user A's pending
    job_id (the pre-fix scan matched ANY pending job)."""
    app_, db = app_ctx
    import app as app_module
    from models import PsychIntake
    a = _user_id(app_, db, "pending-a@test.com")
    b = _user_id(app_, db, "pending-b@test.com")
    with app_.app_context():
        if not PsychIntake.query.filter_by(user_id=b).first():
            db.session.add(PsychIntake(user_id=b, conversation=[
                {"role": "assistant", "content": "What's your name?"},
                {"role": "user", "content": "B"},
            ]))
            db.session.commit()
    monkeypatch.setattr(app_module, "get_intake_response", lambda *args, **kw: ("ok", False))
    app_module._intake_jobs["jobPEND12"] = {
        "status": "pending", "kind": "intake", "user_id": a,
    }
    new_job_id = None
    try:
        client = app_.test_client()
        _login(client, b)
        r = client.post("/api/psych-intake/message", json={"message": "hello coach"})
        assert r.status_code == 200
        payload = r.get_json()
        new_job_id = payload["job_id"]
        assert new_job_id != "jobPEND12"
        job = app_module._intake_jobs.get(new_job_id)
        assert job is not None and job.get("user_id") == b
    finally:
        app_module._intake_jobs.pop("jobPEND12", None)
        if new_job_id:
            app_module._intake_jobs.pop(new_job_id, None)


# ---- push subscription scoping ----------------------------------------------

def test_push_test_only_targets_current_users_subscriptions(app_ctx):
    app_, db = app_ctx
    import app as app_module
    a = _user_id(app_, db, "push-a@test.com")
    b = _user_id(app_, db, "push-b@test.com")
    client_a = app_.test_client()
    _login(client_a, a)
    r = client_a.post("/api/push/subscribe", json={"subscription": {"endpoint": "https://push/a"}})
    assert r.status_code == 200
    assert app_module._push_subscriptions.get(a) == [{"endpoint": "https://push/a"}]
    # B has no subscriptions: /api/push/test must NOT fan out to A's device.
    client_b = app_.test_client()
    _login(client_b, b)
    r = client_b.post("/api/push/test")
    assert r.status_code == 400  # "no subscribers" for B — A untouched
    assert app_module._push_subscriptions.get(a) == [{"endpoint": "https://push/a"}]
