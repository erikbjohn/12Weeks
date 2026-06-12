"""Garmin Connect sync: pull activities into RunLog, push planned runs/HIIT
to the watch as scheduled structured workouts.

Design doc: docs/superpowers/specs/2026-06-11-garmin-sync-design.md

Pure helpers (parser, builder, aggregation) live at module level with no app
imports so they're unit-testable; DB-touching functions import models inside
the function body.
"""

import hashlib
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone

log = logging.getLogger(__name__)

# Activity typeKeys that count as the day's run/HIIT. Strength and everything
# else is ignored (lifts are logged set-by-set in the app).
RUN_TYPE_KEYS = {
    "running", "trail_running", "treadmill_running", "track_running",
    "indoor_running", "virtual_run", "street_running",
}
HIIT_TYPE_KEYS = {"hiit", "indoor_cardio", "cardio"}

# ---------------------------------------------------------------------------
# Prose parser — exact inverse of coach_planning_runs._segments_to_detail.
# Stored detail = "<segments prose> — <rationale>"; parts joined by "; ".
# ---------------------------------------------------------------------------

# n× prefix is optional here — _segments_to_detail always emits it for work, but '1×' and no-prefix parse the same (conservative).
_WORK_RE = re.compile(
    r"^(?:(?P<reps>\d+)×)?(?P<mins>\d+(?:\.\d+)?) min hard"
    r"(?: @ HR (?P<hr>[^/()]+?))?"
    r"(?: / (?P<easymins>\d+(?:\.\d+)?) min easy)?"
    r"(?: \((?P<note>.*)\))?$"
)
_PLAIN_RE = re.compile(
    r"^(?:(?P<reps>\d+)×)?(?P<mins>\d+(?:\.\d+)?) min (?P<kind>warmup|recovery|cooldown|steady)"
    r"(?: \((?P<extra>.*)\))?$"
)
# parenthesized HR annotation in plain segments, e.g. '(@ HR ≤135)' or '(@ HR ≤135 keep it easy)'.
_EXTRA_HR_RE = re.compile(r"^@ HR (?P<hr>\S+)\s*(?P<note>.*)$")


def _num(s):
    """Return int when s is a whole number, else float."""
    f = float(s)
    return int(f) if f == int(f) else f


def parse_detail_to_segments(detail):
    """Invert _segments_to_detail. Returns [{kind, minutes, reps, hr?, note?}]
    or None when ANY part doesn't match the machine format — callers must then
    fall back to a single timed workout (never invent structure)."""
    if not detail:
        return None
    prose = detail.split(" — ")[0].strip()
    if not prose:
        return None
    segments = []
    for part in [p.strip() for p in prose.split(";")]:
        if not part:
            return None
        m = _WORK_RE.match(part)
        if m:
            reps = int(m.group("reps")) if m.group("reps") else 1
            seg = {"kind": "work", "minutes": _num(m.group("mins")), "reps": reps}
            if m.group("hr"):
                seg["hr"] = m.group("hr").strip()
            if m.group("note"):
                seg["note"] = m.group("note")
            segments.append(seg)
            if m.group("easymins"):
                segments.append({"kind": "recovery", "minutes": _num(m.group("easymins")), "reps": reps})
            continue
        m = _PLAIN_RE.match(part)
        if m:
            seg = {
                "kind": m.group("kind"),
                "minutes": _num(m.group("mins")),
                "reps": int(m.group("reps")) if m.group("reps") else 1,
            }
            extra = m.group("extra")
            if extra:
                m2 = _EXTRA_HR_RE.match(extra)
                if m2:
                    seg["hr"] = m2.group("hr")
                    if m2.group("note"):
                        seg["note"] = m2.group("note")
                else:
                    seg["note"] = extra
            segments.append(seg)
            continue
        return None
    return segments or None


def segments_total_minutes(segments):
    """Sum of minutes×reps — must equal the stored duration or we fall back."""
    total = 0
    for s in segments or []:
        total += (s.get("minutes") or 0) * (s.get("reps") or 1)
    return total


# ---------------------------------------------------------------------------
# Garmin structured-workout JSON (workout-service schema).
# All sessions push as running workouts; HIIT days are run-based intervals.
# Schema mirrored from Garmin Connect workout-service payloads; verified live
# in Task 11 against get_workouts() on a real workout.
# ---------------------------------------------------------------------------

