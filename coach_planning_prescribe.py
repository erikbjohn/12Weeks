"""Per-exercise weight prescription via the strength-coach agent.

Replaces training_engine.compute_next_targets for the planning path. The
engine's deterministic rules (first-set bias, rep-drop compensation, etc.)
kept producing regressions below the athlete's proven capacity. The coach
agent reads the actual SetLog top sets across the last 4 weeks plus the
template's sets/reps schema, then prescribes weights that fit the athlete's
real capability and the phase's intent.

Engine still runs as the FALLBACK when the LLM call fails or returns
unparseable output — better to have an engine number than nothing.

Output: per-(day, exercise) target_weight. Sets/reps come from the template;
the coach doesn't change session structure.
"""
from __future__ import annotations
import os
import json
import logging
from collections import defaultdict

log = logging.getLogger(__name__)

_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday",
              "Friday", "Saturday", "Sunday"]


def _anthropic_client():
    import anthropic
    return anthropic.Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        max_retries=3,
    )


def _build_history_block(user_id: int, exercise_names: set[str], current_week: int,
                         lookback_weeks: int = 4) -> str:
    """Render the last N weeks of SetLog for each exercise as compact text.

    Each exercise gets: top set per session, dates, deload context. The coach
    uses this to anchor prescriptions on proven capacity.
    """
    from models import SetLog
    if not exercise_names:
        return "(no exercise history)"
    rows = (SetLog.query
            .filter(SetLog.user_id == user_id)
            .filter(SetLog.exercise_name.in_(list(exercise_names)))
            .filter(SetLog.weight > 0)
            .filter(SetLog.week >= max(1, current_week - lookback_weeks))
            .order_by(SetLog.exercise_name, SetLog.logged_date.desc(), SetLog.set_number)
            .all())
    if not rows:
        return "(no exercise history in the lookback window)"

    # Group by exercise → session date → list of (weight, reps)
    by_ex: dict[str, dict] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        by_ex[r.exercise_name][r.logged_date].append((r.weight, r.reps))

    lines = []
    for ex_name in sorted(by_ex.keys()):
        lines.append(f"  {ex_name}:")
        for date, sets in sorted(by_ex[ex_name].items(), reverse=True)[:4]:  # most recent 4 sessions
            top_weight = max(w for w, _ in sets)
            sets_str = ", ".join(f"{w}x{r}" for w, r in sets)
            lines.append(f"    {date}: top={top_weight} | sets=[{sets_str}]")
    return "\n".join(lines)


