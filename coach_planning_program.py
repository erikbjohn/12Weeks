"""Option B — the strength coach designs the WHOLE weekly program.

Unlike coach_planning_prescribe (which only picked LOADS on a fixed template),
this coach selects the exercises, sets, reps, AND loads each week from the
athlete's real history, equipment, injuries, goal, and phase intent. There is
no static exercise template. Output is HARD-validated against the exercise
catalog + the athlete's equipment so the LLM can never prescribe a movement
they can't do or that doesn't exist.

Returns {day_idx: [{exercise, sets, reps, weight, why}]}. Empty dict on failure
(coach-or-nothing — the caller surfaces the failure, never falls back to a
static template).
"""
from __future__ import annotations
import os
import re
import json
import logging
from collections import defaultdict
from datetime import date

# Equipment / grip qualifiers that describe the SAME movement (so a coach name
# like "Barbell Hip Thrust" maps to logged "Hip Thrust"). The core movement
# words (hip thrust, deadlift, row, curl, ...) are preserved.
_EQUIP_MODIFIERS = re.compile(
    r'\b(barbell|bb|dumbbell|dumbell|db|cable|machine|smith|ez[\s-]?bar|'
    r'wide[\s-]?grip|close[\s-]?grip|narrow[\s-]?grip|neutral[\s-]?grip|'
    r'reverse[\s-]?grip|wide|close|narrow)\b', re.I)


# Every prescribed exercise carries at least this many working sets — always,
# deload weeks included (Erik, 2026-08-24). Deload = lighter loads / fewer
# movements, never 1-2 set stubs.
MIN_SETS = 3


def _movement_key(name: str) -> str:
    """Canonical movement key: alias-resolve then strip equipment/grip
    qualifiers and normalize. 'Barbell Hip Thrust' == 'Hip Thrust',
    'Wide-Grip Lat Pulldown' == 'Lat Pulldown', 'Single-Arm DB Row' ==
    'Single-Arm DB Row' — but 'Conventional Deadlift' != 'Romanian Deadlift'.
    """
    try:
        from workout_data import resolve_name
        n = resolve_name(name or "")
    except Exception:
        n = name or ""
    n = _EQUIP_MODIFIERS.sub(" ", n)
    n = re.sub(r"[-]", " ", n)
    n = re.sub(r"\s+", " ", n).strip().lower()
    return n

log = logging.getLogger(__name__)

_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday",
              "Friday", "Saturday", "Sunday"]


def _anthropic_client():
    import anthropic
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=3)


def validate_program(parsed, catalog, available_equipment):
    """Drop anything the athlete can't do. Pure + unit-tested.

    parsed: {day(str|int): [{exercise, sets, reps, weight, rest, why}]}
    `rest` is REQUIRED and must be a single value (no range); items lacking it or
    giving a range are dropped (coach-or-nothing — no default is substituted).
    catalog: {exercise_name: {equipment: [...], muscle_group: ...}}
    available_equipment: iterable of equipment keys the athlete has.
    Returns (clean: {int_day: [items]}, dropped: [reason strings]).
    """
    available = set(available_equipment or [])
    clean: dict[int, list] = {}
    dropped: list[str] = []
    for k, items in (parsed or {}).items():
        try:
            day = int(k)
        except (TypeError, ValueError):
            dropped.append(f"bad day key {k!r}")
            continue
        if not isinstance(items, list):
            continue
        kept = []
        for it in items:
            if not isinstance(it, dict):
                continue
            name = (it.get("exercise") or "").strip()
            if not name:
                continue
            info = catalog.get(name)
            if info is None:
                dropped.append(f"day{day}: unknown exercise {name!r}")
                continue
            need = set(info.get("equipment") or [])
            if not need.issubset(available):
                dropped.append(f"day{day}: {name} needs {sorted(need - available)}")
                continue
            reps = str(it.get("reps") or "").strip()
            if reps in ("", "0"):
                # rest-day / non-prescription placeholder (e.g. "Burpees 3x0")
                continue
            try:
                sets = int(it.get("sets") or 3)
            except (TypeError, ValueError):
                sets = 3
            if sets <= 0:
                continue
            sets = max(MIN_SETS, min(6, sets))
            weight = it.get("weight")
            try:
                weight = float(weight) if weight is not None else None
            except (TypeError, ValueError):
                weight = None
            # REST: the coach must commit ONE value — never a range, never
            # omitted. No hardcoded default is substituted (coach-or-nothing);
            # a rest-less or range item is dropped and surfaces as unplanned.
            rest = str(it.get("rest") or "").strip()
            if not rest:
                dropped.append(f"day{day}: {name} missing rest")
                continue
            if any(sep in rest for sep in ("-", "–", "/", " to ")):
                dropped.append(f"day{day}: {name} rest is a range {rest!r}")
                continue
            kept.append({"exercise": name, "sets": sets, "reps": reps,
                         "weight": weight, "rest": rest,
                         "why": (it.get("why") or "")})
        if kept:
            clean[day] = kept
    return clean, dropped