_STEP_TYPE = {
    "warmup": {"stepTypeId": 1, "stepTypeKey": "warmup"},
    "cooldown": {"stepTypeId": 2, "stepTypeKey": "cooldown"},
    "work": {"stepTypeId": 3, "stepTypeKey": "interval"},
    "steady": {"stepTypeId": 3, "stepTypeKey": "interval"},
    "recovery": {"stepTypeId": 4, "stepTypeKey": "recovery"},
}
_SPORT_RUNNING = {"sportTypeId": 1, "sportTypeKey": "running"}
_NO_TARGET = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"}
_HR_TARGET = {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone"}


def _hr_bounds(hr_text):
    """Coach HR cue → (low, high) bpm for Garmin's custom HR range, which
    requires BOTH bounds. The bound the coach didn't state is an encoding
    artifact (±window / generous cap), NOT plan content.
    Non-numeric, implausible (e.g. "Z2", "zone 2"), or degenerate (low >= high) → None."""
    if not hr_text:
        return None
    t = str(hr_text)
    nums = [int(n) for n in re.findall(r"\b\d{2,3}\b", t) if 60 <= int(n) <= 220]
    if not nums:
        return None
    if len(nums) >= 2:
        bounds = (nums[0], nums[1])
    else:
        n = nums[0]
        if "≥" in t or ">" in t:
            bounds = (n, min(n + 25, 200))
        elif "≤" in t or "<" in t:
            bounds = (max(n - 45, 80), n)
        else:
            bounds = (n - 5, n + 5)
    low, high = bounds
    return None if low >= high else (low, high)


def _exec_step(seg, order):
    kind = (seg.get("kind") or "steady").lower()
    step = {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": dict(_STEP_TYPE.get(kind, _STEP_TYPE["steady"])),
        "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time"},
        "endConditionValue": float(seg.get("minutes") or 0) * 60.0,
    }
    bounds = _hr_bounds(seg.get("hr"))
    if bounds:
        step["targetType"] = dict(_HR_TARGET)
        step["targetValueOne"], step["targetValueTwo"] = bounds
    else:
        step["targetType"] = dict(_NO_TARGET)
    if seg.get("note"):
        step["description"] = str(seg["note"])[:200]
    return step


def _repeat_group(children, iterations, order_start):
    order = order_start
    group = {
        "type": "RepeatGroupDTO",
        "stepOrder": order,
        "stepType": {"stepTypeId": 6, "stepTypeKey": "repeat"},
        "numberOfIterations": iterations,
        "smartRepeat": False,
        "endCondition": {"conditionTypeId": 7, "conditionTypeKey": "iterations"},
        "workoutSteps": [],
    }
    order += 1
    for child in children:
        group["workoutSteps"].append(_exec_step(child, order))
        order += 1
    return group, order


def build_workout_json(name, segments):
    """Segments → Garmin running workout. Work+recovery pairs with reps>1
    become a repeat group (matching how the prose reads as intervals)."""
    steps = []
    order = 1
    segs = list(segments or [])
    i = 0
    while i < len(segs):
        s = segs[i] or {}
        kind = (s.get("kind") or "steady").lower()
        reps = int(s.get("reps") or 1)
        nxt = segs[i + 1] if i + 1 < len(segs) else None
        nxt_kind = (nxt.get("kind") or "").lower() if nxt else None
        if kind == "work" and reps > 1 and nxt_kind == "recovery":
            group, order = _repeat_group([s, nxt], reps, order)
            steps.append(group)
            i += 2
            continue
        if reps > 1:
            group, order = _repeat_group([s], reps, order)
            steps.append(group)
        else:
            steps.append(_exec_step(s, order))
            order += 1
        i += 1
    return {
        "workoutName": name,
        "sportType": dict(_SPORT_RUNNING),
        "workoutSegments": [{
            "segmentOrder": 1,
            "sportType": dict(_SPORT_RUNNING),
            "workoutSteps": steps,
        }],
    }


def build_simple_timed_workout(name, total_minutes):
    """Fallback when structure can't be recovered: one timed step, no target.
    Correct label + duration, never invented intervals."""
    return build_workout_json(name, [{"kind": "steady", "minutes": total_minutes, "reps": 1}])


def structure_hash(workout_json, date_iso):
    """Idempotency key: same structure + same calendar date → no re-push."""
    payload = json.dumps(workout_json, sort_keys=True) + "|" + date_iso
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Program calendar mapping + daily aggregation
# ---------------------------------------------------------------------------

def week_day_for_date(start_date, d):
    """Inverse of app.py's `start_date + (week-1)*7 + day_idx`. (None, None)
    when outside the 12-week program window."""
    if not start_date or not d:
        return (None, None)
    diff = (d - start_date).days
    if diff < 0:
        return (None, None)
    week = diff // 7 + 1
    if week > 12:
        return (None, None)
    return (week, diff % 7)


