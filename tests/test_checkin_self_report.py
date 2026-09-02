"""S021 (real fix): check-in numerics come ONLY from the athlete's own words.

The Sep 1 2026 loop: the coach narrated Garmin ("HRV 30, high risk"), the
client posted the chat DOM's textContent (coach bubbles included) to the
extractor, Haiku turned the coach's narration into mood 4 / anxiety 6 / soreness
5, and the coach then read those back as the athlete's pattern. Thirteen
consecutive days of soreness=5 in prod with the athlete never asked.
"""
import json
import pytest


@pytest.fixture
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def _login(app_, db, email="selfreport@test.com"):
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


def _seed(db, u, d, msgs):
    from models import ChatMessage, MorningCheckIn
    ChatMessage.query.filter_by(user_id=u.id).delete()
    MorningCheckIn.query.filter_by(user_id=u.id).delete()
    for role, content in msgs:
        db.session.add(ChatMessage(role=role, content=content, log_date=d, user_id=u.id))
    db.session.add(MorningCheckIn(user_id=u.id, log_date=d, notes="[Coach conversation check-in]"))
    db.session.commit()


def _fake_anthropic(monkeypatch, reply, seen):
    import anthropic

    class _Msg:
        content = [type("T", (), {"text": json.dumps(reply)})()]

    class _Fake:
        def __init__(self, *a, **k):
            def create(**kw):
                seen.append(kw["messages"][0]["content"])
                return _Msg()
            self.messages = type("M", (), {"create": staticmethod(create)})()

    monkeypatch.setattr(anthropic, "Anthropic", _Fake)


COACH = ("assistant", "Synced. Last night: 6.3h, sleep score 67. HRV dropped to 30 against a 45 "
                      "average, flagged LOW. Readiness 30/100, high risk. The CNS still hasn't cleared.")


def test_coach_narration_never_becomes_self_report(app_ctx, monkeypatch):
    """Athlete said only 'Check again'. Whatever the model returns, nothing
    the coach said can be stored — every value must quote the athlete."""
    app_, db = app_ctx
    u, client = _login(app_, db)
    from app import _user_today
    from models import MorningCheckIn
    d = _user_today()
    _seed(db, u, d, [("user", "[MORNING_CHECKIN] RIGHT NOW it is Tuesday 4:57 AM. Start the check-in."),
                     ("assistant", "How many hours did you actually get?"),
                     ("user", "Check again"), COACH])
    seen = []
    # A misbehaving model quoting the COACH's words and filling defaults.
    _fake_anthropic(monkeypatch, {
        "sleep_quality": {"value": 4, "quote": "6.3h, sleep score 67"},
        "stress_level": {"value": 7, "quote": "high risk"},
        "soreness": {"value": 5, "quote": ""},
        "mood": {"value": 4, "quote": "CNS still hasn't cleared"},
        "motivation": 5,
        "anxiety": {"value": 6, "quote": "HRV dropped to 30"},
    }, seen)
    r = client.post("/api/morning-checkin/extract", json={"conversation": "coach text the client used to send"})
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    for k in ("sleep_quality", "stress_level", "soreness", "mood", "motivation", "anxiety"):
        assert body[k] is None, (k, body)
    ci = MorningCheckIn.query.filter_by(user_id=u.id, log_date=d).first()
    assert (ci.sleep_quality, ci.stress_level, ci.soreness, ci.mood, ci.motivation, ci.anxiety) == (None,) * 6
    assert "extracted" not in (ci.notes or "")
    # The prompt the model saw contains the athlete's words and NONE of the coach's.
    assert "Check again" in seen[0]
    assert "HRV" not in seen[0] and "sleep score" not in seen[0] and "MORNING_CHECKIN" not in seen[0]
    assert "coach text the client used to send" not in seen[0]


def test_athlete_stated_values_are_stored_with_quotes(app_ctx, monkeypatch):
    app_, db = app_ctx
    u, client = _login(app_, db)
    from app import _user_today
    from models import MorningCheckIn
    d = _user_today()
    _seed(db, u, d, [("user", "[MORNING_CHECKIN] start"),
                     ("assistant", "How did you sleep?"),
                     ("user", "Slept like garbage, maybe a 3. Legs are fine, not sore at all."), COACH])
    seen = []
    _fake_anthropic(monkeypatch, {
        "sleep_quality": {"value": 3, "quote": "Slept like garbage, maybe a 3"},
        "soreness": {"value": 1, "quote": "not sore at all"},
        "anxiety": {"value": 6, "quote": "HRV dropped to 30"},   # coach's words → rejected
        "mood": None, "stress_level": None, "motivation": None,
    }, seen)
    r = client.post("/api/morning-checkin/extract", json={})
    body = r.get_json()
    assert body["sleep_quality"] == 3 and body["soreness"] == 1 and body["anxiety"] is None, body
    assert body["rejected"] == ["anxiety"]
    ci = MorningCheckIn.query.filter_by(user_id=u.id, log_date=d).first()
    assert (ci.sleep_quality, ci.soreness, ci.anxiety, ci.mood) == (3, 1, None, None)
    assert "[self-report extracted: sleep_quality,soreness]" in ci.notes


def test_no_athlete_turns_means_no_model_call_and_no_write(app_ctx, monkeypatch):
    app_, db = app_ctx
    u, client = _login(app_, db)
    from app import _user_today
    from models import MorningCheckIn
    d = _user_today()
    _seed(db, u, d, [("user", "[MORNING_CHECKIN] start"), COACH])
    seen = []
    _fake_anthropic(monkeypatch, {"anxiety": {"value": 9, "quote": "x"}}, seen)
    r = client.post("/api/morning-checkin/extract", json={})
    assert r.status_code == 200
    assert r.get_json()["skipped"]
    assert seen == []
    ci = MorningCheckIn.query.filter_by(user_id=u.id, log_date=d).first()
    assert ci.anxiety is None


def test_client_never_sends_chat_dom_to_extractor():
    src = open("static/app.js").read()
    i = src.index("/api/morning-checkin/extract")
    window = src[i - 800:i + 300]
    assert "textContent" not in window, "extractor must not receive the chat DOM (coach bubbles)"
    assert "conversation:" not in window


def test_missed_marker_and_out_of_range_scores_store_null(app_ctx):
    app_, db = app_ctx
    u, client = _login(app_, db, email="missed@test.com")
    from app import _user_today
    from models import MorningCheckIn
    d = _user_today()
    MorningCheckIn.query.filter_by(user_id=u.id).delete(); db.session.commit()
    r = client.post("/api/morning-checkin", json={
        "date": d.isoformat(), "sleep_quality": 0, "stress_level": 0, "soreness": 0,
        "mood": 0, "motivation": 0, "anxiety": 0, "notes": "[MISSED] x", "missed": True})
    assert r.status_code == 200
    ci = MorningCheckIn.query.filter_by(user_id=u.id, log_date=d).first()
    assert (ci.sleep_quality, ci.stress_level, ci.soreness, ci.mood, ci.motivation, ci.anxiety) == (None,) * 6
    # Out-of-range on a normal save is dropped, in-range kept.
    MorningCheckIn.query.filter_by(user_id=u.id).delete(); db.session.commit()
    client.post("/api/morning-checkin", json={"date": d.isoformat(), "sleep_quality": 0, "mood": 7, "anxiety": 11})
    ci = MorningCheckIn.query.filter_by(user_id=u.id, log_date=d).first()
    assert (ci.sleep_quality, ci.mood, ci.anxiety) == (None, 7, None)
    src = open("static/app.js").read()
    assert "sleep_quality: 0" not in src and "anxiety: 0" not in src
