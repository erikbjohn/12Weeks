"""tests/test_garmin_status_copy.py — TDD for Garmin restore error reporting.

When a Garmin token restore fails, distinguish between:
1. Rate-limited (429 / "Too Many" / cooldown active) → "rate-limited (cooldown Ns)"
2. Other failures (invalid token, auth error, etc.) → "token restore failed: <error class>"

Endpoints tested:
- GET /api/garmin/status (includes restore_error)
- GET /api/garmin/today (honest 503 copy)
- POST /api/garmin/sync-activities (honest 503 copy)
"""
import pytest
import time
from unittest.mock import MagicMock, patch


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
    yield app, db


def _app_do(app_, fn):
    with app_.app_context():
        return fn()


def _make_user(app_, db, email):
    """Create or reset a user for testing."""
    def _do():
        from models import User, GarminTokens
        u = User.query.filter_by(email=email).first()
        if not u:
            u = User(email=email, timezone="America/Los_Angeles")
            db.session.add(u)
            db.session.commit()
        else:
            u.timezone = "America/Los_Angeles"
            db.session.commit()
        # Add a GarminTokens entry so _garmin_linked() returns True
        tokens = GarminTokens.query.filter_by(user_id=u.id).first()
        if not tokens:
            import json
            tokens = GarminTokens(user_id=u.id, token_data=json.dumps({"dummy": "token"}))
            db.session.add(tokens)
            db.session.commit()
        return u.id
    return _app_do(app_, _do)


def _client_for(app_, user_id):
    """Create a logged-in test client for a user."""
    client = app_.test_client()
    with client.session_transaction() as s:
        s["_user_id"] = str(user_id)
        s["_fresh"] = True
    return client


class StubGarminClient:
    """Stub Garmin client for mocking in tests."""
    def __init__(self, connected=False, rate_limited_until=0, last_restore_error=None):
        self.connected = connected
        self._rate_limited_until = rate_limited_until
        self.last_restore_error = last_restore_error
        self.api = None

    def try_restore_tokens(self, user_id=None):
        # Stub: always return False (we're testing the error path)
        return False

    def get_today_summary(self, today=None):
        if self.connected:
            return {"date": "2026-01-01", "hrv": None, "sleep": None}
        return None


# ─────────────────────────────────────────────────────────────────────────
# Test cases
# ─────────────────────────────────────────────────────────────────────────

def test_garmin_today_restore_failed_not_rate_limited(app_ctx, monkeypatch):
    """When restore fails with a non-rate-limit error (e.g. OAuth token invalid),
    the 503 should say "token restore failed" with the error class, NOT "rate-limited"."""
    app_, db = app_ctx
    user_id = _make_user(app_, db, "test1@example.com")
    client = _client_for(app_, user_id)

    # Stub: client is not connected, not rate-limited, but has a restore error
    stub = StubGarminClient(
        connected=False,
        rate_limited_until=0,
        last_restore_error="Exception: OAuth token invalid"
    )

    with app_.app_context():
        import app as appmod
        monkeypatch.setattr(appmod, "_get_garmin", lambda user_id=None: stub)
        monkeypatch.setattr(appmod, "_garmin_linked", lambda uid: True)

        resp = client.get("/api/garmin/today")
        assert resp.status_code == 503
        data = resp.get_json()
        assert "error" in data
        assert "token restore failed" in data["error"]
        assert "OAuth token invalid" in data["error"]
        assert "rate-limited" not in data["error"]
        assert data.get("restore_error") == "Exception: OAuth token invalid"


