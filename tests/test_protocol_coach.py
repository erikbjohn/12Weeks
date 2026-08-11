"""tests/test_protocol_coach.py — TDD for the coach integration of the
peptide protocol (Task 7): the `protocol_status` context-builder, its
prompt injection, the `get_protocol_status` tool, CORE_PROMPT rule 22
(bounded anomaly attribution), and the rule-6 late-hours carve-out for a
scheduled dose.

Fixture pattern: SHORT-LIVED contexts (test_protocol_api.py style), NOT
the module-scoped held-open pattern test_cut_coaching.py uses for its
plain-python-value seeding. `app_ctx` only creates tables; every DB write
opens its own `with app_.app_context():` block. Builder/prompt calls that
need `current_user` open their own `with app_.test_request_context():`
block and do the User lookup + `login_user` + builder call all inside
THAT single context, so nothing crosses a session boundary (avoids
DetachedInstanceError — the trap test_protocol_api.py documents).

escalation_window / next_escalation semantics: CORE_PROMPT rule 22 needs a
LOOK-BACK question ("did we recently escalate, such that a symptom might
still be attributable") — the OPPOSITE of protocol.escalation_window's own
forward-looking ("is an increase coming up") docstring. The builder gets
this by evaluating the SAME pure functions from `today - 6d` instead of
`today` (see coach_assembler._build_protocol_status's docstring). Tests
here pin that behavior with real (non-monkeypatched) protocol.py math.
"""
import json
from datetime import date, datetime, timedelta

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
        from models import User, PeptideDose, PeptideVial, LabReminder
        u = User.query.filter_by(email=email).first()
        if not u:
            u = User(email=email, timezone="UTC")
            db.session.add(u)
            db.session.commit()
        PeptideDose.query.filter_by(user_id=u.id).delete()
        PeptideVial.query.filter_by(user_id=u.id).delete()
        LabReminder.query.filter_by(user_id=u.id).delete()
        db.session.commit()
        return u.id
    return _app_do(app_, _do)


def _add_dose(app_, db, user_id, d, time_s, event_type, compound, dose_mg,
              syringe="10u", site="Thigh", notes=None, taken_at=None):
    def _do():
        from models import PeptideDose
        row = PeptideDose(
            user_id=user_id, date=d, time=time_s, event_type=event_type,
            compound=compound, dose_mg=dose_mg, syringe_units=syringe,
            site=site, notes=notes, taken_at=taken_at,
        )
        db.session.add(row)
        db.session.commit()
        return row.id
    return _app_do(app_, _do)


def _add_vial(app_, db, user_id, compound, total_mg, reconstituted_on, expiry_days):
    def _do():
        from models import PeptideVial
        v = PeptideVial(user_id=user_id, compound=compound, total_mg=total_mg,
                         reconstituted_on=reconstituted_on, expiry_days=expiry_days)
        db.session.add(v)
        db.session.commit()
        return v.id
    return _app_do(app_, _do)


def _add_lab(app_, db, user_id, label, due_date, completed_at=None):
    def _do():
        from models import LabReminder
        row = LabReminder(user_id=user_id, label=label, due_date=due_date,
                           completed_at=completed_at)
        db.session.add(row)
        db.session.commit()
        return row.id
    return _app_do(app_, _do)


def _protocol_status_as(app_, user_id, today, monkeypatch):
    """Log the user in under a fresh test_request_context and call the
    builder directly — the User lookup, login_user, and builder call all
    happen inside the SAME context so nothing crosses a session boundary."""
    from flask_login import login_user
    from models import User
    import coach_assembler as ca
    with app_.test_request_context():
        u = User.query.get(user_id)
        login_user(u, force=True)
        monkeypatch.setattr(ca, "_user_today", lambda: today)
        return ca._build_protocol_status()["protocol_status"]


# ── (a) escalation window (look-back) + next_escalation ─────────────────────

