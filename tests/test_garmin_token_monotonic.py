"""tests/test_garmin_token_monotonic.py — TDD for the 2026-08-28 token clobber.

Root cause (proven from Render logs): prod runs gunicorn with `--preload`, so
the autosync daemon thread lives in the gunicorn MASTER while HTTP (including
the laptop's save-tokens upload) is served by the forked WORKER. Each process
has its own in-memory Garmin client. The worker loads a fresh token and writes
it to the DB; the master's next tick still holds the previous token, syncs
fine, then `persist_tokens_if_changed` sees "my dump != row" and overwrites
the DB with the OLDER token. When that token expires, every tick knocks the
exchange endpoint (429) until the next laptop upload — the daemon was dead
5–8 h/day for days, masked by the worker's page-load syncs.

Contract pinned here:
1. persist_tokens_if_changed is MONOTONIC — it never regresses the stored
   row to an older OAuth2 (by expires_at).
2. GarminClient.stored_token_is_newer() compares the DB blob against the
   in-memory token with zero HTTP.
3. The autosync tick reloads from the DB (exchange-free) when the stored
   token is newer than the one in memory, even if the in-memory one is
   still valid.
4. /api/garmin/sync-activities does the same on a page load.
5. The laptop refresher uploads on EVERY run — its local "prod already has
   this token" marker cannot see prod losing the token.
"""
import json
import os
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


def _make_user(app_, db, email, token_data):
    def _do():
        from models import User, GarminTokens
        u = User.query.filter_by(email=email).first()
        if not u:
            u = User(email=email, timezone="America/Indianapolis")
            db.session.add(u)
            db.session.commit()
        t = GarminTokens.query.filter_by(user_id=u.id).first()
        if t:
            t.token_data = token_data
        else:
            db.session.add(GarminTokens(user_id=u.id, token_data=token_data))
        db.session.commit()
        return u.id
    return _app_do(app_, _do)


def _client_for(app_, user_id):
    client = app_.test_client()
    with client.session_transaction() as s:
        s["_user_id"] = str(user_id)
        s["_fresh"] = True
    return client


def _blob(expires_at, tag="z"):
    """A garth-shaped [oauth1, oauth2] dump; `tag` makes blobs distinguishable."""
    return json.dumps([{"oauth_token": "x", "oauth_token_secret": "y"},
                       {"access_token": tag, "expires_at": expires_at,
                        "refresh_token": "r", "refresh_token_expires_at": expires_at + 86400}])


def _real_client_with_token(user_id, expires_at, tag):
    """A real GarminClient whose api.garth dumps a blob with this expiry."""
    from garmin_client import GarminClient
    gc = GarminClient(user_id=user_id)
    gc._connected = True
    gc.api = MagicMock()
    gc.api.garth.dumps.return_value = _blob(expires_at, tag)
    gc.api.garth.oauth2_token.expires_at = expires_at
    gc.api.garth.oauth2_token.expired = expires_at < time.time()
    return gc


def _row(app_, uid):
    def _do():
        from models import GarminTokens
        r = GarminTokens.query.filter_by(user_id=uid).first()
        return r.token_data, r.updated_at
    return _app_do(app_, _do)


class _StubGC:
    """Mirror of the lifecycle-test stub plus the newer-token hook."""

    def __init__(self, connected=True, stored_newer=False):
        self.connected = connected
        self._rate_limited_until = 0
        self.last_restore_error = None
        self.api = None
        self.restore_calls = 0
        self._stored_newer = stored_newer

    def try_restore_tokens(self, user_id=None, allow_expired_exchange=False):
        self.restore_calls += 1
        return True

    def oauth2_expired_in_memory(self):
        return False

    def stored_token_is_newer(self, user_id=None):
        return self._stored_newer

    def persist_tokens_if_changed(self):
        return False

    def get_activities_between(self, start_iso, end_iso):
        return []

    def get_wellness_for_day(self, day_iso):
        return None


# ── 1. persist is monotonic ──────────────────────────────────────────────

def test_persist_never_regresses_a_newer_stored_token(app_ctx):
    """Master holds T(n-1); worker already wrote T(n). The master's persist
    must leave the row alone."""
    app_, db = app_ctx
    now = time.time()
    newer = _blob(now + 80000, tag="NEW")
    uid = _make_user(app_, db, "mono-regress@test.com", token_data=newer)
    before_data, before_updated = _row(app_, uid)

    gc = _real_client_with_token(uid, now + 30000, tag="OLD")
    with app_.app_context():
        wrote = gc.persist_tokens_if_changed()

    after_data, after_updated = _row(app_, uid)
    assert wrote is False, "an older in-memory token must not be persisted"
    assert after_data == before_data == newer
    assert after_updated == before_updated


def test_persist_still_writes_a_newer_in_memory_token(app_ctx):
    """garth refreshed mid-call → the fresher token must still land."""
    app_, db = app_ctx
    now = time.time()
    older = _blob(now + 30000, tag="OLD")
    uid = _make_user(app_, db, "mono-forward@test.com", token_data=older)

    gc = _real_client_with_token(uid, now + 80000, tag="NEW")
    with app_.app_context():
        wrote = gc.persist_tokens_if_changed()

    after_data, _ = _row(app_, uid)
    assert wrote is True
    assert after_data == _blob(now + 80000, tag="NEW")


# ── 2. stored_token_is_newer: DB blob vs memory, zero HTTP ───────────────

