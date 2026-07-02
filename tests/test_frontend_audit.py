"""Audit theme 9b-frontend regression tests.

Covers the server-visible halves of the frontend audit fixes:
- A client "missed" morning-checkin marker must NEVER overwrite an existing
  check-in (the athlete may have completed the real one on another device).
- A missed check-in registers the missed_checkin compliance event server-side
  (the client used to POST a nonexistent /api/compliance/refresh, which 404'd).
- app.js source tripwires: the fabricated "Auto-completed via morning popup"
  5/10-score POST and the dead /api/compliance/refresh call are gone; the
  falsy-zero-safe helpers exist and are used by the set-logging paths.
"""
import datetime
from pathlib import Path

import pytest

APP_JS = (Path(__file__).resolve().parent.parent / "static" / "app.js").read_text()


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def _login(app_, db, email="frontend-audit@test.com"):
    # NOTE: one shared user for the whole module. The module-scope app context
    # is reused by test-client requests, so Flask-Login caches g._login_user
    # from the FIRST request — a second "user" would silently run as the first.
    from models import User
    u = User.query.filter_by(email=email).first()
    if not u:
        u = User(email=email)
        db.session.add(u)
        db.session.commit()
    client = app_.test_client()
    with client.session_transaction() as s:
        s["_user_id"] = str(u.id)
        s["_fresh"] = True
    return u, client


# ── missed morning check-in: server semantics ───────────────────────────────

def test_missed_marker_never_overwrites_real_checkin(app_ctx):
    app_, db = app_ctx
    from models import MorningCheckIn
    u, client = _login(app_, db)
    d = "2026-03-02"

    r = client.post("/api/morning-checkin", json={
        "date": d, "sleep_quality": 8, "stress_level": 2, "soreness": 3,
        "mood": 9, "motivation": 7, "anxiety": 1, "notes": "real check-in",
    })
    assert r.status_code == 200

    # Another device fires the after-noon auto-miss for the same day.
    r = client.post("/api/morning-checkin", json={
        "date": d, "sleep_quality": 0, "stress_level": 0, "soreness": 0,
        "mood": 0, "motivation": 0, "anxiety": 0,
        "notes": "[MISSED] Morning check-in not completed before noon",
        "missed": True,
    })
    assert r.status_code == 200
    assert r.get_json().get("ignored")

    ci = MorningCheckIn.query.filter_by(
        user_id=u.id, log_date=datetime.date.fromisoformat(d)).first()
    assert ci.sleep_quality == 8  # real scores intact
    assert ci.mood == 9
    assert "[MISSED]" not in (ci.notes or "")


def test_missed_checkin_fires_compliance_event_once(app_ctx):
    app_, db = app_ctx
    from models import ComplianceState, MorningCheckIn
    u, client = _login(app_, db)
    d = "2026-03-03"  # different day from the overwrite test (same user)

    before = ComplianceState.query.filter_by(user_id=u.id).first()
    misses_before = before.consecutive_misses if before else 0

    payload = {
        "date": d, "sleep_quality": 0, "stress_level": 0, "soreness": 0,
        "mood": 0, "motivation": 0, "anxiety": 0,
        "notes": "[MISSED] Morning check-in not completed before noon",
        "missed": True,
    }
    assert client.post("/api/morning-checkin", json=payload).status_code == 200

    state = ComplianceState.query.filter_by(user_id=u.id).first()
    assert state is not None
    assert state.consecutive_misses == misses_before + 1
    assert state.last_miss_date == datetime.date.fromisoformat(d)

    ci = MorningCheckIn.query.filter_by(
        user_id=u.id, log_date=datetime.date.fromisoformat(d)).first()
    assert "[MISSED]" in ci.notes
    assert ci.notes.count("[MISSED]") == 1  # no double marker

    # Replaying the same miss (second device, same day) is a no-op.
    assert client.post("/api/morning-checkin", json=payload).status_code == 200
    state = ComplianceState.query.filter_by(user_id=u.id).first()
    assert state.consecutive_misses == misses_before + 1  # not double-counted


# ── app.js source tripwires ─────────────────────────────────────────────────

def test_no_fabricated_morning_checkin_in_appjs():
    # The morning popup must never auto-complete the check-in with invented
    # neutral scores the athlete never entered.
    assert "Auto-completed via morning popup" not in APP_JS


def test_no_dead_compliance_refresh_call_in_appjs():
    # /api/compliance/refresh never existed as a route; the client must not
    # call it (the compliance event now fires in the morning-checkin POST).
    assert "'/api/compliance/refresh'" not in APP_JS


def test_falsy_zero_helpers_present_and_used():
    assert "function resolveLoggedReps(" in APP_JS
    assert "function resolvePrefillWeight(" in APP_JS
    # The three set-logging paths all route reps through the canonical helper.
    assert APP_JS.count("resolveLoggedReps(") >= 4  # def + 3 call sites
    # No remaining `repsTyped || repsTarget`-style truthy fallback.
    assert "repsTyped || repsTarget" not in APP_JS
    assert "repsTyped || parseInt(_focusTargetReps)" not in APP_JS


def test_no_sw_sync_handoff_in_appjs():
    # The outbox replay must run from the page — index.html unregisters every
    # service worker, so a reg.sync handoff silently loses queued sets.
    assert "reg.sync.register" not in APP_JS
    assert "function replayOutbox(" in APP_JS