def generate_week_prescriptions(
    user_id: int,
    week: int,
    template_program: list[dict],
    user_context: dict,
) -> dict[tuple[int, str, int], dict]:
    """Generate per-exercise target_weight for a week via strength-coach.

    template_program: list of {day, exercise, sets, reps, exercise_order, rest}
      from the phase template — defines session STRUCTURE, not weights.
    user_context: {phase, deload, goal_type, current_weight, target_weight,
                   weeks_remaining}

    Returns: {(day_idx, exercise_name, exercise_order): target_weight}
    Empty dict on failure — caller falls back to the deterministic engine.
    """
    if not template_program:
        return {}

    exercise_names = {ex["exercise"] for ex in template_program}
    history_block = _build_history_block(user_id, exercise_names, week)

    # Render template as a structured prompt
    by_day: dict[int, list[dict]] = defaultdict(list)
    for ex in template_program:
        by_day[ex["day"]].append(ex)

    template_block_lines = []
    for day_idx in sorted(by_day.keys()):
        template_block_lines.append(f"{_DAY_NAMES[day_idx]}:")
        for ex in by_day[day_idx]:
            template_block_lines.append(
                f"  - [day={day_idx}, order={ex.get('exercise_order', 0)}] "
                f"{ex['exercise']}: {ex['sets']}x{ex['reps']}"
            )
    template_block = "\n".join(template_block_lines)

    deload = user_context.get("deload", False)
    phase = user_context.get("phase", "?")
    goal_type = user_context.get("goal_type", "recomp")
    current_wt = user_context.get("current_weight")
    target_wt = user_context.get("target_weight")
    weeks_rem = user_context.get("weeks_remaining")

    system = (
        "You are a strength coach prescribing weekly weights for a 12-week "
        "program. The session structure (sets, reps, exercise selection) is "
        "FIXED by the template. Your job is to pick the LOAD (target_weight) "
        "for each exercise AND write a 1-sentence WHY for each.\n\n"
        "ABSOLUTE RULES:\n"
        "1. NEVER prescribe below the athlete's TOP SET in the last 4 weeks "
        "   unless this is an explicit deload week (week 4 or 8). If they hit "
        "   145×5 last week, do not prescribe 140 this week. Period.\n"
        "2. Compound lifts (squat, deadlift, bench, press, row) progress +5 to "
        "   +10 lb/week in strength phases when reps are being hit clean.\n"
        "3. Accessory/isolation work (curls, raises, face pulls) progress +2.5 lb "
        "   per session when the athlete hits target reps.\n"
        "4. Bodyweight and plyometric (Box Jump, etc.): no weight prescription "
        "   needed — return 0 for target_weight.\n"
        "5. Deload weeks (4 and 8): 70-85% of prior week's working weight.\n"
        "6. Peak week (12): hold weights from week 11, do not bump.\n"
        "7. Equipment-aware: if template says 'DB Bench Press' but the athlete "
        "   logs Barbell Bench Press, they prefer the barbell — keep barbell.\n\n"
        "WHY rules: each WHY is ONE sentence (max 20 words) explaining the load "
        "choice in CONTEXT of the day's other exercises. Read the WHOLE day "
        "before writing each reason. If the day is mostly holding, say "
        "'consolidation'. If only the main lift bumps, say it leads the day. "
        "Reference goal (cut/recomp/build) where relevant. Generic fluff like "
        "'great for shoulders' is banned. Regression outside deload = "
        "'REGRESSION FLAG: ...'.\n\n"
        "Output: ONE JSON object mapping `<day>:<exercise_order>:<exercise_name>` "
        "to {\"weight\": <num|null>, \"why\": \"<one sentence>\"}. JSON only.\n\n"
        "Example:\n"
        '{\n'
        '  "0:0:Barbell Back Squat": {"weight": 150, "why": "Main lift leads Monday — +5 lb push under the cut as accessories hold."},\n'
        '  "0:1:Romanian Deadlift": {"weight": 140, "why": "Hinge volume at RPE 7; protects hamstring mass during the deficit."},\n'
        '  "0:2:Box Jump": {"weight": 0, "why": "CNS primer — explosive opener for heavy lower work."}\n'
        '}'
    )

    user_prompt = (
        f"ATHLETE CONTEXT:\n"
        f"- Goal: {goal_type}, currently {current_wt} lb, target {target_wt} lb, "
        f"{weeks_rem} weeks remaining\n"
        f"- Phase: {phase}{' (DELOAD)' if deload else ''}\n"
        f"- Week being prescribed: {week}\n\n"
        f"WEEK {week} TEMPLATE (sets x reps fixed; you set the weights):\n"
        f"{template_block}\n\n"
        f"RECENT SETLOG (top sets across last 4 weeks):\n{history_block}\n\n"
        "Prescribe the loads. JSON only."
    )

    try:
        client = _anthropic_client()
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=3000,
            system=system,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = "".join(
            b.text for b in resp.content if getattr(b, "type", None) == "text"
        ).strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        parsed = json.loads(text)
    except Exception as e:
        log.warning("generate_week_prescriptions failed: %s", e)
        return {}

    # New schema: value is {"weight": <num>, "why": "<sentence>"}
    # Legacy schema (fallback): value is just <num>
    out: dict[tuple[int, str, int], dict] = {}
    for k, v in parsed.items():
        parts = k.split(":", 2)
        if len(parts) != 3:
            continue
        try:
            day_idx = int(parts[0])
            order = int(parts[1])
            ex_name = parts[2].strip()
        except ValueError:
            continue
        weight = None
        why = None
        if isinstance(v, dict):
            weight = v.get("weight")
            why = v.get("why") or None
        elif v is not None:
            weight = v
        try:
            weight = float(weight) if weight is not None else None
        except (ValueError, TypeError):
            weight = None
        if weight is not None and weight < 0:
            weight = None
        if weight is None and not why:
            continue
        out[(day_idx, ex_name, order)] = {"weight": weight, "why": why}
    return out
