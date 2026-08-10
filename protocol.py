"""protocol.py — peptide-protocol reference + pure derivations.

PURE MODULE: no Flask imports, no DB access. Every function here takes plain
lists of row-shaped objects (the caller passes `models.PeptideDose` /
`models.PeptideVial` rows, or test stubs with the same attributes) and
returns plain dicts/lists. This module never touches the database or the
request context, so it can be unit-tested without an app context.

── Reference dict ───────────────────────────────────────────────────────
`PROTOCOL_COMPOUNDS` is coach-context reference material ONLY. It carries
NO schedule/cadence text anywhere (no dose amounts, no frequency, no times
of day) — cadence and dose size are never hardcoded here; they are always
DERIVED from the actual `PeptideDose` rows (see `escalation_dates`,
`vial_status`, etc). `watch_fors` and `mechanism` exist purely so the coach
has something to say about a compound in conversation; they are not
instructions and are not used for any gating logic. `missed_dose_rule` is
always the literal placeholder `CONFIRM_WITH_DOCTOR` and `late_window_hours`
is always `None` at ship — this app never invents a "safe to take late"
window; that has to come from the user's doctor before it's wired in.

── Date-authority semantics (critical) ──────────────────────────────────
A dose row's own `date` column is the SOLE authority for which day it counts
toward. `taken_at` is an audit-trail timestamp only (it records WHEN the
user tapped "taken", which — because a 22:00 dose logged locally can cross
midnight UTC — can land on the calendar day AFTER `date`). No function in
this module ever derives taken-ness or the counted day from `taken_at`'s
date. The one and only use of `taken_at.date() > row.date` is to
SUBCLASSIFY an already-taken row as "late" in `adherence_7d` — it is never
used to decide whether a row counts as taken, and it is never used to pick
which day a dose belongs to. Because of this, none of the functions in this
module do any timezone conversion or "local day" arithmetic at all, which
means DST transitions (e.g. the US fall-back on 2026-11-01) are simply
irrelevant to every derivation here — there is no local-time math to get
wrong in the first place.

── Escalation-date definition (derived from real CSV, not hardcoded) ────
`escalation_dates` must yield exactly the three retatrutide exposure-rise
dates in the shipped protocol: 2026-08-24 (2mg -> 3mg), 2026-09-10
(1x/week -> 2x/week), 2026-09-21 (3mg -> 4mg).

FIX ROUND 1 (2026-08-10 review): the original definition here was "trailing
7-day sum exceeds the max of all prior trailing sums" over a rolling
scheduled-mg window. Reviewer found two real bugs: (a) it is NOT robust to a
held/removed dose — pulling one row out (e.g. a 2026-09-24 dose held for
GI/travel) shifts which future dates the rolling window "catches up" on and
can fabricate a phantom escalation on a later date where nothing actually
changed; (b) it can MERGE two genuine, independent step-ups that happen to
land close enough together that the rolling window is still rising from the
first one when the second one hits, reporting only one date instead of two.
Both bugs trace to the same root cause: reasoning about a SUM inherently
entangles "how many doses are in the window" with "how big each dose is",
so a change in either one perturbs a quantity that's supposed to represent
both, and a single dip-then-recover in that entangled quantity can look
identical to a fresh, real increase.

The replacement definition decomposes escalation into the two INDEPENDENT
real-world events it's actually about, each tracked via a monotonically
non-decreasing running maximum (a running max only advances on a genuine
new high; a hold, a removed row, or a dip-then-recover can never re-trigger
it, because it never goes down):

  1. DOSE-STEP: a dose date whose `dose_mg` exceeds the running MAX
     `dose_mg` of all STRICTLY EARLIER doses of that compound. Held doses
     (dose_mg <= 0, whether represented by omitting the row entirely or by
     keeping the row with dose_mg=0) are excluded from consideration
     entirely — they contribute to neither the running max nor the
     trailing count below, so a hold can never spuriously suppress or
     manufacture a step.
  2. FREQUENCY-STEP: a dose date whose trailing-7-day (inclusive) dose
     COUNT exceeds the running MAX trailing-7-day count over all earlier
     dose dates, PROVIDED this date's dose_mg has not dropped below the
     running max dose (a frequency bump that coincides with a dose
     REDUCTION — e.g. TB-500's loading->maintenance step-down — is not
     rising overall exposure and must not be flagged).

  `escalation_dates` = the sorted UNION of both kinds' dates (deduped — a
  date can in principle carry both kinds, e.g. a simultaneous dose AND
  frequency increase, and still counts once). `next_escalation` reports the
  `kind` ("dose" | "frequency") and a human-readable `detail` string for
  the nearest upcoming date; ties on the same date prefer the dose-step
  (dose-steps are evaluated before frequency-steps within a date).

  Verified against the shipped CSV: dose-steps = [2026-08-24 (2mg->3mg),
  2026-09-21 (3mg->4mg)]; frequency-steps = [2026-09-10 (1x/wk->2x/wk)];
  union = exactly [2026-08-24, 2026-09-10, 2026-09-21]. Also verified
  robust to removing (or zeroing) the 2026-09-24 row — same three dates,
  no phantom — and to two independent dose-steps landing only 3 days
  apart — both fire on their own distinct dates, never merged.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time as _time, timedelta
from typing import Optional

CONFIRM_WITH_DOCTOR = "confirm with your doctor"

PROTOCOL_COMPOUNDS: dict[str, dict] = {
    "Enclomiphene": {
        "what": "Oral selective estrogen receptor modulator (SERM) used off-label to support endogenous testosterone production.",
        "mechanism": "Blocks estrogen receptors at the hypothalamus/pituitary, reducing negative feedback so LH and FSH pulsatility rises, which drives up endogenous testosterone production.",
        "effects": [
            "Increased serum testosterone",
            "Preserves fertility and spermatogenesis relative to exogenous TRT",
            "Can shift mood and energy as testosterone rises",
        ],
        "watch_fors": [
            "Mood swings, irritability, or anxiety",
            "Visual disturbances (rare, SERM class effect) — flag any changes immediately",
            "Headache",
        ],
        "missed_dose_rule": CONFIRM_WITH_DOCTOR,
        "late_window_hours": None,
    },
    "BPC-157": {
        "what": "Synthetic peptide fragment derived from a gastric body-protective compound, used off-label for soft-tissue and gut recovery.",
        "mechanism": "Promotes angiogenesis and fibroblast migration and modulates growth-factor pathways involved in tissue repair.",
        "effects": [
            "Supports soft-tissue and tendon/ligament healing",
            "Reported gut-lining and GI-comfort support",
            "Often paired with tissue-repair training blocks",
        ],
        "watch_fors": [
            "Injection-site redness, swelling, or irritation",
            "Unexpected GI symptoms",
            "Any new joint or tendon pain that doesn't track with training load",
        ],
        "missed_dose_rule": CONFIRM_WITH_DOCTOR,
        "late_window_hours": None,
    },
    "KPV": {
        "what": "Anti-inflammatory tripeptide (C-terminal fragment of alpha-MSH) used off-label for inflammation and gut support.",
        "mechanism": "Inhibits NF-kB signaling, dampening pro-inflammatory cytokine production locally and systemically.",
        "effects": [
            "General anti-inflammatory support",
            "Often stacked alongside BPC-157 for gut/tissue protocols",
        ],
        "watch_fors": [
            "Injection-site reaction",
            "Any signs of over-suppressed immune response (frequent illness)",
        ],
        "missed_dose_rule": CONFIRM_WITH_DOCTOR,
        "late_window_hours": None,
    },
    "Retatrutide": {
        "what": "Triple hormone-receptor agonist (GIP/GLP-1/glucagon) investigational compound used off-label for weight loss.",
        "mechanism": "Simultaneously activates GIP, GLP-1, and glucagon receptors, suppressing appetite, slowing gastric emptying, and increasing energy expenditure.",
        "effects": [
            "Significant appetite suppression",
            "Progressive fat-mass loss",
            "Can affect training energy and hunger-driven recovery cues",
        ],
        "watch_fors": [
            "Nausea, GI upset, or reflux, especially after dose increases",
            "Dehydration — appetite suppression can also blunt thirst",
            "Unintended lean-mass loss if protein/training aren't kept up as fat loss accelerates",
        ],
        "missed_dose_rule": CONFIRM_WITH_DOCTOR,
        "late_window_hours": None,
    },
    "TB-500": {
        "what": "Synthetic fragment of thymosin beta-4, used off-label for tissue repair and recovery.",
        "mechanism": "Upregulates actin regulation and cell migration, supporting angiogenesis and reducing inflammation in injured tissue.",
        "effects": [
            "Supports muscle, tendon, and ligament recovery",
            "May reduce post-training inflammation",
        ],
        "watch_fors": [
            "Injection-site soreness or bruising",
            "Fatigue that doesn't track with training load",
        ],
        "missed_dose_rule": CONFIRM_WITH_DOCTOR,
        "late_window_hours": None,
    },
    "GHK-Cu": {
        "what": "Copper-binding tripeptide used off-label for skin, connective-tissue, and wound-healing support.",
        "mechanism": "Naturally occurring copper-peptide complex that upregulates collagen/elastin synthesis and has antioxidant and anti-inflammatory activity.",
        "effects": [
            "Skin and connective-tissue support",
            "Wound-healing support",
        ],
        "watch_fors": [
            "Skin irritation at the application/injection site",
            "Any unusual skin discoloration",
        ],
        "missed_dose_rule": CONFIRM_WITH_DOCTOR,
        "late_window_hours": None,
    },
    "Tesamorelin": {
        "what": "Growth-hormone-releasing hormone (GHRH) analog used off-label to raise endogenous growth hormone.",
        "mechanism": "Stimulates the pituitary to release growth hormone in a pulsatile pattern; must be dosed fasted since food blunts the GH pulse.",
        "effects": [
            "Raises endogenous growth hormone / IGF-1",
            "May support recovery and body composition over time",
        ],
        "watch_fors": [
            "Injection-site reaction",
            "Joint stiffness or swelling (GH-related fluid retention)",
            "Blood sugar changes — GH can transiently raise glucose",
        ],
        "missed_dose_rule": CONFIRM_WITH_DOCTOR,
        "late_window_hours": None,
    },
}


def _parse_time(hhmm: str):
    return datetime.strptime(hhmm, "%H:%M").time()


def _fmt_mg(mg: float) -> str:
    return f"{mg:g}"


# ── Escalation derivation ────────────────────────────────────────────────

def _retatrutide_escalations(dose_rows: list) -> list[dict]:
    """Internal: full escalation event records, sorted by date —
    [{"date", "kind": "dose"|"frequency", "detail"}] — per the two-event
    decomposition documented in the module docstring.

    Held doses (dose_mg <= 0) are excluded entirely before any max/count
    tracking happens, whether represented by omitting the row or by a
    dose_mg=0 row, so a hold can never fabricate or suppress an event.
    """
    totals: dict = defaultdict(float)
    for r in dose_rows:
        if r.compound == "Retatrutide" and r.dose_mg > 0:
            totals[r.date] += r.dose_mg
    dates = sorted(totals)
    if not dates:
        return []

    def trailing_count(d):
        return sum(1 for dd in dates if 0 <= (d - dd).days <= 6)

    events = []
    running_max_dose = None
    running_max_count = None
    for d in dates:
        mg = totals[d]
        count = trailing_count(d)

        if running_max_dose is not None and mg > running_max_dose:
            events.append({
                "date": d,
                "kind": "dose",
                "detail": f"{_fmt_mg(running_max_dose)}mg → {_fmt_mg(mg)}mg per dose",
            })

        if running_max_count is not None and count > running_max_count:
            dose_not_reduced = mg >= (running_max_dose if running_max_dose is not None else mg)
            if dose_not_reduced:
                events.append({
                    "date": d,
                    "kind": "frequency",
                    "detail": f"{running_max_count}×/wk → {count}×/wk",
                })

        running_max_dose = mg if running_max_dose is None else max(running_max_dose, mg)
        running_max_count = count if running_max_count is None else max(running_max_count, count)

    events.sort(key=lambda e: e["date"])
    return events


def escalation_dates(dose_rows: list) -> list:
    """Sorted, deduped union of dose-step and frequency-step dates
    (derived from rows, never hardcoded). Defensively filters to
    compound == "Retatrutide" — safe to call with a full, mixed-compound
    dose list."""
    return sorted({e["date"] for e in _retatrutide_escalations(dose_rows)})


def escalation_window(dose_rows: list, today, days: int = 7) -> bool:
    """True if an escalation date falls within [today, today+days)."""
    horizon = today + timedelta(days=days)
    return any(today <= d < horizon for d in escalation_dates(dose_rows))


def next_escalation(dose_rows: list, today) -> Optional[dict]:
    """The next escalation event {"date", "kind", "detail"} with
    date >= today, or None if there isn't one. If a date carries both a
    dose-step and a frequency-step, the dose-step is reported (dose-steps
    are evaluated first within a date in `_retatrutide_escalations`)."""
    for e in _retatrutide_escalations(dose_rows):
        if e["date"] >= today:
            return dict(e)
    return None


# ── Adherence ─────────────────────────────────────────────────────────

def adherence_7d(dose_rows: list, today) -> dict:
    """7-day adherence window [today-6, today]. A row counts as TAKEN iff
    `taken_at is not None` (never inferred from taken_at's own date — see
    module docstring). "late" subclassifies already-taken rows whose
    taken_at date (UTC) is after the row's own date. "missed" = scheduled,
    untaken, and strictly in the past (today's untaken doses aren't missed
    yet)."""
    start = today - timedelta(days=6)
    window_rows = [r for r in dose_rows if start <= r.date <= today]
    scheduled = len(window_rows)
    taken = sum(1 for r in window_rows if r.taken_at is not None)
    late = sum(1 for r in window_rows if r.taken_at is not None and r.taken_at.date() > r.date)
    missed = [{"date": r.date, "compound": r.compound}
              for r in window_rows if r.taken_at is None and r.date < today]
    pct = round(taken / scheduled * 100, 1) if scheduled else None
    return {"pct": pct, "taken": taken, "late": late, "scheduled": scheduled, "missed": missed}


# ── Vial mg-walk ──────────────────────────────────────────────────────

def vial_status(vials: list, dose_rows: list, today, lead_time_days: int = 7) -> list[dict]:
    """Per-vial inventory projection via the mg walk (spec §1):

    - mg_used = sum of dose_mg for TAKEN rows whose date falls in the
      vial's attribution window (window = [reconstituted_on, next same-
      compound vial's reconstituted_on) — unbounded above if there's no
      later vial for that compound).
    - mg_remaining = total_mg - mg_used.
    - Walk FUTURE scheduled (untaken, date >= today) doses for that
      compound within the window, in date+time order, accumulating a
      running total; the first dose whose accumulated total exceeds
      mg_remaining is the mg-based runout.
    - effective runout = min(mg-based runout, reconstituted_on +
      expiry_days) — whichever comes first actually ends the vial's life.
      This is what's reported as `runout_date`.
    - reorder_by = effective runout - lead_time_days; reorder_flag = today
      >= reorder_by.
    - doses_left = count of future doses strictly before the effective
      runout (so an early expiry correctly caps how many "future" doses
      this vial can actually still deliver, even if mg alone would have
      covered more of them).

    Returns one dict per input vial, in the SAME ORDER as `vials`.
    """
    by_compound = defaultdict(list)
    for v in vials:
        by_compound[v.compound].append(v)
    for lst in by_compound.values():
        lst.sort(key=lambda v: v.reconstituted_on)

    windows = {}
    for compound, lst in by_compound.items():
        for i, v in enumerate(lst):
            start = v.reconstituted_on
            end = lst[i + 1].reconstituted_on if i + 1 < len(lst) else None
            windows[id(v)] = (start, end)

    results = []
    for vial in vials:
        start, end = windows[id(vial)]
        compound_doses = [r for r in dose_rows if r.compound == vial.compound]

        def in_window(r):
            if r.date < start:
                return False
            if end is not None and r.date >= end:
                return False
            return True

        mg_used = sum(r.dose_mg for r in compound_doses if r.taken_at is not None and in_window(r))
        mg_remaining = vial.total_mg - mg_used

        future = sorted(
            (r for r in compound_doses if r.taken_at is None and r.date >= today and in_window(r)),
            key=lambda r: (r.date, r.time),
        )

        cumulative = 0.0
        runout_date_mg = None
        for r in future:
            cumulative += r.dose_mg
            if cumulative > mg_remaining:
                runout_date_mg = r.date
                break

        expiry_date = vial.reconstituted_on + timedelta(days=vial.expiry_days)
        effective_runout = min(runout_date_mg, expiry_date) if runout_date_mg is not None else expiry_date

        doses_left = sum(1 for r in future if r.date < effective_runout)

        reorder_by = effective_runout - timedelta(days=lead_time_days)
        reorder_flag = today >= reorder_by

        results.append({
            "compound": vial.compound,
            "mg_remaining": round(mg_remaining, 4),
            "doses_left": doses_left,
            "runout_date": effective_runout,
            "reorder_by": reorder_by,
            "reorder_flag": reorder_flag,
        })
    return results


# ── Missed-dose action classification ────────────────────────────────

def missed_line(dose_rows: list, today, rules: Optional[dict] = None) -> list[dict]:
    """One entry per untaken, past-due dose row: {"date", "compound",
    "rule", "action"}.

    action:
      - "retro_mark" — row.date == today-1 (yesterday). Always allowed,
        ungated by late_window_hours.
      - "taken_late" — row.date is OLDER than yesterday AND the elapsed
        time since the row's scheduled datetime (date+time) is within the
        compound's late_window_hours. Ships as None for every compound (see
        PROTOCOL_COMPOUNDS), so this branch is denied by default until a
        doctor-confirmed window is configured.
      - "none" — everything else.

    Elapsed time is measured from the row's scheduled datetime to midnight
    of `today` (a conservative floor: the actual current time later in the
    day would only shorten, never extend, the remaining window).

    `rules` defaults to PROTOCOL_COMPOUNDS; pass a custom {compound: {...}}
    dict (e.g. with a non-None late_window_hours) to test/exercise the
    "taken_late" branch without mutating global state.
    """
    if rules is None:
        rules = PROTOCOL_COMPOUNDS
    yesterday = today - timedelta(days=1)
    now_floor = datetime.combine(today, _time.min)

    out = []
    for r in dose_rows:
        if r.taken_at is not None:
            continue
        if r.date >= today:
            continue  # not due/missed yet

        compound_rule = rules.get(r.compound, {})
        rule_text = compound_rule.get("missed_dose_rule", CONFIRM_WITH_DOCTOR)
        late_window_hours = compound_rule.get("late_window_hours")

        if r.date == yesterday:
            action = "retro_mark"
        else:
            scheduled_dt = datetime.combine(r.date, _parse_time(r.time))
            hours_elapsed = (now_floor - scheduled_dt).total_seconds() / 3600.0
            if late_window_hours is not None and 0 <= hours_elapsed <= late_window_hours:
                action = "taken_late"
            else:
                action = "none"

        out.append({"date": r.date, "compound": r.compound, "rule": rule_text, "action": action})

    out.sort(key=lambda d: (d["date"], d["compound"]))
    return out


# ── Fasted dose lookup ────────────────────────────────────────────────

def fasted_dose_time(dose_rows: list, on_date) -> Optional[str]:
    """Time string ("HH:MM") of a dose scheduled at or after 21:00 on
    `on_date`, else None. HH:MM zero-padded strings compare correctly as
    plain strings, so no time parsing is needed."""
    for r in dose_rows:
        if r.date == on_date and r.time >= "21:00":
            return r.time
    return None
