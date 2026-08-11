"""tests/test_push_foundation.py — TDD for the push notification server
foundation (Task 1 of the engagement-features plan):

  models.PushSubscription / models.PushSent
  app._get_or_create_vapid() -> (private_pem, public_key_b64), self-
    provisioned once and persisted in SystemFlag (vapid_private_pem /
    vapid_public_key) so the keypair survives worker restarts/deploys.
  app.push_to_user(user_id, title, body, tag=None) -> int (sent count);
    prunes a subscription on 404/410; never raises.
  POST /api/push/subscribe   — upsert PushSubscription by endpoint
  POST /api/push/unsubscribe — delete a row, but only one owned by the
    logged-in user
  GET  /api/push/vapid-public-key

NOTE on app-context handling: this module follows tests/test_protocol_api.py
and tests/test_security_auth.py — no app context is held open across
test-client requests. flask-login caches the resolved current_user on the
active app context's `g`; a held-open module context leaks one client's
(or one anonymous request's) user into the next request. Every DB touch
here therefore opens its own short-lived `with app_.app_context():` block
and returns plain values, never attached ORM objects.
"""
import base64
import json
from datetime import date

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


def _make_user(app_, db, email):
    def _do():
        from models import User, PushSubscription, PushSent
        u = User.query.filter_by(email=email).first()
        if not u:
            u = User(email=email)
            db.session.add(u)
            db.session.commit()
        PushSubscription.query.filter_by(user_id=u.id).delete()
        PushSent.query.filter_by(user_id=u.id).delete()
        db.session.commit()
        return u.id
    return _app_do(app_, _do)


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


def _clear_vapid_flags(app_, db):
    def _do():
        from models import SystemFlag
        SystemFlag.query.filter(
            SystemFlag.key.in_(["vapid_private_pem", "vapid_public_key"])
        ).delete(synchronize_session=False)
        db.session.commit()
    _app_do(app_, _do)


# ---- VAPID key self-provisioning --------------------------------------------

def test_vapid_generates_once_and_persists(app_ctx):
    app_, db = app_ctx
    _clear_vapid_flags(app_, db)
    import app as app_module

    priv1, pub1 = _app_do(app_, lambda: app_module._get_or_create_vapid())
    priv2, pub2 = _app_do(app_, lambda: app_module._get_or_create_vapid())

    assert priv1 == priv2
    assert pub1 == pub2

    def _flags():
        from models import SystemFlag
        p = SystemFlag.query.filter_by(key="vapid_private_pem").first()
        k = SystemFlag.query.filter_by(key="vapid_public_key").first()
        return (p.value if p else None, k.value if k else None)
    flag_priv, flag_pub = _app_do(app_, _flags)
    assert flag_priv == priv1
    assert flag_pub == pub1

    # Public key must be the base64url-encoded uncompressed P-256 point the
    # browser's PushManager.subscribe({applicationServerKey}) expects: 65
    # raw bytes, starting with the uncompressed-point marker 0x04.
    padded = pub1 + "=" * (-len(pub1) % 4)
    raw = base64.urlsafe_b64decode(padded)
    assert len(raw) == 65
    assert raw[0] == 0x04


# ---- subscribe upserts by endpoint ------------------------------------------

def test_subscribe_upserts_by_endpoint(app_ctx):
    app_, db = app_ctx
    uid = _make_user(app_, db, "push-foundation-sub@test.com")
    client = app_.test_client()
    _login(client, uid)
    endpoint = "https://push.example.com/foundation-upsert-1"

    r = client.post("/api/push/subscribe", json={
        "endpoint": endpoint,
        "keys": {"p256dh": "key1", "auth": "auth1"},
    })
    assert r.status_code == 200
    assert r.get_json() == {"ok": True}

    def _rows():
        from models import PushSubscription
        return PushSubscription.query.filter_by(endpoint=endpoint).all()
    rows = _app_do(app_, _rows)
    assert len(rows) == 1
    assert json.loads(rows[0].keys_json) == {"p256dh": "key1", "auth": "auth1"}

    # Re-subscribing with the same endpoint (browser rotated keys) must
    # update the existing row, not create a second one.
    r = client.post("/api/push/subscribe", json={
        "endpoint": endpoint,
        "keys": {"p256dh": "key2", "auth": "auth2"},
    })
    assert r.status_code == 200
    rows2 = _app_do(app_, _rows)
    assert len(rows2) == 1
    assert json.loads(rows2[0].keys_json) == {"p256dh": "key2", "auth": "auth2"}


