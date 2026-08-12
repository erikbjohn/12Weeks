"""tests/test_garmin_token_lifecycle.py — TDD for the 2026-08-12 sync outage.

Root cause that morning: the laptop-minted OAuth2 expired at 05:32 PT; every
subsequent Garmin data call made garth silently re-run a full OAuth2 exchange
from Render's IP (blocked → 429), and the failure was invisible: the daemon
skipped silently, every app page-load re-knocked the exchange endpoint
(sync-activities' throttle only closes on SUCCESS), and the panel kept saying
"Connected".

Quiet-discipline + honesty contract pinned here:
1. get_activities_between never fires HTTP during an active cooldown.
2. stored_oauth2_expires_at() reads token expiry from the DB blob, no HTTP.
3. /api/garmin/sync-status must NOT attempt a restore (= OAuth2 exchange)
   when the stored token is expired; it reports auth_state honestly.
4. /api/garmin/sync-activities throttles on last ATTEMPT, not last success —
   a failing sync must not let every page open knock Garmin's auth endpoint.
5. /api/admin/garmin/save-tokens clears the cooldown and syncs immediately —
   a token upload should land the missing run without waiting for a tick.
6. The autosync tick persists garth's refreshed tokens after a successful
   sync so a mid-call OAuth2 refresh survives restarts.
"""
import base64
import json
import time
from unittest.mock import MagicMock

import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
    yield app, db


def _app_do(app_, fn):
    with app_.app_context():
        return fn()


def _make_user(app_, db, email, token_data=None):
    def _do():
        from models import User, GarminTokens
        u = User.query.filter_by(email=email).first()
        if not u:
            u = User(email=email, timezone="America/Los_Angeles")
            db.session.add(u)
            db.session.commit()
        t = GarminTokens.query.filter_by(user_id=u.id).first()
        if token_data is not None:
            if t:
                t.token_data = token_data
            else:
                db.session.add(GarminTokens(user_id=u.id, token_data=token_data))
            db.session.commit()
        elif not t:
            db.session.add(GarminTokens(user_id=u.id, token_data="{}"))
            db.session.commit()
        return u.id
    return _app_do(app_, _do)


def _client_for(app_, user_id):
    client = app_.test_client()
    with client.session_transaction() as s:
        s["_user_id"] = str(user_id)
        s["_fresh"] = True
    return client


def _blob(expires_at):
    """A garth-shaped [oauth1, oauth2] dump."""
    return json.dumps([{"oauth_token": "x", "oauth_token_secret": "y"},
                       {"access_token": "z", "expires_at": expires_at,
                        "refresh_token": "r", "refresh_token_expires_at": expires_at + 86400}])


class _StubGC:
    def __init__(self, connected=False, cooldown=False, stale_session=False):
        self.connected = connected
        self._rate_limited_until = time.time() + 900 if cooldown else 0
        self.last_restore_error = None
        self.api = None
        self.restore_calls = 0
        self._stale = stale_session

    def try_restore_tokens(self, user_id=None, allow_expired_exchange=False):
        self.restore_calls += 1
        return False

    def oauth2_expired_in_memory(self):
        return self._stale

    def persist_tokens_if_changed(self):
        return False

    # Harmless data methods so a request that legitimately proceeds past the
    # gates can run the real garmin_sync functions without exploding.
    def get_activities_between(self, start_iso, end_iso):
        return []

    def get_wellness_for_day(self, day_iso):
        return None


# ── 1. cooldown pre-check on the activities fetch ────────────────────────

def test_get_activities_between_is_silent_during_cooldown():
    from garmin_client import GarminClient
    gc = GarminClient(user_id=1)
    gc._connected = True
    gc.api = MagicMock()
    gc._rate_limited_until = time.time() + 900
    assert gc.get_activities_between("2026-08-09", "2026-08-12") is None
    gc.api.get_activities_by_date.assert_not_called()


def test_get_activities_between_fetches_after_cooldown():
    from garmin_client import GarminClient
    gc = GarminClient(user_id=1)
    gc._connected = True
    gc.api = MagicMock()
    gc.api.get_activities_by_date.return_value = []
    gc._rate_limited_until = time.time() - 1
    assert gc.get_activities_between("2026-08-09", "2026-08-12") == []


# ── 2. stored token expiry parsing (DB-only, zero HTTP) ──────────────────

def test_oauth2_expiry_parses_plain_json_blob():
    from garmin_client import _oauth2_expires_from_blob
    assert _oauth2_expires_from_blob(_blob(1786537964)) == 1786537964


