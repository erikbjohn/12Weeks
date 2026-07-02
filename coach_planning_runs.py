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
    """Last week's runs so the coach anchors on what came before and never
    proposes a regression. Prefers the stored PRESCRIPTION; if that week was
    template-driven and never persisted (early weeks, or a gap like a missing
    week 9), falls back to the phase TEMPLATE for that week. The coach must
    ALWAYS have a concrete prior anchor — an empty block is what made it
    confabulate 'no prior prescription, so this is the baseline week' for an
    athlete 10 weeks into the program."""
    if week <= 1:
        return ("(week 1 — no prior week to compare; anchor on the template and "
                "recent run log, which still exist)")
    prev = week - 1
    try:
        from models import WeeklyRunPlan
        rows = WeeklyRunPlan.query.filter_by(
            user_id=user_id, week=prev).order_by(WeeklyRunPlan.day_idx).all()
    except Exception:
        rows = []
    if rows:
        lines = []
        for r in rows:
            dn = _DAY_NAMES[r.day_idx] if 0 <= r.day_idx < 7 else "?"
            lines.append(f"  day={r.day_idx} ({dn}): {r.run_type} — {r.duration} — {r.label}")
        return "\n".join(lines)
    # No stored prescription for last week — use the template for that week so
    # the coach still has a real anchor instead of "nothing".
    try:
        from workout_data import get_workouts
        tdays = get_workouts(prev)
        lines = []
        for di, day in enumerate(tdays or []):
            run = (day or {}).get("run") or {}
            if run.get("type"):
                dn = _DAY_NAMES[di] if 0 <= di < 7 else "?"
                lines.append(
                    f"  day={di} ({dn}): {run.get('type')} — "
                    f"{run.get('time') or run.get('duration') or '?'} — "
                    f"{run.get('label') or 'Run'}  [from template; not separately stored]")
        if lines:
            return ("(last week was template-driven — not separately stored; "
                    "the template for week %d was:)\n" % prev) + "\n".join(lines)
    except Exception:
        pass
    return ("(no stored prescription for last week, but this is week %d of the "
            "program — NOT a baseline/first week; anchor on the template and "
            "recent run log)" % week)


_BASELINE_CONFAB_RE = None


def _strip_baseline_confabulation(out: dict, week: int) -> dict:
    """Neutralize any 'this is the baseline/first/intro week' or 'no prior
    prescription/history' claim in a run's user-visible detail when the athlete
    is past week 1. These are confabulations (the athlete is mid-program) and
    the prompt rule against them is not 100% reliable. We remove the offending
    sentence rather than rewrite it, so we never invent a replacement reason.
    """
    if week <= 1:
        return out
    import re
    global _BASELINE_CONFAB_RE
    if _BASELINE_CONFAB_RE is None:
        # Match a whole sentence/clause that asserts baseline/first-week / no-history.
        _BASELINE_CONFAB_RE = re.compile(
            r"(?:^|(?<=[.;—\-]))\s*[^.;]*?\b("
            r"baseline week|baseline session|first week|starting week|intro(?:ductory)? week|"
            r"no (?:prior|previous) (?:prescription|history|data|runs?|week)|"
            r"starting from scratch|no history (?:to|exists)|"
            r"treat(?:ed|ing)? (?:this )?as (?:the )?baseline"
            r")\b[^.;]*[.;]?",
            re.IGNORECASE,
        )
    for di, v in out.items():
        detail = (v or {}).get("detail") or ""
        if not detail:
            continue
        cleaned = _BASELINE_CONFAB_RE.sub("", detail)
        # Tidy leftover separators/whitespace from the excision.
        cleaned = re.sub(r"\s*—\s*—\s*", " — ", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" —-;.").strip()
        if cleaned != detail:
            v["detail"] = cleaned
            log.warning("stripped baseline-confabulation from run detail (week %d, day %d)", week, di)
    return out


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