def test_escalation_window_true_and_next_escalation_reports_recent_step(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "esc-window@test.com")
    _add_dose(app_, db, uid, date(2026, 9, 7), "07:00", "Injection", "Retatrutide", 3)
    _add_dose(app_, db, uid, date(2026, 9, 21), "07:00", "Injection", "Retatrutide", 4)

    ps = _protocol_status_as(app_, uid, date(2026, 9, 22), monkeypatch)

    assert ps is not None
    assert ps["escalation_window"] is True
    assert ps["next_escalation"] is not None
    assert ps["next_escalation"]["date"] == date(2026, 9, 21)
    assert ps["next_escalation"]["kind"] == "dose"


def test_escalation_window_false_eight_days_after_step(app_ctx, monkeypatch):
    """8 days after the escalation, the look-back window has closed."""
    app_, db = app_ctx
    uid = _make_user(app_, db, "esc-window-closed@test.com")
    _add_dose(app_, db, uid, date(2026, 9, 7), "07:00", "Injection", "Retatrutide", 3)
    _add_dose(app_, db, uid, date(2026, 9, 21), "07:00", "Injection", "Retatrutide", 4)

    ps = _protocol_status_as(app_, uid, date(2026, 9, 29), monkeypatch)

    assert ps["escalation_window"] is False


def test_escalation_window_active_through_day_plus_6(app_ctx, monkeypatch):
    """Window covers the escalation date through 6 days later (7 calendar
    days total, inclusive)."""
    app_, db = app_ctx
    uid = _make_user(app_, db, "esc-window-plus6@test.com")
    _add_dose(app_, db, uid, date(2026, 9, 7), "07:00", "Injection", "Retatrutide", 3)
    _add_dose(app_, db, uid, date(2026, 9, 21), "07:00", "Injection", "Retatrutide", 4)

    ps = _protocol_status_as(app_, uid, date(2026, 9, 27), monkeypatch)  # d+6

    assert ps["escalation_window"] is True


def test_escalation_window_closed_at_day_plus_7(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "esc-window-plus7@test.com")
    _add_dose(app_, db, uid, date(2026, 9, 7), "07:00", "Injection", "Retatrutide", 3)
    _add_dose(app_, db, uid, date(2026, 9, 21), "07:00", "Injection", "Retatrutide", 4)

    ps = _protocol_status_as(app_, uid, date(2026, 9, 28), monkeypatch)  # d+7

    assert ps["escalation_window"] is False


def test_escalation_window_true_on_the_escalation_day_itself(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "esc-window-sameday@test.com")
    _add_dose(app_, db, uid, date(2026, 9, 7), "07:00", "Injection", "Retatrutide", 3)
    _add_dose(app_, db, uid, date(2026, 9, 21), "07:00", "Injection", "Retatrutide", 4)

    ps = _protocol_status_as(app_, uid, date(2026, 9, 21), monkeypatch)

    assert ps["escalation_window"] is True
    assert ps["next_escalation"]["date"] == date(2026, 9, 21)


# ── (b) zero PeptideDose rows -> block absent ────────────────────────────────

def test_builder_returns_none_with_zero_rows(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "esc-zero@test.com")

    from flask_login import login_user
    from models import User
    import coach_assembler as ca
    with app_.test_request_context():
        u = User.query.get(uid)
        login_user(u, force=True)
        result = ca._build_protocol_status()
    assert result == {"protocol_status": None}


# ── missed dose with placeholder rule ────────────────────────────────────────

def test_missed_dose_rule_is_confirm_with_doctor(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "esc-missed@test.com")
    today = date(2026, 8, 10)
    yesterday = today - timedelta(days=1)
    _add_dose(app_, db, uid, yesterday, "07:00", "Injection", "BPC-157", 0.25)

    ps = _protocol_status_as(app_, uid, today, monkeypatch)

    assert len(ps["missed"]) == 1
    assert ps["missed"][0]["rule"] == "confirm with your doctor"


# ── (f) watch_fors_active only within +/-3 days ──────────────────────────────

