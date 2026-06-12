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
_EXTRA_HR_RE = re.compile(r"^@ HR (?P<hr>\S+)\s*(?P<note>.*)$")


def _num(s):
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