def test_garmin_today_restore_failed_rate_limited(app_ctx, monkeypatch):
    """When restore fails AND there's an active cooldown, the 503 should say
    'rate-limited (cooldown Ns remaining)' and NOT mention 'token restore failed'."""
    app_, db = app_ctx
    user_id = _make_user(app_, db, "test2@example.com")
    client = _client_for(app_, user_id)

    # Stub: client is not connected, IS rate-limited, cooldown in place
    future_time = time.time() + 300  # 5 min cooldown remaining
    stub = StubGarminClient(
        connected=False,
        rate_limited_until=future_time,
        last_restore_error="Exception: 429 Too Many Requests"
    )

    with app_.app_context():
        import app as appmod
        monkeypatch.setattr(appmod, "_get_garmin", lambda user_id=None: stub)
        monkeypatch.setattr(appmod, "_garmin_linked", lambda uid: True)

        resp = client.get("/api/garmin/today")
        assert resp.status_code == 503
        data = resp.get_json()
        assert "error" in data
        assert "rate-limited" in data["error"]
        assert "cooldown" in data["error"]
        assert "token restore failed" not in data["error"]
        # restore_error should be present for diagnostic purposes
        assert data.get("restore_error") == "Exception: 429 Too Many Requests"


def test_garmin_today_connected(app_ctx, monkeypatch):
    """When client is connected, normal path should work (no 503)."""
    app_, db = app_ctx
    user_id = _make_user(app_, db, "test3@example.com")
    client = _client_for(app_, user_id)

    # Stub: client IS connected
    stub = StubGarminClient(
        connected=True,
        rate_limited_until=0,
        last_restore_error=None
    )

    def mock_get_today_summary(today=None):
        return {
            "date": "2026-01-01",
            "hrv": {"lastNight": 50, "weeklyAvg": 55},
            "sleep": {"durationHours": 7.5},
            "bodyBattery": {"current": 75},
            "trainingReadiness": {"score": 80},
            "trainingStatus": {"status": "high"},
            "stress": {"overall": 30},
        }

    stub.get_today_summary = mock_get_today_summary

    with app_.app_context():
        import app as appmod
        monkeypatch.setattr(appmod, "_get_garmin", lambda user_id=None: stub)
        monkeypatch.setattr(appmod, "_garmin_linked", lambda uid: True)

        resp = client.get("/api/garmin/today")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("date") == "2026-01-01"
        assert data.get("hrv") is not None