def test_watch_fors_active_only_within_3_days(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "esc-watchfors@test.com")
    today = date(2026, 8, 10)
    _add_dose(app_, db, uid, today, "07:00", "Injection", "BPC-157", 0.25)                     # 0d -> IN
    _add_dose(app_, db, uid, today - timedelta(days=3), "07:00", "Injection", "KPV", 1)        # -3d -> IN (boundary)
    _add_dose(app_, db, uid, today - timedelta(days=4), "07:00", "Injection", "TB-500", 2.5)   # -4d -> OUT
    _add_dose(app_, db, uid, today + timedelta(days=3), "07:00", "Injection", "GHK-Cu", 1)     # +3d -> IN (boundary)
    _add_dose(app_, db, uid, today + timedelta(days=4), "07:00", "Injection", "Tesamorelin", 2)  # +4d -> OUT

    ps = _protocol_status_as(app_, uid, today, monkeypatch)

    assert set(ps["watch_fors_active"].keys()) == {"BPC-157", "KPV", "GHK-Cu"}
    assert ps["watch_fors_active"]["BPC-157"]  # non-empty watch_fors list


# ── summary / current_retatrutide_mg ─────────────────────────────────────────

def test_summary_lists_todays_doses_and_current_retatrutide_mg(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "esc-summary@test.com")
    today = date(2026, 8, 10)
    _add_dose(app_, db, uid, today, "07:00", "Injection", "BPC-157", 0.25)
    _add_dose(app_, db, uid, today, "07:15", "Injection", "Retatrutide", 2)
    _add_dose(app_, db, uid, today - timedelta(days=10), "07:00", "Injection", "Retatrutide", 1)

    ps = _protocol_status_as(app_, uid, today, monkeypatch)

    compounds = {s["compound"] for s in ps["summary"]}
    assert compounds == {"BPC-157", "Retatrutide"}
    assert ps["current_retatrutide_mg"] == 2


def test_current_retatrutide_mg_survives_a_held_dose_fix_round_1(app_ctx, monkeypatch):
    """Fix round 1 repro (reviewer, reproduced live): 3mg on 9/7, escalate
    to 4mg on 9/21, HOLD (dose_mg=0) on 9/28, today=9/29. Before the fix
    this reported 0.0 (the held row) instead of 4.0 (the actual current
    dose) — the builder computed it ad hoc instead of delegating to
    protocol.current_dose_mg, which excludes held rows."""
    app_, db = app_ctx
    uid = _make_user(app_, db, "esc-heldfix@test.com")
    _add_dose(app_, db, uid, date(2026, 9, 7), "07:00", "Injection", "Retatrutide", 3)
    _add_dose(app_, db, uid, date(2026, 9, 21), "07:00", "Injection", "Retatrutide", 4)
    _add_dose(app_, db, uid, date(2026, 9, 28), "07:00", "Injection", "Retatrutide", 0)

    ps = _protocol_status_as(app_, uid, date(2026, 9, 29), monkeypatch)

    assert ps["current_retatrutide_mg"] == 4.0


# ── vial reorder flags + labs due ────────────────────────────────────────────

def test_vial_flags_only_include_reorder_flagged(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "esc-vials@test.com")
    today = date(2026, 8, 10)
    # Reconstituted long ago with a short expiry -> already past reorder_by.
    _add_vial(app_, db, uid, "BPC-157", 10.0, today - timedelta(days=25), 28)
    # Fresh vial, plenty of runway -> not flagged.
    _add_vial(app_, db, uid, "KPV", 10.0, today, 28)
    _add_dose(app_, db, uid, today, "07:00", "Injection", "BPC-157", 0.25)
    _add_dose(app_, db, uid, today, "07:00", "Injection", "KPV", 1)

    ps = _protocol_status_as(app_, uid, today, monkeypatch)

    flagged = {v["compound"] for v in ps["vial_flags"]}
    assert "BPC-157" in flagged
    assert "KPV" not in flagged


