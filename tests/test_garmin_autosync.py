"""Server-side Garmin auto-sync: a background tick that pulls activities +
wellness for every token-holding user on a long-lived session — no app-open
required. Born 2026-08-11 after a run sat in Garmin's cloud all night because
sync only ever ran on page load.

Design constraints (the hard lessons):
- NEVER forces a login: if the client is disconnected it attempts ONE restore,
  and if the client is in a 429 cooldown it SKIPS silently (quiet clears
  Garmin's auth blocks; knocking extends them).
- Data endpoints only once connected — auth is touched at most once per
  process lifetime per user.
"""
import time
from datetime import date

import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
    yield app, db


def _user_with_tokens(app_, db, email):
    with app_.app_context():
        from models import User, GarminTokens
        u = User.query.filter_by(email=email).first()
        if not u:
            u = User(email=email)
            db.session.add(u)
            db.session.commit()
        t = GarminTokens.query.filter_by(user_id=u.id).first()
        if not t:
            db.session.add(GarminTokens(user_id=u.id, token_data="{}"))
            db.session.commit()
        return u.id


class _StubGC:
    def __init__(self, connected=True, cooldown=False):
        self.connected = connected
        self._rate_limited_until = time.time() + 900 if cooldown else 0
        self.restore_calls = 0

    def try_restore_tokens(self, uid=None):
        self.restore_calls += 1
        self.connected = True
        return True


def test_tick_syncs_connected_user(app_ctx, monkeypatch):
    app_, db = app_ctx
    import app as appmod
    import garmin_sync as gs
    uid = _user_with_tokens(app_, db, "autosync-a@test.com")
    gc = _StubGC(connected=True)
    calls = {}
    monkeypatch.setattr(appmod, "_get_garmin", lambda u=None: gc)
    monkeypatch.setattr(gs, "sync_activities", lambda *a, **k: calls.setdefault("acts", k) or {"error": None, "days_filled": []})
    monkeypatch.setattr(gs, "sync_wellness", lambda *a, **k: calls.setdefault("well", True) or {})
    with app_.app_context():
        synced = appmod._garmin_autosync_tick()
    assert uid in synced
    assert "acts" in calls and "well" in calls


def test_tick_skips_user_in_cooldown_without_touching_garmin(app_ctx, monkeypatch):
    app_, db = app_ctx
    import app as appmod
    import garmin_sync as gs
    _user_with_tokens(app_, db, "autosync-b@test.com")
    gc = _StubGC(connected=False, cooldown=True)
    monkeypatch.setattr(appmod, "_get_garmin", lambda u=None: gc)
    called = {}
    monkeypatch.setattr(gs, "sync_activities", lambda *a, **k: called.setdefault("x", True))
    with app_.app_context():
        synced = appmod._garmin_autosync_tick()
    assert synced == []          # nobody synced
    assert gc.restore_calls == 0  # cooldown -> no knock on Garmin at all
    assert "x" not in called


def test_tick_restores_disconnected_user_once(app_ctx, monkeypatch):
    app_, db = app_ctx
    import app as appmod
    import garmin_sync as gs
    uid = _user_with_tokens(app_, db, "autosync-c@test.com")
    gc = _StubGC(connected=False, cooldown=False)
    monkeypatch.setattr(appmod, "_get_garmin", lambda u=None: gc)
    monkeypatch.setattr(gs, "sync_activities", lambda *a, **k: {"error": None, "days_filled": []})
    monkeypatch.setattr(gs, "sync_wellness", lambda *a, **k: {})
    with app_.app_context():
        synced = appmod._garmin_autosync_tick()
    assert gc.restore_calls == 1
    assert uid in synced


def test_tick_survives_sync_exception(app_ctx, monkeypatch):
    app_, db = app_ctx
    import app as appmod
    import garmin_sync as gs
    _user_with_tokens(app_, db, "autosync-d@test.com")
    gc = _StubGC(connected=True)
    monkeypatch.setattr(appmod, "_get_garmin", lambda u=None: gc)
    def _boom(*a, **k): raise RuntimeError("garmin hiccup")
    monkeypatch.setattr(gs, "sync_activities", _boom)
    # Must not raise — a bad user/cycle never kills the loop.
    with app_.app_context():
        appmod._garmin_autosync_tick()
