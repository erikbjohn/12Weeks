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
    artifact (±window / generous cap), NOT plan content. Non-numeric → None."""
    if not hr_text:
        return None
    t = str(hr_text)
    nums = [int(n) for n in re.findall(r"(?<![A-Za-z])\d+(?![A-Za-z])", t)]
    if not nums:
        return None
    if len(nums) >= 2:
        return (nums[0], nums[1])
    n = nums[0]
    if "≥" in t or ">" in t:
        return (n, min(n + 25, 200))
    if "≤" in t or "<" in t:
        return (max(n - 45, 80), n)
    return (n - 5, n + 5)


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
