"""LLM-powered lifting prescription agent.

When the deterministic progression engine (training_engine.compute_next_targets)
has no SetLog history for an exercise, fall back to this agent. It asks Claude
to reason about a sensible starting weight based on the user's existing lift
data, estimated 1RMs, body weight, and exercise-specific intensity guidance.

Better than:
- Returning None / 0 (forces the user to guess)
- Hard-coded "70% of 1RM" rules (don't account for exercise relationships)

Output is stored as a regular WeeklyPrescription row so the user can override.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

log = logging.getLogger(__name__)


SYSTEM_PROMPT = """\
You are a strength coach prescribing a starting weight for a single lift for an athlete.

You will receive: the athlete's body weight, their estimated 1RMs and recent peak weights for OTHER exercises, the target exercise, and the prescribed scheme (e.g. "4x3 at ~70-76% wave").

Your job: pick a sensible starting weight in pounds. Be conservative — better to start light and build than to fail a max.

Standard exercise relationships (use as a starting point, not absolute):
- Front Squat ≈ 80-85% of Back Squat
- Overhead Press ≈ 60-65% of Bench Press
- Bench Press ≈ 75-80% of Back Squat for a balanced lifter
- Romanian Deadlift ≈ 70-80% of Conventional Deadlift
- Bulgarian Split Squat (per leg, dumbbell or barbell) ≈ 30-40% of Back Squat
- Weighted Pull-Up ≈ start at bodyweight, add 5-10 lb when 4x8 is clean
- Hip Thrust ≈ 1.0-1.5x Back Squat for trained athletes
- Lat Pulldown ≈ 60-70% of bodyweight for trained
- Bent-Over Row ≈ 60-70% of Bench Press

Phase guidance:
- If the scheme says "speed-focused" or "wave 70-76%" → conservative side
- If "RPE 7" → moderate
- If pure hypertrophy "4x8-12" → start at a weight you can move with form across all sets

Output ONLY a JSON object on a single line, no prose, no code fences:
{"weight_lbs": <number>, "reasoning": "<one short sentence>"}
"""


def prescribe_starting_weight(
    user_id: int,
    exercise_name: str,
    prescribed_scheme: str = "",
    note: str = "",
) -> Optional[dict]:
    """Ask Claude for a sensible starting weight for `exercise_name`.

    Returns {"weight_lbs": float, "reasoning": str} or None on failure.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log.warning("lifting_agent: ANTHROPIC_API_KEY not set; skipping")
        return None

    # Gather user context (lazy imports to avoid circular)
    from models import ExerciseLog, SetLog, BodyWeight

    bw_row = (BodyWeight.query
              .filter_by(user_id=user_id)
              .order_by(BodyWeight.log_date.desc())
              .first())
    body_weight = bw_row.weight_lbs if bw_row else None

    # Estimated 1RMs = best recent Epley estimate per exercise from SetLog (the
    # live table). ExerciseLog.estimated_1rm is dead (table unwritten since April).
    one_rms: dict[str, float] = {}
    e1rm_rows = (SetLog.query
                 .filter(SetLog.user_id == user_id, SetLog.weight.isnot(None))
                 .order_by(SetLog.logged_date.desc())
                 .limit(200).all())
    for s in e1rm_rows:
        if not s.weight:
            continue
        est = round(float(s.weight) * (1 + (s.reps or 0) / 30.0), 1)
        if s.exercise_name not in one_rms or est > one_rms[s.exercise_name]:
            one_rms[s.exercise_name] = est

    # Recent peak weights (top weight per exercise across last ~120 done sets)
    recent_peaks: dict[str, float] = {}
    sl_rows = (SetLog.query
               .filter(SetLog.user_id == user_id, SetLog.done.is_(True))
               .order_by(SetLog.logged_date.desc())
               .limit(120).all())
    for s in sl_rows:
        if s.weight is None:
            continue
        peak = recent_peaks.get(s.exercise_name)
        if peak is None or s.weight > peak:
            recent_peaks[s.exercise_name] = float(s.weight)

    user_msg = (
        f"Target exercise: {exercise_name}\n"
        f"Prescribed scheme: {prescribed_scheme}\n"
        f"Coaching note: {note or '(none)'}\n"
        f"Athlete body weight: {body_weight} lb\n\n"
        f"Estimated 1RMs (other lifts):\n"
        f"{json.dumps(one_rms, indent=2) if one_rms else '(none)'}\n\n"
        f"Recent peak weights across all logged sets:\n"
        f"{json.dumps(recent_peaks, indent=2) if recent_peaks else '(none)'}\n\n"
        f"What's a sensible starting weight (lb) for {exercise_name}? Output JSON."
    )

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key, timeout=20.0)
        response = client.messages.create(
            model=os.environ.get("LIFTING_AGENT_MODEL", "claude-sonnet-4-6"),
            max_tokens=200,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = response.content[0].text.strip()
    except Exception as e:
        log.warning("lifting_agent: API call failed: %s", e)
        return None

    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    # Find first { ... }
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        result = json.loads(text[start:end])
    except Exception as e:
        log.warning("lifting_agent: parse failed for %r: %s", text[:200], e)
        return None

    weight = result.get("weight_lbs")
    if not isinstance(weight, (int, float)) or weight <= 0:
        log.warning("lifting_agent: bad weight in response: %r", result)
        return None

    return {
        "weight_lbs": round(float(weight), 1),
        "reasoning": str(result.get("reasoning", ""))[:300],
    }