def _strip_total_math(reason):
    """Drop any sentence in a run reason that restates the duration or shows
    arithmetic (a 'Total = 12 + … = 47 min', a 'min total (10+20+6+8)', or a
    weekly-mileage sum). The headline duration and the structure already display
    every number; the coach restating its own math only creates a value that can
    contradict the computed headline (it does, after recovery normalization)."""
    if not reason:
        return reason
    import re
    bad = re.compile(
        r"\bTotals?\s*[:=]"          # "Total ="
        r"|\bmin(?:ute)?s?\s+total\b"  # "44 min total"
        r"|\d+\s*\+\s*\d+"            # any explicit sum "10 + 20"
        r"|≈"                          # weekly mileage estimate "≈ 37.9 mi"
        r"|min\s*/\s*\d",            # "341 min / 9"
        re.I)
    sents = re.split(r"(?<=[.;])\s+", reason)
    kept = [s for s in sents if s.strip() and not bad.search(s)]
    out = " ".join(kept).strip(" .;,—-").strip()
    return out or reason


def _normalize_interval_recovery(segments):
    """Default a recovery's MISSING rep count to its work segment's reps.

    RESPECTS an explicit recovery rep count: the system prompt itself teaches
    work reps=4 / recovery reps=3 ("a real 37-min VO2 session — the parts and
    the total can never disagree"), i.e. recoveries BETWEEN intervals with none
    after the last rep. Force-overwriting recovery reps to equal work reps
    silently inflated every such session's stored duration and Garmin workout
    beyond what the coach prescribed (37 → 40 min). The detail renderer
    (_segments_to_detail) states the recovery count honestly when it differs
    from the work count, so structure and headline still always agree — the
    total is ALWAYS the sum of the segments as prescribed."""
    segs = [dict(s) for s in (segments or [])]
    for i, s in enumerate(segs):
        if (s.get("kind") or "").lower() == "work":
            n = int(s.get("reps") or 1)
            if i + 1 < len(segs) and (segs[i + 1].get("kind") or "").lower() == "recovery":
                if segs[i + 1].get("reps") in (None, ""):
                    segs[i + 1]["reps"] = n  # unspecified → one recovery per rep
    return segs