def test_oauth2_expiry_parses_base64_blob():
    from garmin_client import _oauth2_expires_from_blob
    b64 = base64.b64encode(_blob(1786537964).encode()).decode()
    assert _oauth2_expires_from_blob(b64) == 1786537964


def test_oauth2_expiry_none_on_garbage():
    from garmin_client import _oauth2_expires_from_blob
    assert _oauth2_expires_from_blob("not tokens") is None
    assert _oauth2_expires_from_blob("{}") is None
    assert _oauth2_expires_from_blob(None) is None


def test_stored_oauth2_expires_at_reads_db(app_ctx):
    app_, db = app_ctx
    exp = time.time() + 7200
    uid = _make_user(app_, db, "lifecycle-exp@test.com", token_data=_blob(exp))
    from garmin_client import stored_oauth2_expires_at
    def _do():
        assert stored_oauth2_expires_at(uid) == exp
        assert stored_oauth2_expires_at(999999) is None
    _app_do(app_, _do)


# ── 3. sync-status: no exchange knock on an expired token; honest state ──

def test_sync_status_expired_token_skips_restore_and_reports(app_ctx, monkeypatch):
    app_, db = app_ctx
    import app as appmod
    uid = _make_user(app_, db, "lifecycle-status@test.com",
                     token_data=_blob(time.time() - 3600))
    gc = _StubGC(connected=False)
    monkeypatch.setattr(appmod, "_get_garmin", lambda u=None: gc)
    client = _client_for(app_, uid)
    r = client.get("/api/garmin/sync-status?week=1")
    assert r.status_code == 200
    data = r.get_json()
    assert gc.restore_calls == 0, "expired stored token must not trigger an OAuth2 exchange"
    assert data["auth_state"] == "token_expired"
    assert data["token_expires_at"] is not None
    assert data["live"] is False


def test_sync_status_valid_token_still_restores(app_ctx, monkeypatch):
    app_, db = app_ctx
    import app as appmod
    uid = _make_user(app_, db, "lifecycle-status2@test.com",
                     token_data=_blob(time.time() + 7200))
    gc = _StubGC(connected=False)
    monkeypatch.setattr(appmod, "_get_garmin", lambda u=None: gc)
    client = _client_for(app_, uid)
    r = client.get("/api/garmin/sync-status?week=1")
    assert r.status_code == 200
    assert gc.restore_calls == 1


# ── 3b. restore itself refuses the exchange on an expired stored token ───

def test_restore_refuses_exchange_when_stored_token_expired(app_ctx, monkeypatch):
    """The gate lives INSIDE try_restore_tokens so all ~10 call sites (coach
    chat, briefing, /today, push-week, …) stay quiet — not just the two
    patched endpoints."""
    app_, db = app_ctx
    import garminconnect
    uid = _make_user(app_, db, "lifecycle-restoregate@test.com",
                     token_data=_blob(time.time() - 3600))

    def _boom(*a, **k):
        raise AssertionError("restore must not construct a Garmin client on an expired token")
    monkeypatch.setattr(garminconnect, "Garmin", _boom)

    from garmin_client import GarminClient
    gc = GarminClient(user_id=uid)
    with app_.app_context():
        assert gc.try_restore_tokens(uid) is False
    assert "TokenExpired" in (gc.last_restore_error or "")


def test_restore_allows_expired_exchange_for_the_daemon(app_ctx, monkeypatch):
    app_, db = app_ctx
    import garminconnect
    uid = _make_user(app_, db, "lifecycle-restoregate2@test.com",
                     token_data=_blob(time.time() - 3600))
    attempted = {}

    class _FakeGarmin:
        def __init__(self, *a, **k):
            pass

        def login(self, tokenstore=None):
            attempted["login"] = True
            raise RuntimeError("simulated 429 from the exchange")
    monkeypatch.setattr(garminconnect, "Garmin", _FakeGarmin)

    from garmin_client import GarminClient
    gc = GarminClient(user_id=uid)
    with app_.app_context():
        assert gc.try_restore_tokens(uid, allow_expired_exchange=True) is False
    assert attempted.get("login"), "the daemon's controlled knock must still go through"


# ── 3c. stale-connected session (token lapsed in place) ──────────────────

