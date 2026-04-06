"""Anger level state machine for coaching tone adaptation.

Maps compliance events to anger level transitions (0-3).
Tone strings are injected into the CORE prompt.
"""

from datetime import date, datetime, timezone


# Anger level → tone string (injected into prompt as {{anger_level_instruction}})
ANGER_LEVELS = {
    0: {
        "label": "Baseline — Saban process mode",
        "instruction": "Standard coaching intensity. Process-focused. Direct. "
                       "Acknowledge wins briefly. Name misses without drama. The bar is the bar.",
    },
    1: {
        "label": "Warning — patience is gone",
        "instruction": "No pleasantries. No acknowledging effort — only results. "
                       "Start responses by naming what was missed before anything else. "
                       "Tone is clipped, factual, cold.",
    },
    2: {
        "label": "Stern — commanding mode",
        "instruction": "Commands only. No softening. No empathy buffer. "
                       "Open every response by naming the violation directly and its consequence. "
                       "Short sentences. Hard stops. No questions.",
    },
    3: {
        "label": "Lombardi — locker room at halftime",
        "instruction": "This athlete is wasting their potential and you will not pretend otherwise. "
                       "Open with the hard truth: what they're throwing away. "
                       "Do not coach the workout yet. Make them answer for the pattern first. "
                       "One question only, at the end: 'Do you actually want this or not?' "
                       "Wait for a real answer before returning to program details.",
    },
}


def get_compliance_state(user_id):
    """Fetch or create the compliance state for a user."""
    from models import db, ComplianceState
    state = ComplianceState.query.filter_by(user_id=user_id).first()
    if not state:
        state = ComplianceState(user_id=user_id, anger_level=0, consecutive_misses=0)
        db.session.add(state)
        db.session.commit()
    return state


def update_anger_level(user_id, event, today=None):
    """
    Transition anger level based on a compliance event.

    Escalation: each miss increments consecutive_misses.
      anger_level = min(3, consecutive_misses // 2)

    De-escalation:
      full_compliance_day → reset consecutive_misses
      completed_workout → decrement consecutive_misses by 1
      pr_achieved → drop anger_level by 1

    Natural decay: if >2 days since last miss, anger drops by 1.
    """
    from models import db, ComplianceState
    if today is None:
        today = date.today()

    state = get_compliance_state(user_id)

    # Escalation events
    if event in ("missed_checkin", "missed_workout", "missed_meals", "nutrition_cheat"):
        state.consecutive_misses += 1
        state.last_miss_date = today
        state.last_escalation_date = today
        state.anger_level = min(3, state.consecutive_misses // 2)

    # De-escalation events
    elif event == "full_compliance_day":
        state.consecutive_misses = 0
        state.last_deescalation_date = today
        state.anger_level = 0
    elif event == "completed_workout":
        state.consecutive_misses = max(0, state.consecutive_misses - 1)
        state.anger_level = min(state.anger_level, min(3, max(0, state.consecutive_misses // 2)))
    elif event == "pr_achieved":
        state.anger_level = max(0, state.anger_level - 1)
        state.last_deescalation_date = today
    elif event == "streak_milestone":
        state.anger_level = 0
        state.consecutive_misses = 0
        state.last_deescalation_date = today
    elif event == "week_reset":
        # Reset weekly counter but anger persists
        pass

    # Natural decay: >2 days since last miss → drop 1 level
    if state.last_miss_date and (today - state.last_miss_date).days > 2:
        state.anger_level = max(0, state.anger_level - 1)

    state.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return state.anger_level


def get_anger_level(user_id):
    """Get current anger level (0-3)."""
    state = get_compliance_state(user_id)
    return state.anger_level


def get_anger_label(user_id):
    """Get the anger level label string for the prompt."""
    level = get_anger_level(user_id)
    return ANGER_LEVELS.get(level, ANGER_LEVELS[0])["label"]


def get_anger_instruction(user_id):
    """Get the anger level instruction string for the prompt."""
    level = get_anger_level(user_id)
    return ANGER_LEVELS.get(level, ANGER_LEVELS[0])["instruction"]