def _segments_to_detail(segments) -> str:
    """Human-readable structure built from the coach's own segments, so the
    detail always matches the computed duration. A work segment is PAIRED with
    the recovery that follows it and read as intervals ("5×3 min hard / 2 min
    easy"), not two separate blocks ("5×3 min work; 5×2 min recovery") which
    read as 'do all the work, then all the recovery'."""
    segs = list(segments or [])
    parts = []
    i = 0
    while i < len(segs):
        s = segs[i] or {}
        kind = (s.get("kind") or "segment").lower()
        mins = s.get("minutes")
        reps = s.get("reps")
        hr = s.get("hr")
        note = s.get("note")
        hr_txt = f" @ HR {hr}" if hr else ""
        if kind == "work":
            n = reps if reps and int(reps) > 1 else 1
            seg = f"{n}×{mins} min hard{hr_txt}"
            nxt = segs[i + 1] if i + 1 < len(segs) else None
            if nxt and (nxt.get("kind") or "").lower() == "recovery":
                # State the recovery count HONESTLY when it differs from the
                # work count — "/ X min easy" alone reads as one easy per rep,
                # which lied about sessions prescribed with n-1 recoveries
                # (recovery between intervals, none after the last).
                r_reps = int(nxt.get("reps") or 1)
                if r_reps == n:
                    seg += f" / {nxt.get('minutes')} min easy"
                elif r_reps == n - 1:
                    seg += f" / {nxt.get('minutes')} min easy between reps"
                else:
                    seg += f" / {r_reps}×{nxt.get('minutes')} min easy"
                i += 1  # consume the recovery — it's described in this interval
            if note:
                seg += f" ({note})"
            parts.append(seg)
        else:
            seg = (f"{reps}×{mins} min {kind}" if reps and int(reps) > 1
                   else f"{mins} min {kind}")
            extra = " ".join(x for x in [hr_txt.strip(), note or ""] if x).strip()
            parts.append(seg + (f" ({extra})" if extra else ""))
        i += 1
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
            # Void any coach-supplied segments: they were built for the shorter
            # duration and now disagree with the stored duration.  garmin_sync
            # validates segments_total vs duration and would push the wrong
            # workout; None forces it to fall back to simple timed (honest).
            plan["segments"] = None
            log.info("run floor: week %s day %s raised %s->%s (segments voided)",
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
        "NO 'BASELINE WEEK' CONFABULATION: the athlete is mid-program (the exact "
        "week is given below). You may NEVER call this a 'baseline', 'first', "
        "'intro', or 'starting' week, never say 'no prior prescription/history', "
        "and never imply you're starting from scratch. If last week wasn't stored "
        "as a separate prescription, a template and a run log still exist — anchor "
        "on those. Treating a mid-program week as a fresh start is a hard fail.\n\n"
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
        "4. EVERY day has a run — the athlete runs ALL 7 days, Monday included "
        "   (easy/recovery on heavy-lower days). No day may be left runless. At "
        "   most ONE VO2 day per week. The long run is the week's longest.\n"
        "5. Single values only — never a range.\n"
        "6. The `reason` is ONE short, QUALITATIVE sentence. Do NOT state the total "
        "   duration, do NOT show arithmetic or sums ('Total = 12 + … = 47 min', "
        "   '44 min total (10+20+6+8)', weekly-mileage math), and do NOT restate "
        "   the segment minutes — the SYSTEM computes and displays every number, "
        "   and your restating it only creates a value that can contradict the "
        "   headline. Explain WHY (the progression, what the log supports), not "
        "   the math.\n\n"
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
        # Even on total LLM/parse failure, never leave the week runless — the
        # 7-day floor still applies (Erik runs every day). Returning {} here would
        # bypass _ensure_seven_day_runs entirely.
        log.warning("generate_week_runs failed: %s — applying 7-day floor", e)
        # Floor the fills against last week too — the failure path must not
        # ship a same-day, same-type regression either.
        return _apply_run_regression_floor(
            _ensure_seven_day_runs({}, week), user_id, week)

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
            # Pair each work block with its recovery as N equal rounds so the
            # rendered structure and the headline duration describe the SAME
            # rounds (kills the "5×3 hard / 2 easy" headline=41 but structure=43
            # split). Then duration is the honest SUM of those segments.
            segments = _normalize_interval_recovery(segments)
            duration = f"{_segments_total_min(segments)} min"
            detail = _segments_to_detail(segments)
        else:
            # Back-compat if the coach gives a freeform duration/detail.
            duration = v.get("duration") or v.get("time") or "30 min"
            detail = v.get("detail") or ""
            segments = None  # freeform path — no structure to persist
        reason = _strip_total_math((v.get("reason") or "").strip())
        if reason:
            detail = f"{detail} — {reason}" if detail else reason
        out[day_idx] = {
            "type": v.get("type") or "z2",
            "label": v.get("label") or "Run",
            "duration": duration,
            "detail": detail,
            "segments": segments,
        }
    # Hard backstop: Erik runs ALL 7 days — no day may be runless (the generator
    # historically left Monday blank). Fill any gap with an easy Z2 recovery run.
    # MUST run BEFORE the regression floor so a backfilled static 28-min Z2 on a
    # day the coach omitted is itself floored against last week's same-day Z2
    # (fill-after-floor shipped a 40→28 min same-type regression unchecked).
    out = _ensure_seven_day_runs(out, week)
    # Hard backstop: even with the prompt + prior-prescription context, the LLM
    # can still slip a regression through. This guarantees it never ships.
    out = _apply_run_regression_floor(out, user_id, week)
    # Hard backstop: never let a "baseline / first / no prior history" claim
    # reach an athlete who is mid-program. Prompt adherence is unreliable.
    out = _strip_baseline_confabulation(out, week)
    return out


def _ensure_seven_day_runs(out: dict, week: int) -> dict:
    """7-day run floor. Every day_idx 0-6 must carry a run — least of all Monday
    (day 0, the heavy-lower day), which the generator has left blank before.
    A missing day gets an easy Zone 2 recovery run; deload weeks run shorter."""
    deload = week in (4, 8, 12)
    mins = 22 if deload else 28
    for d in range(7):
        if not out.get(d):
            out[d] = {
                "type": "z2",
                "label": "Z2 Easy",
                "duration": f"{mins} min",
                "detail": "Easy aerobic recovery — every day gets a run.",
                "segments": [{"kind": "steady", "minutes": mins, "hr": "≤132"}],
            }
    return out