def test_sync_status_reports_expired_for_stale_connected_session(app_ctx, monkeypatch):
    """`connected` never flips on data failures — when the OAuth2 lapses in
    place the panel must NOT say live (the 2026-08-12 masking bug)."""
    app_, db = app_ctx
    import app as appmod
    uid = _make_user(app_, db, "lifecycle-stale@test.com",
                     token_data=_blob(time.time() - 3600))
    gc = _StubGC(connected=True, stale_session=True)
    monkeypatch.setattr(appmod, "_get_garmin", lambda u=None: gc)
    client = _client_for(app_, uid)
    r = client.get("/api/garmin/sync-status?week=1")
    data = r.get_json()
    assert data["auth_state"] == "token_expired"
    assert data["live"] is False


def test_sync_activities_stale_session_quiet_when_stored_also_expired(app_ctx, monkeypatch):
    app_, db = app_ctx
    import app as appmod
    uid = _make_user(app_, db, "lifecycle-stale2@test.com",
                     token_data=_blob(time.time() - 3600))
    gc = _StubGC(connected=True, stale_session=True)
    monkeypatch.setattr(appmod, "_get_garmin", lambda u=None: gc)
    client = _client_for(app_, uid)
    r = client.post("/api/garmin/sync-activities", json={"force": True})
    assert r.status_code == 503
    assert r.get_json().get("auth_state") == "token_expired"
    assert gc.restore_calls == 0


def test_sync_activities_stale_session_reloads_fresh_stored_tokens(app_ctx, monkeypatch):
    app_, db = app_ctx
    import app as appmod
    uid = _make_user(app_, db, "lifecycle-stale3@test.com",
                     token_data=_blob(time.time() + 70000))
    gc = _StubGC(connected=True, stale_session=True)
    monkeypatch.setattr(appmod, "_get_garmin", lambda u=None: gc)
    client = _client_for(app_, uid)
    client.post("/api/garmin/sync-activities", json={"force": True})
    assert gc.restore_calls == 1, \
        "fresh stored tokens + stale session must reload (exchange-free)"


# ── 4. sync-activities throttles on attempt, not success ─────────────────

def test_failed_sync_attempt_throttles_next_page_load(app_ctx, monkeypatch):
    app_, db = app_ctx
    import app as appmod
    uid = _make_user(app_, db, "lifecycle-throttle@test.com",
                     token_data=_blob(time.time() + 7200))
    gc = _StubGC(connected=False)
    monkeypatch.setattr(appmod, "_get_garmin", lambda u=None: gc)
    appmod._garmin_sync_last.pop(uid, None)
    appmod._garmin_sync_attempt_last.pop(uid, None)
    client = _client_for(app_, uid)

    r1 = client.post("/api/garmin/sync-activities", json={})
    assert r1.status_code == 503  # restore failed → reconnect response
    assert gc.restore_calls == 1

    r2 = client.post("/api/garmin/sync-activities", json={})
    assert r2.get_json().get("throttled") is True, \
        "a failed attempt must close the auto-sync throttle"
    assert gc.restore_calls == 1, "the throttled call must not knock Garmin again"

    # The manual Sync Now button (force) still gets through.
    r3 = client.post("/api/garmin/sync-activities", json={"force": True})
    assert r3.get_json().get("throttled") is not True
    assert gc.restore_calls == 2


def test_sync_activities_expired_token_stays_quiet(app_ctx, monkeypatch):
    """Disconnected client + expired stored OAuth2: the endpoint must NOT
    attempt a restore (= live exchange from the server IP) — honest 503."""
    app_, db = app_ctx
    import app as appmod
    uid = _make_user(app_, db, "lifecycle-gate@test.com",
                     token_data=_blob(time.time() - 3600))
    gc = _StubGC(connected=False)
    monkeypatch.setattr(appmod, "_get_garmin", lambda u=None: gc)
    client = _client_for(app_, uid)
    r = client.post("/api/garmin/sync-activities", json={"force": True})
    assert r.status_code == 503
    assert gc.restore_calls == 0
    assert r.get_json().get("auth_state") == "token_expired"


# ── 5. save-tokens clears cooldown + syncs immediately ───────────────────