def _layoff_days(user_id: int):
    """Days since the athlete's most recent COMPLETED set (any lift, any block).
    None when there is no dated lifting history at all. Drives the
    return-from-layoff rail: history-anchored loads are unsafe after weeks off."""
    from models import SetLog
    row = (SetLog.query
           .filter(SetLog.user_id == user_id,
                   SetLog.done.is_(True),
                   SetLog.logged_date.isnot(None))
           .order_by(SetLog.logged_date.desc())
           .first())
    if row is None:
        return None
    return (date.today() - row.logged_date).days


# Layoff thresholds (days) and load-cap fractions. >= LAYOFF_LONG is a full
# return-to-training protocol: 60% loads AND the weekly volume ceiling cut to
# 60%. >= LAYOFF_MODERATE is 75% loads only.
LAYOFF_MODERATE = 21
LAYOFF_LONG = 42
LAYOFF_CAP_FRAC = {LAYOFF_MODERATE: 0.75, LAYOFF_LONG: 0.60}


def enforce_safety(program, *, rest_day_idx, ceiling, history_exercises,
                   history_max_weight, history_top=None, new_move_frac=0.6,
                   max_jump_frac=0.20, prev_by_day=None, min_per_day=4,
                   deload=False, floor=0, layoff_days=None):
    """Deterministic safety rails the LLM can't be trusted to honor. Mutates a
    copy. Returns (program, actions[]).

    1. No lifting on the rest / long-run day.
    2. New (no-history) movements: flagged `new` and their load forced to a
       genuinely light start (<= new_move_frac of the athlete's max logged lift).
    2b. Existing movements: load can't LEAP — capped at the recent top set ×
       (1 + max_jump_frac), so a 97.5 -> 143 (+47%) jump is impossible.
    2c. Per-day volume FLOOR (non-deload): every lifting day carries
       >= min_per_day movements; if the coach under-prescribed, restore the
       movement(s) that day ran LAST week (honest backfill from prev_by_day, not
       a clone). This is the countervailing rail to the ceiling — without it a
       day that drops low re-anchors low on each re-derive and ratchets Phase-3
       volume DOWN (week 10 Tuesday 4->3 exercises = an unintended deload).
    3. Hard weekly working-set CEILING — trim accessories first, never the day's
       lead compound, until total <= ceiling.

    `rest` is carried through untouched on every item (a plain key on the copied
    dict) — the rails NEVER invent or overwrite the coach's committed rest.
    """
    actions = []
    history_top = history_top or {}
    out = {int(d): [dict(it) for it in items] for d, items in program.items()}

    # 1. rest day
    if rest_day_idx in out:
        out.pop(rest_day_idx)
        actions.append(f"Dropped lifting on rest day (day {rest_day_idx}) — long-run day.")

    # 2. new-movement load cap — match by canonical movement key so equipment/
    #    grip variants of a logged lift are NOT treated as new.
    hist_keys = {_movement_key(e) for e in (history_exercises or [])}
    cap = (history_max_weight or 0) * new_move_frac
    for items in out.values():
        for it in items:
            if _movement_key(it["exercise"]) not in hist_keys:
                it["new"] = True
                w = it.get("weight")
                if w and cap and w > cap:
                    neww = max(5, round(cap / 5) * 5)
                    actions.append(
                        f"Capped new movement {it['exercise']} {w:g}->{neww:g} lb (start light, ramp up).")
                    it["weight"] = neww
                    # Keep the rationale coherent with the adjusted load.
                    it["why"] = (f"New movement — starting light at {neww:g} lb, "
                                 f"ramp up fast as you log it.")

    # 2b. existing-movement jump cap — an already-logged lift can't leap more
    #     than max_jump_frac over its recent top set (blocks the 97.5 -> 143
    #     +47% nonsense). New movements are exempt (they ramp up by design).
    for items in out.values():
        for it in items:
            if it.get("new"):
                continue
            prev_top = history_top.get(_movement_key(it["exercise"]))
            w = it.get("weight")
            if prev_top and w and w > prev_top * (1 + max_jump_frac):
                capped = max(5, round(prev_top * (1 + max_jump_frac) / 5) * 5)
                actions.append(
                    f"Capped {it['exercise']} jump {w:g}->{capped:g} lb "
                    f"(recent top {prev_top:g}; progress is incremental).")
                it["weight"] = capped
                # Keep the why consistent with the capped load — don't leave it
                # narrating the un-capped number (the "@70 but why says 65" class).
                it["why"] = (f"{capped:g} lb — incremental step up from your recent "
                             f"top {prev_top:g} (held back from a {w:g} lb jump).")

    # 2d. RETURN-FROM-LAYOFF cap — after weeks away from the bar, history-
    #     anchored loads are an injury setup, not a plan. Cap EVERY logged
    #     movement at a fraction of its recent top (0.75 at >= 21 days off,
    #     0.60 at >= 42 days) and, for a long layoff, cut the weekly volume
    #     ceiling to 60% so the week reads as a return ramp, not a continuation.
    if layoff_days is not None and layoff_days >= LAYOFF_MODERATE:
        frac = (LAYOFF_CAP_FRAC[LAYOFF_LONG]
                if layoff_days >= LAYOFF_LONG else LAYOFF_CAP_FRAC[LAYOFF_MODERATE])
        wks_off = layoff_days // 7
        for items in out.values():
            for it in items:
                if it.get("new"):
                    continue  # new movements already start light (rail 2)
                prev_top = history_top.get(_movement_key(it["exercise"]))
                w = it.get("weight")
                if prev_top and w and w > prev_top * frac:
                    capped = max(5, round(prev_top * frac / 5) * 5)
                    actions.append(
                        f"Layoff cap: {it['exercise']} {w:g}->{capped:g} lb "
                        f"({wks_off} weeks since last logged set; return at "
                        f"{int(frac * 100)}% and ramp).")
                    it["weight"] = capped
                    it["why"] = (
                        f"{capped:g} lb — {wks_off} weeks off the bar, so we "
                        f"restart at ~{int(frac * 100)}% of your {prev_top:g} lb "
                        f"top and ramp back over 2-3 weeks.")
        if layoff_days >= LAYOFF_LONG:
            new_ceiling = max(min_per_day, int(ceiling * 0.6))
            if new_ceiling < ceiling:
                actions.append(
                    f"Layoff volume cut: weekly set ceiling {ceiling}->{new_ceiling} "
                    f"({wks_off} weeks off; volume rebuilds week over week).")
                ceiling = new_ceiling
            floor = 0  # the anti-taper floor must not fight the return ramp

    # 2c. per-day volume FLOOR (non-deload) — restore movements the day ran last
    #     week so the coach can't silently turn a training day into a deload.
    if not deload and prev_by_day:
        for d, items in out.items():
            if d == rest_day_idx or len(items) >= min_per_day:
                continue
            have = {_movement_key(it["exercise"]) for it in items}
            for pit in prev_by_day.get(d, []):
                if len(items) >= min_per_day:
                    break
                if _movement_key(pit["exercise"]) in have:
                    continue
                restored = dict(pit)
                restored["why"] = (
                    f"Restored {pit['exercise']} — you trained it on this day last "
                    f"week; Phase-3 volume holds, no regression.")
                items.append(restored)
                have.add(_movement_key(pit["exercise"]))
                actions.append(
                    f"Floored day {d} to {len(items)} exercises (coach "
                    f"under-prescribed; restored {pit['exercise']}).")

    # 2d. per-exercise set FLOOR — no exercise below MIN_SETS, deload weeks
    #     included. A 2-set exercise is not a prescription (Erik, 2026-08-24).
    for items in out.values():
        for it in items:
            if it["sets"] < MIN_SETS:
                actions.append(
                    f"Raised {it['exercise']} {it['sets']}->{MIN_SETS} sets (min sets rail).")
                it["sets"] = MIN_SETS

    # 3. volume ceiling — trim non-lead (accessory) sets first. An exercise
    #    already at MIN_SETS is never decremented into a stub: it is dropped
    #    whole instead (accessories before leads).
    def _total():
        return sum(it["sets"] for items in out.values() for it in items)

    def _trim_candidate(include_leads):
        # Prefer decrementing the fattest movement above the floor; if none,
        # drop the accessory (or lead, as a last resort) with the fewest sets.
        dec = None
        for d, items in out.items():
            for idx, it in enumerate(items):
                if idx == 0 and not include_leads:
                    continue  # protect the day's lead compound
                if it["sets"] > MIN_SETS and (dec is None or it["sets"] > dec[1]["sets"]):
                    dec = (d, it)
        if dec:
            return "dec", dec
        drop = None
        for d, items in out.items():
            for idx, it in enumerate(items):
                if idx == 0 and not include_leads:
                    continue
                if drop is None or it["sets"] < drop[1]["sets"]:
                    drop = (d, it)
        return ("drop", drop) if drop else (None, None)

    trimmed = False
    guard = 0
    while _total() > ceiling and guard < 1000:
        guard += 1
        kind, cand = _trim_candidate(include_leads=False)
        if cand is None:  # only leads remain — trim them as a last resort
            kind, cand = _trim_candidate(include_leads=True)
        if cand is None:
            break
        d, it = cand
        trimmed = True
        if kind == "dec":
            it["sets"] -= 1
        else:
            actions.append(
                f"Dropped {it['exercise']} (day {d}) whole rather than stub it below "
                f"{MIN_SETS} sets (ceiling).")
            out[d] = [x for x in out[d] if x is not it]
    if trimmed:
        actions.append(f"Trimmed volume to ceiling of {ceiling} working sets.")

    # 4. weekly volume FLOOR (non-deload) — the anti-taper rail. Total working
    #    sets may not fall below `floor` (max of 0.92*target and the last
    #    non-deload week's total, computed by the caller). Backfill sets onto
    #    EXISTING movements — accessories first, then leads — capped at 6 sets
    #    per exercise, and NEVER above the ceiling just enforced (the two rails
    #    can't fight). This is what makes the block CLIMB instead of bleeding out
    #    the way block 1 did (163 -> 48). The coach keeps full discretion over
    #    exercise selection and loads; it just can't let total volume collapse.
    if not deload and floor:
        floor = min(int(floor), ceiling)  # clamp — the floor can't break the ceiling
        backfilled = False
        guard = 0
        while _total() < floor and guard < 1000:
            guard += 1
            cand = None  # (rank, day, item) — accessories first, then fewest sets
            for d, items in out.items():
                for idx, it in enumerate(items):
                    if it["sets"] >= 6:
                        continue
                    rank = (0 if idx > 0 else 1, it["sets"])
                    if cand is None or rank < cand[0]:
                        cand = (rank, d, it)
            if cand is None:
                break  # every movement at the 6-set cap — can't reach floor
            _, d, it = cand
            it["sets"] += 1
            backfilled = True
        if backfilled:
            reached = _total()
            if reached >= floor:
                actions.append(
                    f"Backfilled volume up to floor of {floor} working sets (anti-taper).")
            else:
                # Honest: don't claim we hit the floor when every movement is at the
                # 6-set cap. Surfaces that the coach needs MORE movements, not sets.
                log.warning("volume floor %s unreachable — all movements at 6-set cap (got %s)",
                            floor, reached)
                actions.append(
                    f"Volume short of floor {floor} (reached {reached}) — movements capped at 6 sets.")

    out = {d: items for d, items in out.items() if items}
    return out, actions


