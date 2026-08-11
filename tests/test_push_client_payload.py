"""tests/test_push_client_payload.py — server-side contracts consumed by the
Task 2 push CLIENT (static/sw.js + the Notifications toggle in
static/app.js). Task 1 (tests/test_push_foundation.py) already covers the
push server foundation end to end; this file re-verifies, from the CLIENT's
point of view, the exact shapes the browser code depends on:

  GET  /api/push/vapid-public-key — the value handed straight to
    `PushManager.subscribe({applicationServerKey: urlBase64ToUint8Array(key)})`;
    it must decode to a 65-byte uncompressed P-256 point starting 0x04 or
    subscribe() throws in every browser.
  POST /api/push/subscribe — body is exactly `subscription.toJSON()` from a
    real PushSubscription object, which includes fields (expirationTime)
    the server contract doesn't require; extra fields must be tolerated,
    and a payload missing `keys` must 400.
  push_to_user()'s payload — what static/sw.js's `push` handler receives in
    `event.data.json()`; must be valid JSON with title/body/tag keys (tag
    may be null when the caller doesn't pass one).

No browser, no service worker, and no real push service are involved —
this only pins the server side of the contract.

NOTE on app-context handling: follows tests/test_protocol_api.py and
tests/test_push_foundation.py — no app context is held open across
test-client requests (flask-login caches current_user on the active app
context's `g`; a held-open module context leaks one client's user into the
next request). Every DB touch here opens its own short-lived
`with app_.app_context():` block and returns plain values, never attached
ORM objects.
"""
import base64
import json

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
        from models import User, PushSubscription
        u = User.query.filter_by(email=email).first()
        if not u:
            u = User(email=email)
            db.session.add(u)
            db.session.commit()
        PushSubscription.query.filter_by(user_id=u.id).delete()
        db.session.commit()
        return u.id
    return _app_do(app_, _do)


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


# ---- (a) vapid-public-key: what pushManager.subscribe() needs --------------

def test_vapid_public_key_decodes_to_application_server_key(app_ctx):
    app_, db = app_ctx
    uid = _make_user(app_, db, "push-client-vapid@test.com")
    client = app_.test_client()
    _login(client, uid)

    r = client.get("/api/push/vapid-public-key")
    assert r.status_code == 200
    body = r.get_json()
    assert "key" in body
    key = body["key"]

    # Mirrors static/app.js's urlBase64ToUint8Array: '-'/'_' -> '+'/'/', pad
    # to a multiple of 4, then standard base64-decode.
    padded = key + "=" * (-len(key) % 4)
    raw = base64.urlsafe_b64decode(padded)
    assert len(raw) == 65
    assert raw[0] == 0x04


def test_vapid_public_key_requires_login(app_ctx):
    app_, db = app_ctx
    client = app_.test_client()
    r = client.get("/api/push/vapid-public-key")
    assert r.status_code in (401, 403)


# ---- (b) subscribe: exact browser subscription.toJSON() shape --------------

def test_subscribe_accepts_real_browser_subscription_shape(app_ctx):
    app_, db = app_ctx
    uid = _make_user(app_, db, "push-client-sub@test.com")
    client = app_.test_client()
    _login(client, uid)

    # This is exactly what PushSubscription.prototype.toJSON() returns in a
    # browser — including expirationTime, which the server contract does
    # not require and must tolerate rather than reject.
    payload = {
        "endpoint": "https://fcm.googleapis.com/fcm/send/client-payload-1",
        "expirationTime": None,
        "keys": {
            "p256dh": "BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QTpQtUbVlUls0VJXg7A8u-Ts1XbjhazAkj7I99e8QcYP7DkM",
            "auth": "tBHItJI5svbpez7KI4CCXg",
        },
    }
    r = client.post("/api/push/subscribe", json=payload)
    assert r.status_code == 200
    assert r.get_json() == {"ok": True}

    def _row():
        from models import PushSubscription
        return PushSubscription.query.filter_by(endpoint=payload["endpoint"]).first()
    row = _app_do(app_, _row)
    assert row is not None
    assert row.user_id == uid
    assert json.loads(row.keys_json) == payload["keys"]


def test_subscribe_400_when_keys_missing(app_ctx):
    app_, db = app_ctx
    uid = _make_user(app_, db, "push-client-nokeys@test.com")
    client = app_.test_client()
    _login(client, uid)

    r = client.post("/api/push/subscribe", json={
        "endpoint": "https://fcm.googleapis.com/fcm/send/client-payload-nokeys",
        "expirationTime": None,
    })
    assert r.status_code == 400


# ---- (d) push_to_user's payload: what sw.js's `push` handler parses --------

def test_push_payload_is_valid_json_with_title_body_tag(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "push-client-payload@test.com")

    def _seed():
        from models import PushSubscription
        db.session.add(PushSubscription(
            user_id=uid,
            endpoint="https://fcm.googleapis.com/fcm/send/client-payload-send",
            keys_json=json.dumps({"p256dh": "a", "auth": "b"}),
        ))
        db.session.commit()
    _app_do(app_, _seed)

    import pywebpush
    captured = {}

    def fake_webpush(subscription_info, **kwargs):
        captured["data"] = kwargs.get("data")
        return None

    monkeypatch.setattr(pywebpush, "webpush", fake_webpush)

    import app as app_module
    sent = _app_do(app_, lambda: app_module.push_to_user(
        uid, "Time to check in!", "Your Monday plan is ready.", tag="morning",
    ))
    assert sent == 1

    assert "data" in captured
    # Must be valid JSON — sw.js does `data = e.data.json()`.
    parsed = json.loads(captured["data"])
    assert parsed["title"] == "Time to check in!"
    assert parsed["body"] == "Your Monday plan is ready."
    assert parsed["tag"] == "morning"


def test_push_payload_tag_is_null_when_not_passed(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "push-client-payload-notag@test.com")

    def _seed():
        from models import PushSubscription
        db.session.add(PushSubscription(
            user_id=uid,
            endpoint="https://fcm.googleapis.com/fcm/send/client-payload-notag",
            keys_json=json.dumps({"p256dh": "a", "auth": "b"}),
        ))
        db.session.commit()
    _app_do(app_, _seed)

    import pywebpush
    captured = {}

    def fake_webpush(subscription_info, **kwargs):
        captured["data"] = kwargs.get("data")
        return None

    monkeypatch.setattr(pywebpush, "webpush", fake_webpush)

    import app as app_module
    sent = _app_do(app_, lambda: app_module.push_to_user(uid, "Title", "Body"))
    assert sent == 1

    parsed = json.loads(captured["data"])
    assert parsed["title"] == "Title"
    assert parsed["body"] == "Body"
    assert parsed["tag"] is None