def test_admin_save_tokens_clears_cooldown_and_syncs_now(app_ctx, monkeypatch):
    app_, db = app_ctx
    import app as appmod
    import garmin_sync as gs
    import garminconnect
    uid = _make_user(app_, db, "lifecycle-save@test.com")
    monkeypatch.setenv("ADMIN_API_KEY", "test-admin-key")

    class _FakeGarth:
        def dumps(self):
            return _blob(time.time() + 70000)

    class _FakeGarmin:
        def __init__(self, *a, **k):
            self.garth = _FakeGarth()

        def login(self, tokenstore=None):
            return True

    monkeypatch.setattr(garminconnect, "Garmin", _FakeGarmin)

    with app_.app_context():
        gc = appmod._get_garmin(uid)
    gc._rate_limited_until = time.time() + 900  # pre-armed cooldown

    called = {}

    def _fake_acts(*a, **k):
        called["acts"] = True
        return {"error": None, "days_filled": ["w1d2"]}

    def _fake_well(*a, **k):
        called["well"] = True
        return {}

    monkeypatch.setattr(gs, "sync_activities", _fake_acts)
    monkeypatch.setattr(gs, "sync_wellness", _fake_well)

    client = app_.test_client()
    r = client.post("/api/admin/garmin/save-tokens",
                    json={"email": "lifecycle-save@test.com", "tokens": _blob(time.time() + 70000)},
                    headers={"X-Admin-Key": "test-admin-key"})
    assert r.status_code == 200
    data = r.get_json()
    assert data["connected"] is True
    assert gc._rate_limited_until == 0, "fresh tokens must clear the client cooldown"
    assert called.get("acts") and called.get("well"), \
        "a token upload must sync immediately, not wait for the next tick"
    assert data.get("days_filled") == ["w1d2"]


# ── 6. tick persists refreshed tokens ─────────────────────────────────────

def test_tick_persists_refreshed_tokens_after_success(app_ctx, monkeypatch):
    app_, db = app_ctx
    import app as appmod
    import garmin_sync as gs
    uid = _make_user(app_, db, "lifecycle-persist@test.com")

    class _PersistStub(_StubGC):
        def __init__(self):
            super().__init__(connected=True)
            self.persist_calls = 0

        def persist_tokens_if_changed(self):
            self.persist_calls += 1
            return True

    gc = _PersistStub()
    monkeypatch.setattr(appmod, "_get_garmin", lambda u=None: gc)
    monkeypatch.setattr(gs, "sync_activities", lambda *a, **k: {"error": None, "days_filled": []})
    monkeypatch.setattr(gs, "sync_wellness", lambda *a, **k: {})
    with app_.app_context():
        synced = appmod._garmin_autosync_tick()
    assert uid in synced
    # The tick loops over every token-holding user in the (shared) test DB and
    # _get_garmin is stubbed to the same client — one persist per synced user.
    assert gc.persist_calls == len(synced), \
        "a successful tick must persist garth's (possibly refreshed) tokens"


def test_tick_persists_tokens_even_when_sync_fails(app_ctx, monkeypatch):
    """garth can re-exchange the OAuth2 mid-call even when the sync then
    fails — an unpersisted refresh dies with the process."""
    app_, db = app_ctx
    import app as appmod
    import garmin_sync as gs
    _make_user(app_, db, "lifecycle-persist2@test.com")

    class _PersistStub(_StubGC):
        def __init__(self):
            super().__init__(connected=True)
            self.persist_calls = 0

        def persist_tokens_if_changed(self):
            self.persist_calls += 1
            return False

    gc = _PersistStub()
    monkeypatch.setattr(appmod, "_get_garmin", lambda u=None: gc)
    monkeypatch.setattr(gs, "sync_activities",
                        lambda *a, **k: {"error": "Garmin activity fetch failed", "days_filled": []})
    monkeypatch.setattr(gs, "sync_wellness", lambda *a, **k: {})
    with app_.app_context():
        synced = appmod._garmin_autosync_tick()
    assert synced == []
    assert gc.persist_calls >= 1, \
        "a failed sync must still persist a possibly-refreshed token"


def test_tick_reloads_fresh_stored_tokens_over_stale_session(app_ctx, monkeypatch):
    app_, db = app_ctx
    import app as appmod
    import garmin_sync as gs
    uid = _make_user(app_, db, "lifecycle-tickstale@test.com",
                     token_data=_blob(time.time() + 70000))
    gc = _StubGC(connected=True, stale_session=True)
    monkeypatch.setattr(appmod, "_get_garmin", lambda u=None: gc)
    monkeypatch.setattr(gs, "sync_activities", lambda *a, **k: {"error": None, "days_filled": []})
    monkeypatch.setattr(gs, "sync_wellness", lambda *a, **k: {})
    with app_.app_context():
        appmod._garmin_autosync_tick()
    assert gc.restore_calls >= 1, \
        "stale session + fresh stored tokens: the tick must reload them"