def test_garmin_status_includes_restore_error(app_ctx, monkeypatch):
    """/api/garmin/status should include restore_error in the response."""
    app_, db = app_ctx
    user_id = _make_user(app_, db, "test4@example.com")
    client = _client_for(app_, user_id)

    stub = StubGarminClient(
        connected=False,
        rate_limited_until=0,
        last_restore_error="Exception: 401 Unauthorized"
    )

    with app_.app_context():
        import app as appmod
        monkeypatch.setattr(appmod, "_get_garmin", lambda user_id=None: stub)
        monkeypatch.setattr(appmod, "_garmin_linked", lambda uid: True)

        resp = client.get("/api/garmin/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("restore_error") == "Exception: 401 Unauthorized"


def test_garmin_sync_activities_restore_failed_not_rate_limited(app_ctx, monkeypatch):
    """POST /api/garmin/sync-activities: same error-copy logic as garmin_today."""
    app_, db = app_ctx
    user_id = _make_user(app_, db, "test5@example.com")
    client = _client_for(app_, user_id)

    stub = StubGarminClient(
        connected=False,
        rate_limited_until=0,
        last_restore_error="Exception: Garmin API error"
    )

    with app_.app_context():
        import app as appmod
        monkeypatch.setattr(appmod, "_get_garmin", lambda user_id=None: stub)
        monkeypatch.setattr(appmod, "_garmin_linked", lambda uid: True)

        resp = client.post("/api/garmin/sync-activities", json={})
        assert resp.status_code == 503
        data = resp.get_json()
        assert "error" in data
        assert "token restore failed" in data["error"]
        assert "rate-limited" not in data["error"]
        assert data.get("restore_error") == "Exception: Garmin API error"


def test_garmin_sync_activities_restore_failed_rate_limited(app_ctx, monkeypatch):
    """POST /api/garmin/sync-activities: rate-limited 503."""
    app_, db = app_ctx
    user_id = _make_user(app_, db, "test6@example.com")
    client = _client_for(app_, user_id)

    future_time = time.time() + 120  # 2 min cooldown
    stub = StubGarminClient(
        connected=False,
        rate_limited_until=future_time,
        last_restore_error="Exception: 429 Too Many Requests"
    )

    with app_.app_context():
        import app as appmod
        monkeypatch.setattr(appmod, "_get_garmin", lambda user_id=None: stub)
        monkeypatch.setattr(appmod, "_garmin_linked", lambda uid: True)

        resp = client.post("/api/garmin/sync-activities", json={})
        assert resp.status_code == 503
        data = resp.get_json()
        assert "rate-limited" in data["error"]
        assert "cooldown" in data["error"]
        assert "token restore failed" not in data["error"]


def test_garmin_push_week_restore_failed_not_rate_limited(app_ctx, monkeypatch):
    """POST /api/garmin/push-week: restore failed (not rate-limited) 503."""
    app_, db = app_ctx
    user_id = _make_user(app_, db, "test7@example.com")
    client = _client_for(app_, user_id)

    stub = StubGarminClient(
        connected=False,
        rate_limited_until=0,
        last_restore_error="Exception: 401 Unauthorized"
    )

    with app_.app_context():
        import app as appmod
        monkeypatch.setattr(appmod, "_get_garmin", lambda user_id=None: stub)
        monkeypatch.setattr(appmod, "_garmin_linked", lambda uid: True)

        resp = client.post("/api/garmin/push-week", json={})
        assert resp.status_code == 503
        data = resp.get_json()
        assert "error" in data
        assert "token restore failed" in data["error"]
        assert "401 Unauthorized" in data["error"]
        assert "rate-limited" not in data["error"]
        assert data.get("restore_error") == "Exception: 401 Unauthorized"


def test_sync_default_window_is_week_to_date(app_ctx, monkeypatch):
    """Without an explicit days_back, sync covers Monday-of-the-current-block-
    week through today only — day 0 syncs 1 day, day 3 syncs 4 days."""
    from datetime import date
    import app as appmod
    app_, db = app_ctx
    from models import User, AppState
    with app_.app_context():
        u = User.query.filter_by(email="syncwin@test.com").first()
        if not u:
            u = User(email="syncwin@test.com")
            db.session.add(u); db.session.commit()
        st = AppState.query.filter_by(user_id=u.id).first()
        if not st:
            st = AppState(user_id=u.id)
            db.session.add(st)
        st.start_date = date(2026, 8, 10)
        st.current_week = 1
        db.session.commit()
        uid = u.id

    captured = {}

    class _StubGC:
        connected = True
        last_restore_error = None
        _rate_limited_until = 0
        def try_restore_tokens(self, uid=None): return True

    def _fake_sync(gc, uid, days_back=3, today=None):
        captured["days_back"] = days_back
        return {"pulled": 0, "days_filled": [], "days_skipped_manual": [],
                "ignored": 0, "error": None, }

    import garmin_sync as gs_mod  # app.py imports it inside the handler
    monkeypatch.setattr(appmod, "_get_garmin", lambda *a, **k: _StubGC())
    monkeypatch.setattr(appmod, "_garmin_linked", lambda uid: True)
    monkeypatch.setattr(gs_mod, "sync_activities", _fake_sync)
    monkeypatch.setattr(gs_mod, "sync_wellness",
                        lambda *a, **k: {"wellness_upserted": 0})

    client = app_.test_client()
    with client.session_transaction() as s:
        s["_user_id"] = str(uid); s["_fresh"] = True

    # Thursday of week 1 (day_idx 3) -> window = 4 days (Mon..Thu)
    monkeypatch.setattr(appmod, "_user_today", lambda: date(2026, 8, 13))
    r = client.post("/api/garmin/sync-activities", json={"force": True})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert captured["days_back"] == 4

    # Monday day 0 -> 1 day only
    monkeypatch.setattr(appmod, "_user_today", lambda: date(2026, 8, 10))
    client.post("/api/garmin/sync-activities", json={"force": True})
    assert captured["days_back"] == 1

    # Explicit override still honored
    client.post("/api/garmin/sync-activities", json={"force": True, "days_back": 14})
    assert captured["days_back"] == 14