def _history_block(user_id: int, current_week: int, lookback_weeks: int = 4) -> str:
    from models import SetLog
    rows = (SetLog.query
            .filter(SetLog.user_id == user_id)
            .filter(SetLog.weight > 0)
            .filter(SetLog.week >= max(1, current_week - lookback_weeks))
            .order_by(SetLog.exercise_name, SetLog.logged_date.desc())
            .all())
    if not rows:
        return "(no recent lifting history)"
    by_ex: dict[str, list] = defaultdict(list)
    for r in rows:
        by_ex[r.exercise_name].append((r.logged_date, r.weight, r.reps))
    lines = []
    for ex in sorted(by_ex):
        top = max(w for _, w, _ in by_ex[ex])
        recent = by_ex[ex][0]
        lines.append(f"  {ex}: top {top} lb (recent {recent[1]}x{recent[2]})")
    return "\n".join(lines)


def _prev_program_block(user_id: int, week: int) -> str:
    """Last week's PRESCRIBED lifts, so the coach anchors progression on the plan
    it set (not only logged top sets) and can't leap a load week-over-week (the
    97.5 -> 143 jump). Also shows the rest it committed so it stays consistent."""
    if week <= 1:
        return "(no prior week prescribed)"
    try:
        from models import WeeklyPrescription
        rows = (WeeklyPrescription.query
                .filter_by(user_id=user_id, week=week - 1)
                .order_by(WeeklyPrescription.day_idx,
                          WeeklyPrescription.exercise_order).all())
    except Exception:
        return "(unavailable)"
    if not rows:
        return "(no lifts prescribed last week)"
    lines = []
    for r in rows:
        w = f"{r.target_weight:g} lb" if r.target_weight else "BW"
        lines.append(f"  day{r.day_idx} {r.exercise_name}: {r.sets}x{r.reps} @ {w}"
                     + (f" (rest {r.rest})" if r.rest else ""))
    return "\n".join(lines)