def test_stored_token_is_newer_true_when_db_is_fresher(app_ctx):
    app_, db = app_ctx
    now = time.time()
    uid = _make_user(app_, db, "mono-newer@test.com", token_data=_blob(now + 80000, "NEW"))
    gc = _real_client_with_token(uid, now + 30000, tag="OLD")
    with app_.app_context():
        assert gc.stored_token_is_newer(uid) is True


def test_stored_token_is_newer_false_when_memory_matches_or_leads(app_ctx):
    app_, db = app_ctx
    now = time.time()
    uid = _make_user(app_, db, "mono-same@test.com", token_data=_blob(now + 30000, "SAME"))
    gc = _real_client_with_token(uid, now + 30000, tag="SAME")
    with app_.app_context():
        assert gc.stored_token_is_newer(uid) is False
    gc = _real_client_with_token(uid, now + 80000, tag="LEAD")
    with app_.app_context():
        assert gc.stored_token_is_newer(uid) is False


def test_stored_token_is_newer_false_without_a_session(app_ctx):
    """No api / no row → never claims 'newer' (callers would restore)."""
    app_, db = app_ctx
    from garmin_client import GarminClient
    uid = _make_user(app_, db, "mono-noapi@test.com", token_data=_blob(time.time() + 80000))
    gc = GarminClient(user_id=uid)
    with app_.app_context():
        assert gc.stored_token_is_newer(uid) is False


# ── 3. the tick adopts a newer stored token ──────────────────────────────

def test_tick_reloads_when_stored_token_is_newer_than_memory(app_ctx, monkeypatch):
    app_, db = app_ctx
    import app as appmod
    import garmin_sync as gs
    uid = _make_user(app_, db, "mono-tick@test.com", token_data=_blob(time.time() + 80000))
    gc = _StubGC(connected=True, stored_newer=True)
    monkeypatch.setattr(appmod, "_get_garmin", lambda u=None: gc)
    monkeypatch.setattr(gs, "sync_activities", lambda *a, **k: {"error": None, "days_filled": []})
    monkeypatch.setattr(gs, "sync_wellness", lambda *a, **k: {})
    with app_.app_context():
        synced = appmod._garmin_autosync_tick()
    assert uid in synced
    assert gc.restore_calls >= 1, \
        "a valid-but-older in-memory token must be replaced by the newer stored one"


def test_tick_does_not_reload_when_memory_is_current(app_ctx, monkeypatch):
    app_, db = app_ctx
    import app as appmod
    import garmin_sync as gs
    _make_user(app_, db, "mono-tick2@test.com", token_data=_blob(time.time() + 80000))
    gc = _StubGC(connected=True, stored_newer=False)
    monkeypatch.setattr(appmod, "_get_garmin", lambda u=None: gc)
    monkeypatch.setattr(gs, "sync_activities", lambda *a, **k: {"error": None, "days_filled": []})
    monkeypatch.setattr(gs, "sync_wellness", lambda *a, **k: {})
    with app_.app_context():
        appmod._garmin_autosync_tick()
    assert gc.restore_calls == 0


# ── 4. page-load sync adopts a newer stored token ────────────────────────

def test_sync_activities_reloads_when_stored_token_is_newer(app_ctx, monkeypatch):
    app_, db = app_ctx
    import app as appmod
    uid = _make_user(app_, db, "mono-page@test.com", token_data=_blob(time.time() + 80000))
    gc = _StubGC(connected=True, stored_newer=True)
    monkeypatch.setattr(appmod, "_get_garmin", lambda u=None: gc)
    client = _client_for(app_, uid)
    r = client.post("/api/garmin/sync-activities", json={"force": True})
    assert r.status_code == 200
    assert gc.restore_calls == 1


# ── 5. the laptop refresher uploads every run ────────────────────────────

def _garth_dump(expires_at):
    from garth.auth_tokens import OAuth1Token, OAuth2Token
    from garth.http import Client
    c = Client()
    c.configure(
        oauth1_token=OAuth1Token(oauth_token="x", oauth_token_secret="y"),
        oauth2_token=OAuth2Token(scope="s", jti="j", token_type="Bearer",
                                 access_token="a", refresh_token="r",
                                 expires_in=86400, expires_at=int(expires_at),
                                 refresh_token_expires_in=86400 * 30,
                                 refresh_token_expires_at=int(expires_at) + 86400 * 30),
    )
    return c.dumps()


def test_refresher_uploads_even_when_local_marker_matches(tmp_path, monkeypatch):
    """The marker is the refresher's OWN memory of what it sent; prod can lose
    the token behind its back (2026-08-28). Every run must upload."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "garmin_refresh_upload_auto",
        os.path.join(os.path.dirname(__file__), "..", "scripts", "garmin_refresh_upload_auto.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    dump = _garth_dump(time.time() + 20 * 3600)  # >12 h left → no refresh path
    token_file = tmp_path / "tokens.json"
    token_file.write_text(dump)
    marker = tmp_path / "uploaded"
    marker.write_text(dump)  # prod "already confirmed" this exact dump
    monkeypatch.setattr(mod, "TOKEN_PATHS", [str(token_file)])
    monkeypatch.setattr(mod, "UPLOADED_MARKER", str(marker))

    sent = {}

    def _fake_upload(d):
        sent["dump"] = d
        return {"connected": True, "days_filled": ["w3d4"]}
    monkeypatch.setattr(mod, "_upload", _fake_upload)

    mod.main()
    assert sent.get("dump") == dump, "must upload every run, marker or not"