def test_subscribe_400_on_missing_endpoint_or_keys(app_ctx):
    app_, db = app_ctx
    uid = _make_user(app_, db, "push-foundation-missing@test.com")
    client = app_.test_client()
    _login(client, uid)

    r = client.post("/api/push/subscribe", json={
        "endpoint": "https://push.example.com/foundation-missing-keys",
    })
    assert r.status_code == 400

    r = client.post("/api/push/subscribe", json={
        "keys": {"p256dh": "a", "auth": "b"},
    })
    assert r.status_code == 400

    r = client.post("/api/push/subscribe", json={})
    assert r.status_code == 400


def test_subscribe_requires_login(app_ctx):
    app_, db = app_ctx
    client = app_.test_client()
    r = client.post("/api/push/subscribe", json={
        "endpoint": "https://push.example.com/foundation-anon",
        "keys": {"p256dh": "a", "auth": "b"},
    })
    assert r.status_code in (401, 403)


# ---- unsubscribe deletes own row only ---------------------------------------

def test_unsubscribe_deletes_own_row_only(app_ctx):
    app_, db = app_ctx
    a = _make_user(app_, db, "push-foundation-unsub-a@test.com")
    b = _make_user(app_, db, "push-foundation-unsub-b@test.com")
    endpoint = "https://push.example.com/foundation-unsub-1"

    def _seed():
        from models import PushSubscription
        db.session.add(PushSubscription(
            user_id=a, endpoint=endpoint,
            keys_json=json.dumps({"p256dh": "x", "auth": "y"}),
        ))
        db.session.commit()
    _app_do(app_, _seed)

    def _exists():
        from models import PushSubscription
        return PushSubscription.query.filter_by(endpoint=endpoint).first() is not None

    # B (not the owner) tries to unsubscribe A's endpoint: must succeed
    # (still {"ok": true} — no information leak about who owns it) but must
    # NOT delete A's row.
    client_b = app_.test_client()
    _login(client_b, b)
    r = client_b.post("/api/push/unsubscribe", json={"endpoint": endpoint})
    assert r.status_code == 200
    assert r.get_json() == {"ok": True}
    assert _app_do(app_, _exists) is True

    # A unsubscribes their own endpoint: row is deleted.
    client_a = app_.test_client()
    _login(client_a, a)
    r = client_a.post("/api/push/unsubscribe", json={"endpoint": endpoint})
    assert r.status_code == 200
    assert _app_do(app_, _exists) is False


# ---- vapid-public-key endpoint -----------------------------------------------

def test_vapid_public_key_endpoint_matches_helper(app_ctx):
    app_, db = app_ctx
    uid = _make_user(app_, db, "push-foundation-vapidkey@test.com")
    import app as app_module
    _, expected_pub = _app_do(app_, lambda: app_module._get_or_create_vapid())

    client = app_.test_client()
    _login(client, uid)
    r = client.get("/api/push/vapid-public-key")
    assert r.status_code == 200
    assert r.get_json() == {"key": expected_pub}


# ---- push_to_user: send / prune / swallow -----------------------------------

def test_push_to_user_counts_successes_and_prunes_on_410(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "push-foundation-send-410@test.com")

    def _seed():
        from models import PushSubscription
        ok = PushSubscription(
            user_id=uid, endpoint="https://push.example.com/foundation-send-ok",
            keys_json=json.dumps({"p256dh": "a", "auth": "b"}),
        )
        gone = PushSubscription(
            user_id=uid, endpoint="https://push.example.com/foundation-send-gone",
            keys_json=json.dumps({"p256dh": "c", "auth": "d"}),
        )
        db.session.add_all([ok, gone])
        db.session.commit()
        return ok.endpoint, gone.endpoint
    ok_ep, gone_ep = _app_do(app_, _seed)

    import pywebpush

    class FakeResponse:
        status_code = 410

    def fake_webpush(subscription_info, **kwargs):
        if subscription_info["endpoint"] == gone_ep:
            raise pywebpush.WebPushException("Gone", response=FakeResponse())
        return None

    monkeypatch.setattr(pywebpush, "webpush", fake_webpush)

    import app as app_module
    sent = _app_do(app_, lambda: app_module.push_to_user(uid, "Title", "Body", tag="t"))
    assert sent == 1

    def _remaining():
        from models import PushSubscription
        return sorted(r.endpoint for r in PushSubscription.query.filter_by(user_id=uid).all())
    assert _app_do(app_, _remaining) == [ok_ep]