def _prev_program_by_day(user_id: int, week: int) -> dict:
    """Last week's prescribed movements, STRUCTURED per day — used to backfill a
    day the coach under-prescribed (the volume FLOOR). Returns
    {day_idx: [{exercise, sets, reps, weight, rest, why}]} or {} for week 1."""
    if week <= 1:
        return {}
    try:
        from models import WeeklyPrescription
        # COACH rows ONLY. Last week can also contain template-seeded or legacy
        # engine rows; restoring one of those via the volume floor would launder
        # a static template exercise into the new week as source='coach' —
        # coach-or-nothing forbids that. And no invented defaults: a fabricated
        # rest ('90s') would sneak past the persist path's "coach omitted rest"
        # guard dressed as a coach decision.
        rows = (WeeklyPrescription.query
                .filter_by(user_id=user_id, week=week - 1, source='coach')
                .order_by(WeeklyPrescription.day_idx,
                          WeeklyPrescription.exercise_order).all())
    except Exception:
        return {}
    out: dict[int, list] = {}
    for r in rows:
        out.setdefault(r.day_idx, []).append({
            "exercise": r.exercise_name,
            "sets": r.sets or 3,
            "reps": r.reps or "8",
            "weight": r.target_weight,
            "rest": r.rest,  # the coach's OWN committed rest — never invented
            "why": r.adjustment_reason or "",
        })
    return out