def test_labs_due_within_7_days_excludes_far_out_and_completed(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "esc-labs@test.com")
    today = date(2026, 8, 10)
    _add_dose(app_, db, uid, today, "07:00", "Injection", "BPC-157", 0.25)
    _add_lab(app_, db, uid, "Lipid panel", today + timedelta(days=3))
    _add_lab(app_, db, uid, "Far-out panel", today + timedelta(days=30))
    _add_lab(app_, db, uid, "Already done", today + timedelta(days=2),
             completed_at=datetime(2026, 8, 1, 12, 0))

    ps = _protocol_status_as(app_, uid, today, monkeypatch)

    labels = {l["label"] for l in ps["labs_due"]}
    assert labels == {"Lipid panel"}


# ── (c) get_protocol_status tool ─────────────────────────────────────────────

def test_execute_tool_returns_real_seeded_rows(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "esc-tool@test.com")
    today = date(2026, 8, 10)
    _add_dose(app_, db, uid, today, "07:00", "Injection", "BPC-157", 0.25)
    _add_dose(app_, db, uid, today - timedelta(days=1), "07:00", "Injection", "BPC-157", 0.25,
              taken_at=datetime(2026, 8, 9, 14, 0))
    _add_dose(app_, db, uid, date(2026, 9, 7), "07:00", "Injection", "Retatrutide", 3)
    _add_dose(app_, db, uid, date(2026, 9, 21), "07:00", "Injection", "Retatrutide", 4)

    import coach_tools as ct
    monkeypatch.setattr(ct, "_user_local_today", lambda user_id: today)
    with app_.app_context():
        result_json = ct.execute_tool("get_protocol_status", {"days": 7}, uid)
    result = json.loads(result_json)

    assert "error" not in result
    dates_in_history = {d["date"] for d in result["dose_history"]}
    assert str(today) in dates_in_history
    assert str(today - timedelta(days=1)) in dates_in_history
    taken_row = next(d for d in result["dose_history"] if d["date"] == str(today - timedelta(days=1)))
    assert taken_row["taken"] is True
    assert result["adherence_7d"]["scheduled"] == 2
    # today=Aug 10; the Sep 21 escalation is ~42 days out, well past the
    # 14-day horizon -> real pin (not a trivial always-true "or []").
    assert result["escalation_dates_next_14d"] == []


def test_execute_tool_escalation_dates_next_14d_includes_upcoming_step(app_ctx, monkeypatch):
    """Same seeded escalation as above, but 'today' is moved to within 14
    days of it -> the date must actually appear (pins the True branch that
    the far-future test above can't exercise)."""
    app_, db = app_ctx
    uid = _make_user(app_, db, "esc-tool-upcoming@test.com")
    _add_dose(app_, db, uid, date(2026, 9, 7), "07:00", "Injection", "Retatrutide", 3)
    _add_dose(app_, db, uid, date(2026, 9, 21), "07:00", "Injection", "Retatrutide", 4)
    today = date(2026, 9, 10)  # 11 days before the Sep 21 escalation

    import coach_tools as ct
    monkeypatch.setattr(ct, "_user_local_today", lambda user_id: today)
    with app_.app_context():
        result_json = ct.execute_tool("get_protocol_status", {"days": 7}, uid)
    result = json.loads(result_json)

    assert "error" not in result
    assert "2026-09-21" in result["escalation_dates_next_14d"]


def test_tool_schema_and_dispatch_registered():
    from coach_tools import TOOLS, _DISPATCH
    names = {t["name"] for t in TOOLS}
    assert "get_protocol_status" in names
    tool_def = next(t for t in TOOLS if t["name"] == "get_protocol_status")
    assert tool_def["input_schema"]["properties"]["days"]["default"] == 7
    assert "get_protocol_status" in _DISPATCH


def test_execute_tool_unknown_dispatch_still_safe(app_ctx):
    """Sanity: execute_tool never raises, even for a made-up user_id."""
    app_, db = app_ctx
    import coach_tools as ct
    with app_.app_context():
        result_json = ct.execute_tool("get_protocol_status", {"days": 7}, 999999)
    result = json.loads(result_json)
    assert "error" not in result
    assert result["dose_history"] == []


# ── (d) CORE_PROMPT text assertions ──────────────────────────────────────────

