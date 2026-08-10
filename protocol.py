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
(1x/week -> 2x/week), 2026-09-21 (3mg -> 4mg). A naive "trailing 7-day sum
exceeds the max of all prior trailing sums" definition over-fires: because
the twice-weekly cadence takes two dose-cycles to fully "flush" a stale
lower-dose day out of a 7-day rolling window, the rolling sum keeps
climbing for one extra dose after each frequency change (e.g. after the
Sep-21 3mg->4mg step, the trailing sum rises again on Sep-24 purely because
the window is still digesting the transition, not because a NEW escalation
started). The correct, final definition used here:

  1. Group scheduled retatrutide mg by calendar date (dose dates, sorted).
  2. For each dose date d, compute the trailing 7-day (inclusive) sum of
     scheduled mg over [d-6, d].
  3. Walk the sorted trailing sums and find maximal RUNS of consecutive
     dose dates where each date's trailing sum is strictly greater than the
     previous date's trailing sum ("rising runs").
  4. An escalation date is the FIRST date of each rising run — i.e. the day
     the increased exposure STARTS, not every day until the rolling window
     finishes reflecting the new steady state.

  `weekly_mg_before` = the trailing sum immediately before the run began
  (the last non-rising value). `weekly_mg_after` = the trailing sum at the
  END of the run (the new steady-state weekly total once the window has
  fully caught up). Verified against the shipped CSV: this yields exactly
  [2026-08-24 (2->3), 2026-09-10 (3->6), 2026-09-21 (6->8)] with no false
  positive on 2026-09-24 (which the naive "exceeds all-prior-max" approach
  incorrectly also flags).
"""
from collections import defaultdict
from datetime import datetime, time as _time, timedelta

CONFIRM_WITH_DOCTOR = "confirm with your doctor"

PROTOCOL_COMPOUNDS = {
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


def _parse_time(hhmm):
    return datetime.strptime(hhmm, "%H:%M").time()


# ── Escalation derivation ────────────────────────────────────────────────

def _retatrutide_escalations(dose_rows):
    """Internal: full escalation records [{"date", "weekly_mg_before",
    "weekly_mg_after"}] per the module-docstring definition."""
    totals = defaultdict(float)
    for r in dose_rows:
        if r.compound == "Retatrutide":
            totals[r.date] += r.dose_mg
    dates = sorted(totals)
    if not dates:
        return []

    def trailing_sum(d):
        return sum(mg for dd, mg in totals.items() if 0 <= (d - dd).days <= 6)

    sums = [trailing_sum(d) for d in dates]

    escalations = []
    run_start = None
    for i in range(1, len(dates)):
        rising = sums[i] > sums[i - 1]
        if rising:
            if run_start is None:
                run_start = i
        else:
            if run_start is not None:
                escalations.append({
                    "date": dates[run_start],
                    "weekly_mg_before": sums[run_start - 1],
                    "weekly_mg_after": sums[i - 1],
                })
                run_start = None
    if run_start is not None:
        escalations.append({
            "date": dates[run_start],
            "weekly_mg_before": sums[run_start - 1],
            "weekly_mg_after": sums[-1],
        })
    return escalations


def escalation_dates(dose_rows):
    """Dates where the scheduled weekly retatrutide mg-sum increases
    week-over-week (derived from rows, never hardcoded). Defensively
    filters to compound == "Retatrutide" — safe to call with a full,
    mixed-compound dose list."""
    return [e["date"] for e in _retatrutide_escalations(dose_rows)]


def escalation_window(dose_rows, today, days=7):
    """True if an escalation date falls within [today, today+days)."""
    horizon = today + timedelta(days=days)
    return any(today <= e["date"] < horizon for e in _retatrutide_escalations(dose_rows))


def next_escalation(dose_rows, today):
    """The next escalation date >= today, or None if there isn't one."""
    for e in _retatrutide_escalations(dose_rows):
        if e["date"] >= today:
            return dict(e)
    return None


# ── Adherence ─────────────────────────────────────────────────────────

def adherence_7d(dose_rows, today):
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

def vial_status(vials, dose_rows, today, lead_time_days=7):
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

def missed_line(dose_rows, today, rules=None):
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

def fasted_dose_time(dose_rows, on_date):
    """Time string ("HH:MM") of a dose scheduled at or after 21:00 on
    `on_date`, else None. HH:MM zero-padded strings compare correctly as
    plain strings, so no time parsing is needed."""
    for r in dose_rows:
        if r.date == on_date and r.time >= "21:00":
            return r.time
    return None
