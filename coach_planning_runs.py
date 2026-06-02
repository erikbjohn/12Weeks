"""Running coach: per-day run prescriptions for the planning week.

Replaces _generate_run_plan's deterministic progression with an agent
call that sees actual RunLog history (distance, HR, pace, perceived effort)
and the athlete's training goal. Returns per-day run plans.

Engine remains as fallback when LLM fails.
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


def _build_run_history_block(user_id: int, current_week: int,
                              lookback_weeks: int = 4) -> str:
    """Recent RunLog summary — distance, duration, HR, type. Coach uses this
    to set pace/distance/HR for the upcoming week."""
    from models import RunLog
    from datetime import timedelta
    from coach_assembler import _user_today
    cutoff = _user_today() - timedelta(weeks=lookback_weeks)
    runs = (RunLog.query
            .filter(RunLog.user_id == user_id)
            .filter(RunLog.log_date >= cutoff)
            .order_by(RunLog.log_date.desc())
            .limit(20).all())
    if not runs:
        return "(no recent runs)"
    lines = []
    for r in runs:
        bits = [str(r.log_date)]
        if r.distance_miles: bits.append(f"{r.distance_miles}mi")
        if getattr(r, 'duration_min', None): bits.append(f"{r.duration_min}min")
        if r.avg_hr: bits.append(f"HR={r.avg_hr}")
        if getattr(r, 'run_type', None): bits.append(r.run_type)
        if getattr(r, 'elevation_ft', None): bits.append(f"{r.elevation_ft}ft")
        lines.append("  " + " | ".join(bits))
    return "\n".join(lines)


def _prev_prescription_block(user_id: int, week: int) -> str:
    """Last week's PRESCRIBED runs (not logged) so the coach anchors on the
    plan it set and never proposes a regression against it. The run coach was
    blind to this — it only saw RunLog — which is how a 40-min run drifted to
    38."""
    if week <= 1:
        return "(no prior week)"
    try:
        from models import WeeklyRunPlan
        rows = WeeklyRunPlan.query.filter_by(
            user_id=user_id, week=week - 1).order_by(WeeklyRunPlan.day_idx).all()
    except Exception:
        return "(unavailable)"
    if not rows:
        return "(no runs prescribed last week)"
    lines = []
    for r in rows:
        dn = _DAY_NAMES[r.day_idx] if 0 <= r.day_idx < 7 else "?"
        lines.append(f"  day={r.day_idx} ({dn}): {r.run_type} — {r.duration} — {r.label}")
    return "\n".join(lines)


def _parse_run_magnitude(s):
    """Return (value, unit) for a duration string like '38 min' or '9 mi',
    else (None, None). Used to compare run prescriptions week-over-week."""
    import re
    if not s:
        return (None, None)
    s = str(s)
    m = re.search(r"(\d+(?:\.\d+)?)\s*mi\b", s)
    if m:
        return (float(m.group(1)), "mi")
    m = re.search(r"(\d+(?:\.\d+)?)\s*min", s)
    if m:
        return (float(m.group(1)), "min")
    return (None, None)


def _apply_run_regression_floor(out: dict, user_id: int, week: int) -> dict:
    """Code-enforced anti-regression rail (mirrors the lift 'floor at top set').

    A run's prescribed duration may NOT drop below last week's same-day,
    same-type run unless this is a deload week. The system prompt asks for this
    (rule 1) but prompt adherence is unreliable — this is the hard guarantee.
    Only floors when units AND run type match, so it never wrongly compares a
    VO2 day against a Z2 day or minutes against miles.
    """
    if week in (4, 8, 12):  # deload weeks may legitimately reduce volume
        return out
    try:
        from models import WeeklyRunPlan
        prev = {r.day_idx: r for r in WeeklyRunPlan.query.filter_by(
            user_id=user_id, week=week - 1).all()}
    except Exception:
        return out
    for day_idx, plan in out.items():
        prev_run = prev.get(day_idx)
        if not prev_run:
            continue
        if (plan.get("type") or "").lower() != (prev_run.run_type or "").lower():
            continue  # different run type — not comparable
        cur_v, cur_u = _parse_run_magnitude(plan.get("duration"))
        prev_v, prev_u = _parse_run_magnitude(prev_run.duration)
        if cur_v is None or prev_v is None or cur_u != prev_u:
            continue
        if cur_v < prev_v:
            plan["duration"] = prev_run.duration
            plan["detail"] = (plan.get("detail") or "").rstrip(". ") + \
                f". [held at last week's {prev_run.duration} — no regression outside deload]"
            log.info("run floor: week %s day %s raised %s->%s",
                     week, day_idx, f"{cur_v:g}{cur_u}", prev_run.duration)
    return out


def generate_week_runs(
    user_id: int,
    week: int,
    template_runs: list[dict],
    user_context: dict,
) -> dict[int, dict]:
    """Generate per-day run prescriptions via the running coach.

    template_runs: list of {day, type, label, duration} from the phase
      template — defines run shape. Coach picks duration / distance /
      HR target based on actual history.
    user_context: {phase, deload, goal_type, target_weekly_miles,
                   current_weight, target_weight}

    Returns: {day_idx: {type, label, duration, detail}} — missing days
    indicate rest/no run.
    """
    if not template_runs:
        return {}

    history_block = _build_run_history_block(user_id, week)
    prev_block = _prev_prescription_block(user_id, week)
    template_lines = []
    for r in template_runs:
        template_lines.append(
            f"  day={r['day']} ({_DAY_NAMES[r['day']] if 0 <= r['day'] < 7 else '?'}): "
            f"type={r.get('type', '?')}, label={r.get('label', '?')}, "
            f"duration={r.get('duration') or r.get('time') or '?'}"
        )
    template_block = "\n".join(template_lines) if template_lines else "(no runs in template)"

    phase = user_context.get("phase", "?")
    deload = user_context.get("deload", False)
    goal_type = user_context.get("goal_type", "recomp")
    target_miles = user_context.get("target_weekly_miles")
    current_wt = user_context.get("current_weight")
    target_wt = user_context.get("target_weight")

    system = (
        "You are a running coach prescribing the weekly run plan. The phase "
        "template defines the TYPE and SHAPE (Z2, VO2, tempo, long run, etc.); "
        "you pick duration/distance/HR target per day based on the athlete's "
        "actual recent runs.\n\n"
        "ABSOLUTE RULES:\n"
        "0. COMMIT TO A SINGLE NUMBER. Every duration is exactly one value — "
        "   \"75 min\", never a range like \"60-90 min\" or \"45-60 min\". A "
        "   range is a hard fail; decide the number. Same for distance: one "
        "   value, e.g. \"9 mi\".\n"
        "0b. PRESCRIBE EVERY DAY in the template run structure below. Omitting "
        "   a day leaves the athlete with no run for it — a hard fail.\n"
        "1. NEVER prescribe a run below LAST WEEK'S PRESCRIBED run for the same "
        "   day/type (see 'LAST WEEK'S PRESCRIBED RUNS' below) — MATCH OR EXCEED "
        "   it — unless this is a deload week (4/8/12) or an explicit taper. A "
        "   regression vs last week's plan is a HARD FAIL. Do NOT use the logged "
        "   runs to justify a drop: a logged run may be shorter than prescribed, "
        "   but the PRESCRIPTION is the floor. Last week's 40-min VO2 → this week "
        "   is 40+ min, never 38.\n"
        "2. HIT THE TARGET WEEKLY MILES. The target is a FLOOR, not a ceiling. "
        "   Sum up your prescribed durations × ~9 min/mi pace; if the total "
        "   is below the target, INCREASE durations until it's at or above. "
        "   Undershooting the target is a hard fail. Show the math in your "
        "   reasoning even if you don't output it.\n"
        "3. Z2 runs should hold HR ≤ Z2 ceiling (typically 130-140 for the "
        "   athlete). State the HR ceiling in the detail.\n"
        "4. VO2 intervals: name reps × duration (e.g. 4×4 min at threshold). "
        "   At MOST one VO2 day per week — don't double up.\n"
        "5. Long run: distance > all other runs in the week. For build phase "
        "   targeting 40+ mi/wk, pick ONE long-run duration around 90-120 min "
        "   (commit to a single number, e.g. 100 min; shorter only on deload).\n"
        "6. Deload weeks: ~70% of prior week's volume per run.\n"
        "7. Build phase: progress long run by 0.5-1 mi/week if streak is clean.\n"
        "8. Strict Z2 days: HR ceiling explicit (e.g. 'HR ≤ 132').\n"
        "9. SATURDAY MUST HAVE A RUN if the athlete trains 6 days. Don't skip it.\n\n"
        "Output: JSON mapping `<day_idx>` to "
        '{"type": "<z2|vo2|tempo|long|streak|hill>", '
        '"label": "<short label>", "duration": "<X min or X mi>", '
        '"detail": "<HR target + notes>"}. No prose. JSON only.\n\n'
        "Example:\n"
        '{\n'
        '  "1": {"type": "vo2", "label": "VO2 4×4", "duration": "35 min", '
        '"detail": "4×4 min at HR 165-175, 3 min jog recovery"},\n'
        '  "3": {"type": "z2", "label": "Z2 base", "duration": "60 min", '
        '"detail": "HR ≤ 132. Easy pace."},\n'
        '  "6": {"type": "long", "label": "Long fasted", "duration": "90 min", '
        '"detail": "~9 mi @ HR ≤ 140. Fasted state."}\n'
        '}'
    )

    user_prompt = (
        f"ATHLETE CONTEXT:\n"
        f"- Goal: {goal_type}, currently {current_wt} lb → target {target_wt} lb\n"
        f"- Phase: {phase}{' (DELOAD)' if deload else ''}\n"
        f"- Week being prescribed: {week}\n"
        f"- Target weekly miles: {target_miles or 'unspecified'}\n\n"
        f"TEMPLATE RUN STRUCTURE (you pick load):\n{template_block}\n\n"
        f"LAST WEEK'S PRESCRIBED RUNS (this week MUST match or exceed these for "
        f"the same day/type — never regress outside deload):\n{prev_block}\n\n"
        f"RECENT RUN LOG (last 4 weeks — what they actually ran; do NOT use this "
        f"to justify dropping below the prescription above):\n{history_block}\n\n"
        "Prescribe the runs. JSON only."
    )

    try:
        client = _anthropic_client()
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
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
        log.warning("generate_week_runs failed: %s", e)
        return {}

    out: dict[int, dict] = {}
    for k, v in parsed.items():
        try:
            day_idx = int(k)
        except ValueError:
            continue
        if not isinstance(v, dict):
            continue
        out[day_idx] = {
            "type": v.get("type") or "z2",
            "label": v.get("label") or "Run",
            "duration": v.get("duration") or v.get("time") or "30 min",
            "detail": v.get("detail") or "",
        }
    # Hard backstop: even with the prompt + prior-prescription context, the LLM
    # can still slip a regression through. This guarantees it never ships.
    out = _apply_run_regression_floor(out, user_id, week)
    return out