# No scheduled deload weeks (2026-08-30) — the coach calls them from the data;
# the persisted flag (deload.is_deload_week) is the only truth.


def _prev_nondeload_total(user_id: int, week: int) -> int:
    """Total prescribed working sets of the most recent prior NON-deload week
    (< `week`, within this block, skipping weeks 4/8/12). This is the anti-taper
    ANCHOR: a non-deload week may never prescribe fewer total sets than the last
    real week, so volume can't bleed out the way block 1 did (163 -> 48).

    `_prev_program_by_day` only reads `week-1`, which after a deload IS the
    deload week — anchoring on that low total would stall the climb. This walks
    back to the last genuine training week instead. Returns 0 when there is no
    such prior week (e.g. block week 1)."""
    if week <= 1:
        return 0
    try:
        from models import WeeklyPrescription
        for w in range(week - 1, 0, -1):
            from deload import is_deload_week
            if is_deload_week(user_id, w):
                continue
            rows = WeeklyPrescription.query.filter_by(user_id=user_id, week=w).all()
            if rows:
                return sum((r.sets or 0) for r in rows)
    except Exception:
        return 0
    return 0


def _injury_block(user_id: int) -> str:
    try:
        from models import CoachMemory
        rows = (CoachMemory.query
                .filter(CoachMemory.user_id == user_id)
                .filter(CoachMemory.memory_type == "injury").all())
        notes = [r.content for r in rows if getattr(r, "content", None)]
        return "; ".join(notes) if notes else "(none recorded)"
    except Exception:
        return "(none recorded)"