def test_push_to_user_prunes_on_404(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "push-foundation-send-404@test.com")

    def _seed():
        from models import PushSubscription
        row = PushSubscription(
            user_id=uid, endpoint="https://push.example.com/foundation-send-404",
            keys_json=json.dumps({"p256dh": "a", "auth": "b"}),
        )
        db.session.add(row)
        db.session.commit()
    _app_do(app_, _seed)

    import pywebpush

    class FakeResponse:
        status_code = 404

    def fake_webpush(subscription_info, **kwargs):
        raise pywebpush.WebPushException("Not Found", response=FakeResponse())

    monkeypatch.setattr(pywebpush, "webpush", fake_webpush)

    import app as app_module
    sent = _app_do(app_, lambda: app_module.push_to_user(uid, "Title", "Body"))
    assert sent == 0

    def _remaining():
        from models import PushSubscription
        return PushSubscription.query.filter_by(user_id=uid).count()
    assert _app_do(app_, _remaining) == 0


def test_push_to_user_swallows_generic_exception_and_continues(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "push-foundation-send-exc@test.com")

    def _seed():
        from models import PushSubscription
        boom = PushSubscription(
            user_id=uid, endpoint="https://push.example.com/foundation-send-boom",
            keys_json=json.dumps({"p256dh": "a", "auth": "b"}),
        )
        fine = PushSubscription(
            user_id=uid, endpoint="https://push.example.com/foundation-send-fine",
            keys_json=json.dumps({"p256dh": "c", "auth": "d"}),
        )
        db.session.add_all([boom, fine])
        db.session.commit()
        return boom.endpoint, fine.endpoint
    boom_ep, fine_ep = _app_do(app_, _seed)

    import pywebpush

    def fake_webpush(subscription_info, **kwargs):
        if subscription_info["endpoint"] == boom_ep:
            raise RuntimeError("network exploded")
        return None

    monkeypatch.setattr(pywebpush, "webpush", fake_webpush)

    import app as app_module
    sent = _app_do(app_, lambda: app_module.push_to_user(uid, "Title", "Body"))
    # Only the non-exploding subscription counts as a success; the crashed
    # one must never raise out of push_to_user, and must NOT be pruned
    # (a generic exception is not evidence the subscription is dead).
    assert sent == 1

    def _remaining():
        from models import PushSubscription
        return sorted(r.endpoint for r in PushSubscription.query.filter_by(user_id=uid).all())
    assert _app_do(app_, _remaining) == sorted([boom_ep, fine_ep])


def test_push_to_user_no_subscriptions_returns_zero(app_ctx):
    app_, db = app_ctx
    uid = _make_user(app_, db, "push-foundation-send-none@test.com")
    import app as app_module
    sent = _app_do(app_, lambda: app_module.push_to_user(uid, "Title", "Body"))
    assert sent == 0


# ---- PushSent idempotency ledger --------------------------------------------

def test_push_sent_unique_constraint_enforced(app_ctx):
    app_, db = app_ctx
    uid = _make_user(app_, db, "push-foundation-sent@test.com")

    def _first():
        from models import PushSent
        db.session.add(PushSent(user_id=uid, kind="morning", local_date=date(2026, 8, 11)))
        db.session.commit()
    _app_do(app_, _first)

    def _dup():
        from sqlalchemy.exc import IntegrityError
        from models import PushSent
        db.session.add(PushSent(user_id=uid, kind="morning", local_date=date(2026, 8, 11)))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()
    _app_do(app_, _dup)

    # A different kind (or a different date) on the same user is NOT a
    # duplicate — it must be allowed.
    def _distinct():
        from models import PushSent
        db.session.add(PushSent(user_id=uid, kind="evening", local_date=date(2026, 8, 11)))
        db.session.add(PushSent(user_id=uid, kind="morning", local_date=date(2026, 8, 12)))
        db.session.commit()
        return PushSent.query.filter_by(user_id=uid).count()
    assert _app_do(app_, _distinct) == 3