def aggregate_day(rows):
    """Aggregate one day's activities (dicts or GarminActivity rows) into
    RunLog fields. Doubles sum distance/duration/elevation; HR is the
    duration-weighted mean (consistent with avg_hr = whole-run mean)."""
    def _get(r, k):
        return r.get(k) if isinstance(r, dict) else getattr(r, k, None)

    rows = [r for r in (rows or [])
            if (_get(r, "duration_min") or 0) > 0 or (_get(r, "distance_miles") or 0) > 0]
    if not rows:
        return None
    dist = round(sum(_get(r, "distance_miles") or 0 for r in rows), 2)
    dur = int(sum(_get(r, "duration_min") or 0 for r in rows))
    elev = int(sum(_get(r, "elevation_ft") or 0 for r in rows))
    hr_rows = [r for r in rows if _get(r, "avg_hr") and _get(r, "duration_min")]
    hr = None
    if hr_rows:
        hr = int(round(sum(_get(r, "avg_hr") * _get(r, "duration_min") for r in hr_rows)
                       / sum(_get(r, "duration_min") for r in hr_rows)))
    return {
        "distance_miles": dist or None,
        "duration_min": dur or None,
        "avg_hr": hr,
        "elevation_ft": elev or None,
    }

# ---------------------------------------------------------------------------
# PULL: Garmin activities → GarminActivity audit rows → RunLog
# ---------------------------------------------------------------------------

_RAW_KEYS = ("activityId", "activityName", "startTimeLocal", "distance",
             "duration", "averageHR", "maxHR", "elevationGain")


def sync_activities(gc, user_id, days_back=3, today=None):
    """Pull recent running/HIIT activities and fill RunLog for days the user
    hasn't logged manually. Manual logs (source NULL/'manual') are never
    touched; sync-created logs (source='garmin') are kept up to date."""
    from models import db, AppState, RunLog, GarminActivity

    result = {"pulled": 0, "days_filled": [], "days_skipped_manual": [],
              "ignored": 0, "error": None}
    today = today or date.today()
    state = AppState.query.filter_by(user_id=user_id).first()
    start_date = state.start_date if state else None

    start = (today - timedelta(days=days_back)).isoformat()
    acts = gc.get_activities_between(start, today.isoformat())
    if acts is None:
        result["error"] = "Garmin activity fetch failed (not connected or rate limited)"
        return result

    touched = set()
    for a in acts:
        type_key = ((a.get("activityType") or {}).get("typeKey") or "").lower()
        if type_key not in RUN_TYPE_KEYS | HIIT_TYPE_KEYS:
            result["ignored"] += 1
            continue
        aid = str(a.get("activityId"))
        start_local = a.get("startTimeLocal") or ""
        act_date = None
        if len(start_local) >= 10:
            try:
                act_date = date.fromisoformat(start_local[:10])
            except ValueError:
                act_date = None
        week, day_idx = week_day_for_date(start_date, act_date)
        fields = dict(
            user_id=user_id,
            type_key=type_key,
            start_time_local=start_local,
            activity_date=act_date,
            week=week,
            day_idx=day_idx,
            distance_miles=round((a.get("distance") or 0) / 1609.344, 2),
            duration_min=int(round((a.get("duration") or 0) / 60.0)),
            avg_hr=int(a["averageHR"]) if a.get("averageHR") else None,
            elevation_ft=int(round((a.get("elevationGain") or 0) * 3.28084)),
            raw_summary=json.dumps({k: a.get(k) for k in _RAW_KEYS}),
        )
        row = GarminActivity.query.filter_by(user_id=user_id, garmin_activity_id=aid).first()
        if row:
            for k, v in fields.items():
                setattr(row, k, v)
        else:
            db.session.add(GarminActivity(garmin_activity_id=aid, **fields))
            result["pulled"] += 1
        if week is not None:
            touched.add((week, day_idx))
    db.session.commit()

    for week, day_idx in sorted(touched):
        key = f"w{week}d{day_idx}"
        existing = RunLog.query.filter_by(user_id=user_id, week=week, day_idx=day_idx).first()
        if existing and (existing.source or "manual") != "garmin":
            result["days_skipped_manual"].append(key)
            continue
        rows = GarminActivity.query.filter_by(user_id=user_id, week=week, day_idx=day_idx).all()
        agg = aggregate_day(rows)
        if not agg:
            continue
        if not existing:
            existing = RunLog(user_id=user_id, week=week, day_idx=day_idx,
                              log_date=rows[0].activity_date)
            db.session.add(existing)
        existing.distance_miles = agg["distance_miles"]
        existing.duration_min = agg["duration_min"]
        existing.avg_hr = agg["avg_hr"]
        existing.elevation_ft = agg["elevation_ft"]
        existing.source = "garmin"
        result["days_filled"].append(key)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        log.exception("Garmin sync RunLog commit failed")
        result["error"] = f"DB commit failed: {e}"
    return result
