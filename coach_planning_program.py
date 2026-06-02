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

# Equipment / grip qualifiers that describe the SAME movement (so a coach name
# like "Barbell Hip Thrust" maps to logged "Hip Thrust"). The core movement
# words (hip thrust, deadlift, row, curl, ...) are preserved.
_EQUIP_MODIFIERS = re.compile(
    r'\b(barbell|bb|dumbbell|dumbell|db|cable|machine|smith|ez[\s-]?bar|'
    r'wide[\s-]?grip|close[\s-]?grip|narrow[\s-]?grip|neutral[\s-]?grip|'
    r'reverse[\s-]?grip|wide|close|narrow)\b', re.I)


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
            sets = max(1, min(6, sets))
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


def enforce_safety(program, *, rest_day_idx, ceiling, history_exercises,
                   history_max_weight, history_top=None, new_move_frac=0.6,
                   max_jump_frac=0.20, prev_by_day=None, min_per_day=4,
                   deload=False):
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

    # 3. volume ceiling — trim non-lead (accessory) sets first
    def _total():
        return sum(it["sets"] for items in out.values() for it in items)

    trimmed = False
    guard = 0
    while _total() > ceiling and guard < 1000:
        guard += 1
        cand = None
        for d, items in out.items():
            for idx, it in enumerate(items):
                if idx == 0:
                    continue  # protect the day's lead compound
                if cand is None or it["sets"] > cand[1]["sets"]:
                    cand = (d, it)
        if cand is None:  # only leads remain — trim them as a last resort
            for d, items in out.items():
                for it in items:
                    if cand is None or it["sets"] > cand[1]["sets"]:
                        cand = (d, it)
        if cand is None:
            break
        d, it = cand
        it["sets"] -= 1
        trimmed = True
        if it["sets"] <= 0:
            out[d] = [x for x in out[d] if x is not it]
    if trimmed:
        actions.append(f"Trimmed volume to ceiling of {ceiling} working sets.")

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
        rows = (WeeklyPrescription.query
                .filter_by(user_id=user_id, week=week - 1)
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
            "rest": r.rest or "90s",
            "why": r.adjustment_reason or "",
        })
    return out


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
    deload = user_context.get("deload", False)
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
        f"4. WEEKLY VOLUME: aim for {target_sets} working sets and treat "
        f"   {target_sets + 8} as a HARD CEILING. Do NOT exceed it. More is "
        "   NOT better — the athlete also runs ~40 mi/wk in a calorie deficit, "
        "   so recovery is the binding constraint. Roughly "
        f"   {max(3, round(target_sets / max(1, train_days) / 3.5))}-5 exercises "
        "   per lifting day. On a deload week use ~55% volume and lighter loads.\n"
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
        'range>", "why": "<one sentence: load + rest rationale>"}. JSON only, no prose.'
    )
    user_prompt = (
        f"ATHLETE:\n- Goal {goal_type}, {current_wt} lb → {target_wt} lb\n"
        f"- Week {week}, phase {phase} ({phase_intent}){' — DELOAD WEEK' if deload else ''}\n"
        f"- Injuries/limits: {injuries}\n\n"
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
        return {}, []

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
    clean, actions = enforce_safety(
        clean, rest_day_idx=rest_day, ceiling=ceiling,
        history_exercises=hist_ex, history_max_weight=hist_max,
        history_top=hist_top,
        prev_by_day=_prev_program_by_day(user_id, week),
        min_per_day=4, deload=deload,
    )
    notes = dropped + actions
    if notes:
        log.info("program coach adjustments: %s", notes[:8])
    return clean, notes