def test_rule22_covers_escalation_confirm_and_causation_language():
    from coach_assembler import CORE_PROMPT
    start = CORE_PROMPT.index("22. PEPTIDE PROTOCOL")
    end = CORE_PROMPT.index("</non_negotiable_rules>")
    rule22 = CORE_PROMPT[start:end]

    assert "escalation" in rule22.lower()
    assert "confirm with your doctor" in rule22
    assert "never assert" in rule22.lower()
    assert "<lift_trend>" in rule22
    assert "lift_decline_suspected" in rule22
    assert "rule 20" in rule22.lower()


def test_rule21_first_line_present_verbatim_unchanged():
    from coach_assembler import CORE_PROMPT
    assert (
        "21. RUN THE CUT — REACT TO THE SCALE. When <cut_status> is present "
        "(the athlete is cutting), the scale is the #1 signal and you OWN it "
        "every day. Read cut_status every response:"
    ) in CORE_PROMPT


def test_rule6_carveout_present_and_no_hardcoded_2200():
    from coach_assembler import CORE_PROMPT
    start = CORE_PROMPT.index("6. TIME OF DAY")
    end = CORE_PROMPT.index("7. FOOD SAFETY")
    rule6 = CORE_PROMPT[start:end]

    assert "scheduled dose at or after 21:00" in rule6
    assert "22:00" not in rule6
    assert "<protocol_status>" in rule6


# ── (e) prompt injection presence / absence ──────────────────────────────────

def test_prompt_contains_protocol_status_tag_and_missed_rule_text(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "esc-inject@test.com")
    today = date(2026, 8, 10)
    yesterday = today - timedelta(days=1)
    _add_dose(app_, db, uid, yesterday, "07:00", "Injection", "BPC-157", 0.25)  # -> missed

    from flask_login import login_user
    from models import User
    import coach_assembler as ca
    with app_.test_request_context():
        u = User.query.get(uid)
        login_user(u, force=True)
        monkeypatch.setattr(ca, "_user_today", lambda: today)
        frag = ca._build_protocol_status()
        ctx = {"athlete_name": "Erik", **frag}
        prompt = ca.assemble_prompt("morning_checkin", ctx)

    # NOTE: rule 6's carve-out text also mentions "<protocol_status>" as a
    # reference regardless of whether the block is rendered — the CLOSING
    # tag only ever appears when the injected block itself is present, so
    # it's the unambiguous signal.
    assert "</protocol_status>" in prompt
    assert "confirm with your doctor" in prompt


def test_prompt_omits_protocol_status_tag_with_zero_rows(app_ctx, monkeypatch):
    app_, db = app_ctx
    uid = _make_user(app_, db, "esc-inject-none@test.com")

    from flask_login import login_user
    from models import User
    import coach_assembler as ca
    with app_.test_request_context():
        u = User.query.get(uid)
        login_user(u, force=True)
        frag = ca._build_protocol_status()
        assert frag == {"protocol_status": None}
        ctx = {"athlete_name": "Erik", **frag}
        prompt = ca.assemble_prompt("morning_checkin", ctx)

    assert "</protocol_status>" not in prompt


# ── (6) agents wiring: everything that requires cut_status also requires protocol_status ──

def test_agents_with_cut_status_also_require_protocol_status():
    from coach_agents import AGENTS
    checked = 0
    for name, agent in AGENTS.items():
        reqs = agent.get("requires", [])
        if "cut_status" in reqs:
            checked += 1
            assert "protocol_status" in reqs, f"{name} requires cut_status but not protocol_status"
    assert checked >= 4  # conversation, morning_checkin, meals_complete, nutritionist


def test_chat_opened_and_end_of_day_require_protocol_status():
    """chat_opened and end_of_day don't carry cut_status (so the loop above
    never checks them), but they still need protocol_status reachable so the
    dose-night greeting ("Tesamorelin at 22:00 — take it, check it off,
    lights out") and the rule-6 late-hours carve-out fire from a greeting,
    not just from mid-day agents."""
    from coach_agents import AGENTS
    assert "protocol_status" in AGENTS["chat_opened"]["requires"]
    assert "protocol_status" in AGENTS["end_of_day"]["requires"]