def _catalog_for_prompt(available: set) -> tuple[str, dict]:
    """Build the allowed-exercise list (only equipment-compatible) grouped by
    muscle group, plus the catalog dict for validation."""
    from workout_data import EXERCISES
    by_mg: dict[str, list] = defaultdict(list)
    usable = {}
    for name, info in EXERCISES.items():
        need = set(info.get("equipment") or [])
        if need.issubset(available):
            by_mg[info.get("muscle_group", "other")].append(name)
            usable[name] = info
    lines = []
    for mg in sorted(by_mg):
        lines.append(f"  {mg}: " + ", ".join(sorted(by_mg[mg])))
    return "\n".join(lines), usable


def generate_week_program(user_id: int, week: int, user_context: dict):
    """Design the full week's strength program. Returns (program, dropped).
    program = {day_idx: [{exercise, sets, reps, weight, why}]}; {} on failure."""
    from models import UserEquipment
    eq = UserEquipment.query.filter_by(user_id=user_id).first()
    available = set((eq.available_equipment if eq else []) or [])
    catalog_str, catalog = _catalog_for_prompt(available)
    history = _history_block(user_id, week)
    prev_program = _prev_program_block(user_id, week)
    injuries = _injury_block(user_id)

    phase = user_context.get("phase", "?")
    # True/False = the athlete already decided (codified [DELOAD] marker); None = the
    # coach decides from the evidence block below (deload.py).
    deload_forced = user_context.get("deload")
    goal_type = user_context.get("goal_type", "recomp")
    target_sets = user_context.get("target_weekly_sets", 80)
    current_wt = user_context.get("current_weight")
    target_wt = user_context.get("target_weight")
    train_days = user_context.get("train_days", 6)

    phase_intent = {
        1: "hypertrophy/adaptation — moderate loads, 8-12 reps, highest volume",
        2: "strength — heavier, 3-6 reps",
        3: "strength, leaner — heavy 3-6 reps, FULL volume (no taper), loads keep climbing",
    }.get(phase, "balanced")

    system = (
        "You are a strength coach who designs the athlete's ENTIRE week of "
        "lifting from scratch — exercise selection, sets, reps, AND load for "
        "every movement. There is no fixed template; you own the program.\n\n"
        "ABSOLUTE RULES:\n"
        "1. PICK EXERCISES ONLY from the ALLOWED list below (it is already "
        "   filtered to the athlete's equipment). Never invent a movement or "
        "   name one not on the list — it will be discarded.\n"
        "2. RESPECT INJURIES. Avoid movements that aggravate the listed "
        "   injuries; pick joint-friendly alternatives from the list.\n"
        "3. WEIGHTS come from history and MUST be loadable on real equipment:\n"
        "   • BARBELL lifts (bench, squat, deadlift, OHP, barbell row, hip "
        "     thrust, RDL) load a 45-lb bar with 5-lb-and-up plates → the total "
        "     is 45 + a multiple of 10 and ALWAYS ENDS IN 5 (45, 55, … 135, 145, "
        "     155). A barbell is NEVER 150 or 147.5. The smallest barbell "
        "     progression is +10 lb — there is no +2.5 or +5 on a barbell.\n"
        "   • DUMBBELLS and MACHINES move in 5-lb steps.\n"
        "   For movements the athlete already logs, load from those logs: never "
        "   below a recent top set unless deload; progress compounds +10 lb "
        "   (one plate step) and dumbbell/machine accessories +5 lb when reps "
        "   are hit clean. A movement that appears in RECENT TOP SETS below is "
        "   NOT new — never call it 'new', 'baseline', or 'introduced'. NEW "
        "   (truly no-history) movements are WELCOME — start DELIBERATELY LIGHT, "
        "   then ramp UP FAST. NEVER prescribe a heavy 1RM cold. Bodyweight/"
        "   plyo: weight 0.\n"
        "3b. Your `why` MUST state the SAME final number you prescribe in "
        "   `weight`. If you write a delta ('+10 from 145'), it must add up to "
        "   that exact weight. Never narrate a different number than you load.\n"
        f"4. WEEKLY VOLUME: prescribe AT LEAST {target_sets} working sets — a "
        f"   FLOOR to meet or exceed, never to undershoot — and treat "
        f"   {target_sets + 8} as a HARD CEILING you may approach but not exceed. "
        "   Volume TRENDS UP across the block: NEVER prescribe fewer total working "
        "   sets than the last non-deload week. The athlete also runs daily in a "
        "   calorie deficit, so manage recovery through LOAD selection and exercise "
        "   choice — do NOT cut total volume to do it. Roughly "
        f"   {max(4, round(target_sets / max(1, train_days) / 3.5))}-6 exercises "
        "   per lifting day. There are NO scheduled deload weeks — if YOU call a "
        "   deload (DELOAD DECISION block), use ~55% of the target via LIGHTER LOADS "
        "   and FEWER MOVEMENTS — never fewer sets per movement.\n"
        "4c. LIFTING VOLUME IS PROTECTED during this cut (athlete directive "
        "   2026-08-30): when fatigue needs managing, cut RUNNING volume FIRST via "
        "   reduce_running below and manage lifting through LOAD selection — a "
        "   lifting deload is the LAST resort, and the athlete may veto it (his "
        "   veto is final).\n"
        f"4b. EVERY exercise is AT LEAST {MIN_SETS} working sets — never 1 or 2, "
        "   deload weeks included. A 2-set exercise is not a prescription.\n"
        "5. Cover the major muscle groups across the week (legs, chest, back, "
        "   shoulders, arms, posterior chain, core) WITHOUT overlapping the same "
        "   heavy pattern on back-to-back days (his legs also take the running "
        "   load). Lead each day with the heaviest compound when CNS is fresh.\n"
        f"6. Train {train_days} lifting days; the 7th day is rest (long run). "
        "   Use day indices 0=Mon … 6=Sun.\n"
        "7. REST: choose ONE committed rest per exercise from the movement and "
        "   intent — heavy compounds rest longer (e.g. 2-3 min), accessories "
        "   shorter (e.g. 45-90s). Output a SINGLE value like \"90s\" or "
        "   \"2 min\" — NEVER a range (not \"90s-2 min\"), never omit it.\n"
        "8. NEVER jump a logged movement's load more than ~+10-15 lb (compound) "
        "   or +5 lb (accessory) vs LAST WEEK'S PRESCRIPTION below. A +40 lb / "
        "   +40% week-over-week jump is a hard fail — progress is incremental.\n"
        "9. Each exercise needs a ONE-sentence why covering BOTH the load/"
        "   selection AND the rest you chose.\n\n"
        "Output ONE JSON object mapping `<day_idx>` to a list of "
        '{"exercise": "<exact catalog name>", "sets": <int>, "reps": "<str>", '
        '"weight": <num|0>, "rest": "<single value, e.g. 90s or 2 min — never a '
        'range>", "why": "<one sentence: load + rest rationale>"}. The object MUST '
        'also carry the key "deload": {"call": <true|false>, "reason": "<one sentence '
        'citing the evidence>"} and MAY carry "reduce_running": {"call": <true|false>, '
        '"reason": "<one sentence>"} to trim easy-run volume instead of lifting. '
        'JSON only, no prose.'
    )
    layoff = _layoff_days(user_id)
    layoff_block = ""
    if layoff is not None and layoff >= LAYOFF_MODERATE:
        frac = (LAYOFF_CAP_FRAC[LAYOFF_LONG]
                if layoff >= LAYOFF_LONG else LAYOFF_CAP_FRAC[LAYOFF_MODERATE])
        layoff_block = (
            f"\nRETURN FROM LAYOFF — READ FIRST: the athlete has NOT lifted in "
            f"{layoff // 7} weeks (last logged set {layoff} days ago). The top "
            f"sets below are PRE-LAYOFF numbers, not current ability. Design a "
            f"RETURN week: loads at ~{int(frac * 100)}% of those tops, moderate "
            f"volume, nothing near failure, full-body competence over "
            f"specialization. Say in each why that this is a return ramp and "
            f"loads rebuild over 2-3 weeks. A deterministic rail will cap any "
            f"load above {int(frac * 100)}% of a movement's recent top.\n")
    from deload import deload_evidence_text, DELOAD_VOLUME_FACTOR
    from datetime import date as _date
    try:
        _evidence = deload_evidence_text(user_id, week, user_context.get("today") or _date.today())
    except Exception:
        log.warning("deload evidence failed", exc_info=True)
        _evidence = "DELOAD DECISION — yours; evidence unavailable. Default = NORMAL week."
    if deload_forced is None:
        _deload_block = _evidence
    else:
        _deload_block = (
            f"DELOAD DECISION — ALREADY MADE BY THE ATHLETE: deload={'true' if deload_forced else 'false'} "
            f"({user_context.get('deload_override_reason') or 'athlete decision'}). Obey it and echo it in "
            f"the \"deload\" key." + (f" Use ~{int(DELOAD_VOLUME_FACTOR * 100)}% of the volume target." if deload_forced else ""))
    user_prompt = (
        f"ATHLETE:\n- Goal {goal_type}, {current_wt} lb → {target_wt} lb\n"
        f"- Week {week}, phase {phase} ({phase_intent})\n"
        f"- Injuries/limits: {injuries}\n"
        f"{layoff_block}\n"
        f"{_deload_block}\n\n"
        f"ALLOWED EXERCISES (equipment-filtered — use these exact names):\n{catalog_str}\n\n"
        f"RECENT TOP SETS (last 4 weeks):\n{history}\n\n"
        f"LAST WEEK'S PRESCRIBED PROGRAM (anchor progression here — match or "
        f"nudge up incrementally, NEVER leap a load):\n{prev_program}\n\n"
        "Design the week. JSON only."
    )

    try:
        client = _anthropic_client()
        resp = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=4000,
            system=system, messages=[{"role": "user", "content": user_prompt}],
        )
        text = "".join(b.text for b in resp.content
                        if getattr(b, "type", None) == "text").strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        parsed = json.loads(text)
    except Exception as e:
        log.warning("generate_week_program failed: %s", e)
        return {}, [], {"deload": False, "reason": None}
    raw_dec = parsed.pop("deload", None) if isinstance(parsed, dict) else None
    if deload_forced is not None:
        deload = bool(deload_forced)
        reason = user_context.get("deload_override_reason") or "athlete decision"
    elif isinstance(raw_dec, dict):
        deload = bool(raw_dec.get("call"))
        reason = (str(raw_dec.get("reason") or "").strip() or None)
    else:
        deload, reason = False, None
    raw_rr = parsed.pop("reduce_running", None) if isinstance(parsed, dict) else None
    reduce_running = None
    if isinstance(raw_rr, dict) and raw_rr.get("call"):
        reduce_running = {"call": True,
                          "reason": (str(raw_rr.get("reason") or "").strip() or None)}
    decision = {"deload": deload, "reason": reason, "reduce_running": reduce_running}
    if deload:
        log.info("strength coach called a DELOAD for week %s: %s", week, reason)

    clean, dropped = validate_program(parsed, catalog, available)

    # Code-enforced safety rails — the prompt alone does not reliably hold them.
    from models import SetLog
    from workout_data import resolve_name
    hist_rows = (SetLog.query
                 .filter(SetLog.user_id == user_id, SetLog.weight > 0,
                         SetLog.week >= max(1, week - 4)).all())
    hist_ex = {resolve_name(r.exercise_name) for r in hist_rows}
    hist_max = max([r.weight for r in hist_rows], default=0)
    hist_top = {}  # per-movement recent top set, for the jump cap
    for r in hist_rows:
        if r.weight:
            k = _movement_key(resolve_name(r.exercise_name))
            hist_top[k] = max(hist_top.get(k, 0), r.weight)
    rest_day = 6 if train_days <= 6 else -1  # Sunday is the long-run/rest day
    ceiling = int(target_sets) + 8
    # Weekly volume FLOOR — the anti-taper rail. Never below 0.92*target, and
    # never below the last NON-deload week's prescribed total (so a post-deload
    # week can't anchor on the deload's low number and stall the climb). Week 1
    # has no prior week -> _prev_nondeload_total returns 0, so the floor is just
    # the 0.92*target clause (no throw, no zero-floor).
    floor = 0 if deload else max(round(0.92 * int(target_sets)),
                                 _prev_nondeload_total(user_id, week))
    clean, actions = enforce_safety(
        clean, rest_day_idx=rest_day, ceiling=ceiling,
        history_exercises=hist_ex, history_max_weight=hist_max,
        history_top=hist_top,
        prev_by_day=_prev_program_by_day(user_id, week),
        min_per_day=4, deload=deload, floor=floor,
        layoff_days=_layoff_days(user_id),
    )
    notes = dropped + actions
    if notes:
        log.info("program coach adjustments: %s", notes[:8])
    return clean, notes, decision
