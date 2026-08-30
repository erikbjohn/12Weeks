"""tests/test_deload_override_and_battery.py — Erik's 2026-08-30 directives.

1. Body battery must be the watch's ACTUAL last level (bodyBatteryValuesArray),
   never charged-minus-drained (the daily net — it went negative in prod and the
   coach argued from it; audit finding S038).
2. The athlete's deload veto is FINAL and codified: CORE_PROMPT orders the chat
   coach to argue once then emit the [DELOAD] marker with the athlete's call.
3. Lifting volume is PROTECTED during the cut: the strength planner is told to
   manage fatigue through RUNNING volume first, may return
   {"reduce_running": {"call", "reason"}}, and that call reaches the decision.
"""
import json
from types import SimpleNamespace

import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
    yield app, db


def _user(app_, db, email):
    with app_.app_context():
        from models import User
        u = User.query.filter_by(email=email).first()
        if not u:
            u = User(email=email, timezone="America/Indianapolis")
            db.session.add(u)
            db.session.commit()
        return u.id


# ── 1. body battery is the actual level ──────────────────────────────────

def _bb_client(payload):
    from garmin_client import GarminClient
    gc = GarminClient(user_id=1)
    gc._connected = True
    gc.api = SimpleNamespace(get_body_battery=lambda day: payload)
    return gc


def test_body_battery_is_last_level_from_values_array():
    gc = _bb_client([{
        "charged": 60, "drained": 80,  # daily net = -20 (the old, wrong "current")
        "bodyBatteryValuesArray": [[1756500000000, "MEASURED", 55, 1.0],
                                   [1756540000000, "MEASURED", 34, 1.0]],
    }])
    out = gc._get_body_battery("2026-08-30")
    assert out["current"] == 34, "current must be the LAST measured level, not charged-drained"
    assert out["charged"] == 60 and out["drained"] == 80


def test_body_battery_none_when_no_levels_reported():
    out = _bb_client([{"charged": 60, "drained": 80}])._get_body_battery("2026-08-30")
    assert out["current"] is None, "no levels → honest None, never the negative net"
    out2 = _bb_client([{"charged": 10, "drained": 4,
                        "bodyBatteryValuesArray": []}])._get_body_battery("2026-08-31")
    assert out2["current"] is None


def test_body_battery_three_element_entries():
    gc = _bb_client([{"charged": 5, "drained": 50,
                      "bodyBatteryValuesArray": [[1756500000000, "MEASURED", 22]]}])
    assert gc._get_body_battery("2026-09-01")["current"] == 22


# ── 2. the athlete's veto is final in chat ───────────────────────────────

def test_core_prompt_makes_deload_override_final():
    from coach_assembler import CORE_PROMPT
    assert "DELOAD IS THE ATHLETE'S FINAL CALL" in CORE_PROMPT
    i_rule = CORE_PROMPT.index("DELOAD IS THE ATHLETE'S FINAL CALL")
    assert i_rule < CORE_PROMPT.rindex("<markers>"), "must be a numbered rule, not marker fine print"
    assert "argue it ONCE" in CORE_PROMPT


# ── 3. lifting is protected; fatigue comes out of running first ──────────

class _CapturingMessages:
    def __init__(self, text):
        self._text = text
        self.kwargs = None

    def create(self, **kw):
        self.kwargs = kw
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self._text)],
                               stop_reason="end_turn")


def test_strength_prompt_protects_lifting_and_offers_reduce_running(app_ctx, monkeypatch):
    app_, db = app_ctx
    import coach_planning_program as cpp
    uid = _user(app_, db, "protect-lifting@test.com")
    fake = _CapturingMessages(json.dumps({
        "deload": {"call": False, "reason": "athlete progressing"},
        "reduce_running": {"call": True, "reason": "HRV suppressed; trim easy-run volume, keep lifts"},
        "0": [{"exercise": "Barbell Bench Press", "sets": 4, "reps": "5", "weight": 135,
               "rest": "2 min", "why": "progress"}],
    }))
    monkeypatch.setattr(cpp, "_anthropic_client", lambda: SimpleNamespace(messages=fake))
    with app_.app_context():
        _, _, decision = cpp.generate_week_program(
            uid, 5, {"phase": 3, "goal_type": "cut", "target_weekly_sets": 96, "train_days": 6})
    sent = (fake.kwargs["system"] or "") + (fake.kwargs["messages"][0]["content"] or "")
    assert "LIFTING VOLUME IS PROTECTED" in sent
    assert "RUNNING volume FIRST" in sent
    assert decision["deload"] is False
    assert decision["reduce_running"] == {"call": True,
                                          "reason": "HRV suppressed; trim easy-run volume, keep lifts"}


def test_reduce_running_defaults_to_none(app_ctx, monkeypatch):
    app_, db = app_ctx
    import coach_planning_program as cpp
    uid = _user(app_, db, "protect-lifting2@test.com")
    fake = _CapturingMessages(json.dumps({
        "0": [{"exercise": "Barbell Bench Press", "sets": 4, "reps": "5", "weight": 135,
               "rest": "2 min", "why": "progress"}]}))
    monkeypatch.setattr(cpp, "_anthropic_client", lambda: SimpleNamespace(messages=fake))
    with app_.app_context():
        _, _, decision = cpp.generate_week_program(
            uid, 5, {"phase": 3, "goal_type": "cut", "target_weekly_sets": 96, "train_days": 6})
    assert decision.get("reduce_running") is None
