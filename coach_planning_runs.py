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
        if r.avg_hr: bits.append(f"wholeRunAvgHR={r.avg_hr}")
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


def _segments_total_min(segments) -> int:
    """Sum the coach's OWN run segments into honest total minutes. Each segment
    is {kind, minutes, reps?}; total = sum(minutes × reps). The coach chooses
    every value — code only adds them, so the headline duration can never
    contradict the structure the coach described (the '38 min' for a 34-min
    session bug)."""
    total = 0.0
    for s in segments or []:
        try:
            mins = float(s.get("minutes") or 0)
            reps = int(s.get("reps") or 1)
            total += mins * max(1, reps)
        except (TypeError, ValueError):
            continue
    return int(round(total))


def _segments_to_detail(segments) -> str:
    """Human-readable structure built from the coach's own segments, so the
    detail always matches the computed duration."""
    parts = []
    for s in segments or []:
        kind = (s.get("kind") or "segment").lower()
        mins = s.get("minutes")
        reps = s.get("reps")
        hr = s.get("hr")
        note = s.get("note")
        seg = (f"{reps}×{mins} min {kind}" if reps and int(reps) > 1
               else f"{mins} min {kind}")
        extra = " ".join(x for x in [f"@ HR {hr}" if hr else "", note or ""] if x).strip()
        parts.append(seg + (f" ({extra})" if extra else ""))
    return "; ".join(parts)


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
        "You are a running coach designing the athlete's weekly run plan from "
        "their actual history and how they're performing. You decide EVERYTHING "
        "— interval count, work duration, recovery, warm-up, cool-down, "
        "intensity, and week-over-week progression. Nothing is fixed; you own "
        "the plan AND a real reason for every choice.\n\n"
        "HOW YOU OUTPUT A RUN — as SEGMENTS, never a guessed total:\n"
        "Describe each run as an ordered list of segments. Each segment is "
        '{"kind": "warmup|work|recovery|cooldown|steady", "minutes": <number>, '
        '"reps": <number, default 1>, "hr": "<target/ceiling, optional>", '
        '"note": "<optional>"}. The total duration is the SUM of (minutes × '
        "reps) — the SYSTEM computes it, so it always matches what you actually "
        "prescribed. Do NOT output a separate total number; just get the "
        "segments right. (warmup 10 + work 3min×4 + recovery 3min×3 + cooldown 6 "
        "= a real 37-min VO2 session — the parts and the total can never "
        "disagree.)\n\n"
        "DATA YOU HAVE — and ONLY this; never reference anything else:\n"
        "  date · distance (mi) · total duration (min) · elevation (ft) · notes\n"
        "  WHOLE-RUN AVERAGE HR: a single mean over the ENTIRE run including "
        "  warm-up, recoveries, and cool-down. It does NOT tell you interval "
        "  intensity, per-rep HR, or HR recovery.\n"
        "HARD ANTI-HALLUCINATION RULE: every reason must cite ONLY the data "
        "above. You may NOT claim or imply HR recovery, per-interval or per-rep "
        "HR, splits, work-interval HR zones, lactate, or 'how they executed the "
        "intervals' — THAT DATA DOES NOT EXIST. Inventing a metric to justify a "
        "choice is a hard fail. A whole-run average tells you overall effort and "
        "nothing finer; say only what it actually supports.\n\n"
        "PROGRAMMING RULES:\n"
        "1. Give a `reason` for EVERY run, and explicitly justify any change vs "
        "   LAST WEEK'S PRESCRIPTION (shown below) from the real data. A change "
        "   with no data-grounded reason is a hard fail.\n"
        "2. Do NOT regress below last week's same-type run (shorter total, fewer "
        "   reps, less work) unless it is a deload week (4/8/12) or you state an "
        "   explicit, data-grounded taper. A short LOGGED run does NOT justify "
        "   cutting the PRESCRIPTION.\n"
        "3. Hit the target weekly miles (a FLOOR): sum durations × ~9 min/mi; if "
        "   under target, add volume.\n"
        "4. At most ONE VO2 day per week. Saturday must have a run if they train "
        "   6 days. The long run is the week's longest.\n"
        "5. Single values only — never a range.\n\n"
        "Output JSON only: map `<day_idx>` to "
        '{"type": "<z2|vo2|tempo|long|streak|hill>", "label": "<short label>", '
        '"segments": [ ... ], "reason": "<data-grounded why, incl. any change>"}.\n'
        "Example:\n"
        '{\n'
        '  "1": {"type":"vo2","label":"VO2 4×3","segments":['
        '{"kind":"warmup","minutes":10},'
        '{"kind":"work","minutes":3,"reps":4,"hr":"165-175"},'
        '{"kind":"recovery","minutes":3,"reps":3},'
        '{"kind":"cooldown","minutes":6}],'
        '"reason":"Held 4×3 work from last week; added 2 min of warm-up. Last '
        'week\'s whole-run avg HR was 148, i.e. easy overall, so total volume is '
        'safe to nudge up — kept the work/recovery the same since I can\'t see '
        'interval HR."},\n'
        '  "3": {"type":"z2","label":"Z2 base","segments":['
        '{"kind":"steady","minutes":60,"hr":"≤132"}],'
        '"reason":"Matches last week\'s 60-min Z2; aerobic base held."}\n'
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
        segments = v.get("segments")
        if isinstance(segments, list) and segments:
            # Duration is the SUM of the coach's own segments — never an invented
            # headline number that contradicts the structure.
            duration = f"{_segments_total_min(segments)} min"
            detail = _segments_to_detail(segments)
        else:
            # Back-compat if the coach gives a freeform duration/detail.
            duration = v.get("duration") or v.get("time") or "30 min"
            detail = v.get("detail") or ""
        reason = (v.get("reason") or "").strip()
        if reason:
            detail = f"{detail} — {reason}" if detail else reason
        out[day_idx] = {
            "type": v.get("type") or "z2",
            "label": v.get("label") or "Run",
            "duration": duration,
            "detail": detail,
        }
    # Hard backstop: even with the prompt + prior-prescription context, the LLM
    # can still slip a regression through. This guarantees it never ships.
    out = _apply_run_regression_floor(out, user_id, week)
    return out
