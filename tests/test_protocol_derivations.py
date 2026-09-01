"""protocol.py — pure peptide-protocol derivations.

Covers: compounds reference shape, adherence counting (incl. date-authority /
DST-irrelevance), escalation-date derivation from the real CSV, vial mg-walk
(single + multi-vial attribution, expiry-beats-mg, mid-vial dose step-down),
missed-dose action classification, and fasted-dose-time lookup.
"""
import csv
from datetime import date, datetime, timezone
from types import SimpleNamespace as Row


def _csv_rows():
    out = []
    with open("peptide_protocol.csv") as f:
        for r in csv.DictReader(f):
            y, m, d = map(int, r["Date"].split("-"))
            out.append(Row(date=date(y, m, d), time=r["Time"], compound=r["Compound"],
                           dose_mg=float(r["Dose_mg"]), taken_at=None))
    return out


# ── PROTOCOL_COMPOUNDS shape ─────────────────────────────────────────────

def test_protocol_compounds_has_all_seven_with_required_keys():
    from protocol import PROTOCOL_COMPOUNDS, CONFIRM_WITH_DOCTOR
    expected = {"Enclomiphene", "BPC-157", "KPV", "Retatrutide", "TB-500",
                "GHK-Cu", "Tesamorelin", "Cagrilintide"}
    assert set(PROTOCOL_COMPOUNDS.keys()) == expected
    for name, c in PROTOCOL_COMPOUNDS.items():
        assert set(c.keys()) == {"what", "mechanism", "effects", "watch_fors",
                                  "missed_dose_rule", "late_window_hours"}
        assert isinstance(c["what"], str) and c["what"]
        assert isinstance(c["mechanism"], str) and c["mechanism"]
        assert isinstance(c["effects"], list) and c["effects"]
        assert isinstance(c["watch_fors"], list) and c["watch_fors"]
        assert c["missed_dose_rule"] == CONFIRM_WITH_DOCTOR
        assert c["late_window_hours"] is None


def test_protocol_compounds_carries_no_schedule_text():
    from protocol import PROTOCOL_COMPOUNDS
    banned = ("mg", "twice", "weekly", "daily", "am", "pm", "cadence",
              "schedule", "monday", "thursday")
    for name, c in PROTOCOL_COMPOUNDS.items():
        blob = " ".join([c["what"], c["mechanism"]] + c["effects"] + c["watch_fors"]).lower()
        for word in banned:
            assert word not in blob.split(), f"{name}: schedule-ish word {word!r} leaked into reference text"


# ── escalation_dates: ground truth from the real CSV ─────────────────────

def test_escalation_dates_derived_from_csv():
    from protocol import escalation_dates
    dates = escalation_dates([r for r in _csv_rows() if r.compound == "Retatrutide"])
    assert dates == [date(2026, 8, 24), date(2026, 9, 10), date(2026, 9, 21)]


def test_escalation_dates_union_over_titrating_compounds():
    """The FULL mixed-compound CSV yields Retatrutide's 3 steps PLUS
    Cagrilintide's 4 (Aug 29 1×→2×/wk, Sep 2, Sep 16, Oct 14) — S011: the
    detector used to be Retatrutide-only and these were invisible. Compounds
    that never titrate (BPC, KPV, TB-500, Enclomiphene) contribute nothing."""
    from protocol import escalation_dates, escalation_events
    dates = escalation_dates(_csv_rows())
    assert dates == [date(2026, 8, 24), date(2026, 8, 29), date(2026, 9, 2),
                     date(2026, 9, 10), date(2026, 9, 16), date(2026, 9, 21), date(2026, 10, 14)]
    by_date = {e["date"]: e for e in escalation_events(_csv_rows())}
    assert by_date[date(2026, 8, 29)]["compound"] == "Cagrilintide"
    assert by_date[date(2026, 8, 29)]["kind"] == "frequency"
    assert by_date[date(2026, 9, 2)]["detail"] == "0.3mg → 0.6mg per dose"


def test_escalation_dates_order_independent():
    from protocol import escalation_dates
    rows = [r for r in _csv_rows() if r.compound == "Retatrutide"]
    import random
    shuffled = rows[:]
    random.Random(7).shuffle(shuffled)
    assert escalation_dates(shuffled) == escalation_dates(rows)


def test_next_escalation_before_first_boundary_is_dose_step():
    from protocol import next_escalation
    rows = [r for r in _csv_rows() if r.compound == "Retatrutide"]
    n = next_escalation(rows, today=date(2026, 8, 1))
    assert n == {"date": date(2026, 8, 24), "kind": "dose", "detail": "2mg → 3mg per dose", "compound": "Retatrutide"}


def test_next_escalation_between_boundaries_is_frequency_step():
    from protocol import next_escalation
    rows = [r for r in _csv_rows() if r.compound == "Retatrutide"]
    n = next_escalation(rows, today=date(2026, 8, 25))
    assert n == {"date": date(2026, 9, 10), "kind": "frequency", "detail": "1×/wk → 2×/wk",
                 "compound": "Retatrutide"}


def test_next_escalation_on_boundary_date_is_inclusive_dose_step():
    from protocol import next_escalation
    rows = [r for r in _csv_rows() if r.compound == "Retatrutide"]
    n = next_escalation(rows, today=date(2026, 9, 21))
    assert n == {"date": date(2026, 9, 21), "kind": "dose", "detail": "3mg → 4mg per dose",
                 "compound": "Retatrutide"}


def test_next_escalation_after_last_boundary_is_none():
    from protocol import next_escalation
    rows = [r for r in _csv_rows() if r.compound == "Retatrutide"]
    assert next_escalation(rows, today=date(2026, 9, 22)) is None


def test_escalation_window_true_when_boundary_within_days():
    from protocol import escalation_window
    rows = [r for r in _csv_rows() if r.compound == "Retatrutide"]
    assert escalation_window(rows, today=date(2026, 8, 20), days=7) is True


def test_escalation_window_false_when_no_boundary_within_days():
    from protocol import escalation_window
    rows = [r for r in _csv_rows() if r.compound == "Retatrutide"]
    assert escalation_window(rows, today=date(2026, 8, 25), days=7) is False


# ── escalation_dates: hold-robustness (fix round 1) ───────────────────────

def test_escalation_dates_robust_to_held_dose_row_removed():
    """Removing the 2026-09-24 row entirely (held for GI/travel) must NOT
    change the escalation dates — no phantom on a later date where the
    rolling window merely 'catches up'."""
    from protocol import escalation_dates
    rows = [r for r in _csv_rows() if r.compound == "Retatrutide" and r.date != date(2026, 9, 24)]
    assert escalation_dates(rows) == [date(2026, 8, 24), date(2026, 9, 10), date(2026, 9, 21)]


def test_escalation_dates_robust_to_held_dose_zero_mg():
    """Same hold, represented by KEEPING the row but zeroing dose_mg
    (instead of omitting it) — must produce the identical result."""
    from protocol import escalation_dates
    rows = [r for r in _csv_rows() if r.compound == "Retatrutide"]
    for r in rows:
        if r.date == date(2026, 9, 24):
            r.dose_mg = 0.0
    assert escalation_dates(rows) == [date(2026, 8, 24), date(2026, 9, 10), date(2026, 9, 21)]


def test_escalation_dates_two_back_to_back_dose_steps_both_fire():
    """Two genuine, independent dose-steps (3mg->4mg, then 4mg->5mg) only
    3 days apart must BOTH be reported as distinct dates — never merged
    into a single date the way the old rising-run trailing-sum definition
    would have collapsed them."""
    from protocol import escalation_dates
    rows = [
        Row(date=date(2030, 1, 1), time="07:00", compound="Retatrutide", dose_mg=2.0, taken_at=None),
        Row(date=date(2030, 3, 1), time="07:00", compound="Retatrutide", dose_mg=3.0, taken_at=None),
        Row(date=date(2030, 5, 1), time="07:00", compound="Retatrutide", dose_mg=4.0, taken_at=None),
        Row(date=date(2030, 5, 4), time="07:00", compound="Retatrutide", dose_mg=5.0, taken_at=None),
    ]
    dates = escalation_dates(rows)
    assert date(2030, 5, 1) in dates
    assert date(2030, 5, 4) in dates
    assert dates == [date(2030, 3, 1), date(2030, 5, 1), date(2030, 5, 4)]


def test_escalation_dates_frequency_step_not_flagged_on_dose_reduction():
    """A frequency bump that coincides with a dose REDUCTION (e.g. a
    loading->maintenance step-down going twice-weekly to compensate) must
    NOT be flagged as an escalation — exposure isn't rising overall."""
    from protocol import escalation_dates
    rows = [
        Row(date=date(2030, 1, 1), time="07:00", compound="Retatrutide", dose_mg=4.0, taken_at=None),
        Row(date=date(2030, 1, 8), time="07:00", compound="Retatrutide", dose_mg=4.0, taken_at=None),
        # frequency jumps from 1x/wk to 2x/wk here, but dose_mg DROPS to 2.0 (below running max 4.0)
        Row(date=date(2030, 1, 11), time="07:00", compound="Retatrutide", dose_mg=2.0, taken_at=None),
        Row(date=date(2030, 1, 15), time="07:00", compound="Retatrutide", dose_mg=2.0, taken_at=None),
    ]
    assert escalation_dates(rows) == []


# ── current_dose_mg: held-dose-safe "what's the current dose" lookup ──────

def test_current_dose_mg_excludes_held_dose_reports_prior_real_dose():
    """3mg -> 4mg step, then a HELD (0mg) row after it -> current dose is
    still 4.0, not 0.0. This is the exact bug this helper exists to fix:
    the caller must never read a hold as a new (zero) dose level."""
    from protocol import current_dose_mg
    rows = [
        Row(date=date(2026, 9, 7), time="07:00", compound="Retatrutide", dose_mg=3.0, taken_at=None),
        Row(date=date(2026, 9, 21), time="07:00", compound="Retatrutide", dose_mg=4.0, taken_at=None),
        Row(date=date(2026, 9, 28), time="07:00", compound="Retatrutide", dose_mg=0.0, taken_at=None),
    ]
    assert current_dose_mg(rows, date(2026, 9, 29)) == 4.0


def test_current_dose_mg_all_held_since_returns_prior_real_dose():
    """Multiple consecutive holds after the last real dose must still
    resolve to that last real dose, however many holds intervene."""
    from protocol import current_dose_mg
    rows = [
        Row(date=date(2026, 9, 7), time="07:00", compound="Retatrutide", dose_mg=3.0, taken_at=None),
        Row(date=date(2026, 9, 21), time="07:00", compound="Retatrutide", dose_mg=4.0, taken_at=None),
        Row(date=date(2026, 9, 28), time="07:00", compound="Retatrutide", dose_mg=0.0, taken_at=None),
        Row(date=date(2026, 10, 5), time="07:00", compound="Retatrutide", dose_mg=0.0, taken_at=None),
    ]
    assert current_dose_mg(rows, date(2026, 10, 6)) == 4.0


def test_current_dose_mg_no_rows_for_compound_returns_none():
    from protocol import current_dose_mg
    rows = [
        Row(date=date(2026, 9, 7), time="07:00", compound="BPC-157", dose_mg=0.25, taken_at=None),
    ]
    assert current_dose_mg(rows, date(2026, 9, 8)) is None
    assert current_dose_mg([], date(2026, 9, 8)) is None


def test_current_dose_mg_ignores_rows_after_today():
    """A future dose row must not leak into 'current' — only date <= today
    counts."""
    from protocol import current_dose_mg
    rows = [
        Row(date=date(2026, 9, 7), time="07:00", compound="Retatrutide", dose_mg=3.0, taken_at=None),
        Row(date=date(2026, 9, 21), time="07:00", compound="Retatrutide", dose_mg=4.0, taken_at=None),
    ]
    assert current_dose_mg(rows, date(2026, 9, 14)) == 3.0


def test_current_dose_mg_only_a_held_row_ever_returns_none():
    """If the ONLY row for a compound on/before today is a hold, there is
    no real dose to report — None, not 0.0."""
    from protocol import current_dose_mg
    rows = [
        Row(date=date(2026, 9, 7), time="07:00", compound="Retatrutide", dose_mg=0.0, taken_at=None),
    ]
    assert current_dose_mg(rows, date(2026, 9, 8)) is None


def test_current_dose_mg_defaults_to_retatrutide_and_respects_compound_arg():
    from protocol import current_dose_mg
    rows = [
        Row(date=date(2026, 9, 7), time="07:00", compound="Retatrutide", dose_mg=3.0, taken_at=None),
        Row(date=date(2026, 9, 7), time="07:00", compound="TB-500", dose_mg=2.5, taken_at=None),
    ]
    assert current_dose_mg(rows, date(2026, 9, 8)) == 3.0
    assert current_dose_mg(rows, date(2026, 9, 8), compound="TB-500") == 2.5


# ── adherence_7d ───────────────────────────────────────────────────────

def test_adherence_taken_at_next_day_utc_still_counts_for_own_date():
    from protocol import adherence_7d
    # 22:05 Pacific on Oct 5 == 05:05 UTC Oct 6 — must count as taken ON Oct 5
    row = Row(date=date(2026, 10, 5), time="22:00", compound="Tesamorelin",
              dose_mg=2.0, taken_at=datetime(2026, 10, 6, 5, 5, tzinfo=timezone.utc))
    a = adherence_7d([row], today=date(2026, 10, 6))
    assert a["taken"] == 1 and a["missed"] == []


def test_adherence_counts_taken_late_missed_and_pct():
    from protocol import adherence_7d
    today = date(2026, 9, 5)
    rows = [
        # taken on time
        Row(date=date(2026, 9, 1), time="07:00", compound="Enclomiphene", dose_mg=6.25,
            taken_at=datetime(2026, 9, 1, 15, 0, tzinfo=timezone.utc)),
        # taken on time — 21:00-PDT-equivalent evening tap crosses UTC midnight
        # (taken_at date == row date + 1); the 1-day grace boundary keeps this
        # on-time, not late (see is_late()).
        Row(date=date(2026, 9, 2), time="07:00", compound="Enclomiphene", dose_mg=6.25,
            taken_at=datetime(2026, 9, 3, 4, 0, tzinfo=timezone.utc)),
        # missed (untaken, in the past)
        Row(date=date(2026, 9, 3), time="07:00", compound="Enclomiphene", dose_mg=6.25,
            taken_at=None),
        # scheduled today, untaken — NOT missed yet
        Row(date=date(2026, 9, 5), time="07:00", compound="Enclomiphene", dose_mg=6.25,
            taken_at=None),
    ]
    a = adherence_7d(rows, today=today)
    assert a["scheduled"] == 4
    assert a["taken"] == 2
    assert a["late"] == 0
    assert a["missed"] == [{"date": date(2026, 9, 3), "compound": "Enclomiphene"}]
    assert a["pct"] == 50.0


def test_adherence_late_boundary_same_day_evening_tap_after_1700pt_not_late():
    """(a) 22:05 PT tap on the dose's own date (05:05 UTC next day) must NOT
    be late — this is the every-night Tesamorelin case."""
    from protocol import adherence_7d
    row = Row(date=date(2026, 10, 5), time="22:00", compound="Tesamorelin",
              dose_mg=2.0, taken_at=datetime(2026, 10, 6, 5, 5, tzinfo=timezone.utc))
    a = adherence_7d([row], today=date(2026, 10, 6))
    assert a["late"] == 0


def test_adherence_late_boundary_next_morning_retro_mark_not_late():
    """(b) A next-morning retro-mark (taken_at date == row.date + 1, UTC)
    must NOT be late — the spec counts these as on-time."""
    from protocol import adherence_7d
    row = Row(date=date(2026, 9, 1), time="07:00", compound="Enclomiphene",
              dose_mg=6.25, taken_at=datetime(2026, 9, 2, 14, 0, tzinfo=timezone.utc))
    a = adherence_7d([row], today=date(2026, 9, 2))
    assert a["late"] == 0


def test_adherence_late_boundary_genuine_late_path_take_is_late():
    """(c) A genuine /late-path take (taken_at date == row.date + 3, UTC —
    i.e. the doctor-gated >=2-days-old territory) IS late."""
    from protocol import adherence_7d
    row = Row(date=date(2026, 9, 1), time="07:00", compound="Enclomiphene",
              dose_mg=6.25, taken_at=datetime(2026, 9, 4, 14, 0, tzinfo=timezone.utc))
    a = adherence_7d([row], today=date(2026, 9, 4))
    assert a["late"] == 1


def test_adherence_pct_none_when_nothing_scheduled():
    from protocol import adherence_7d
    a = adherence_7d([], today=date(2026, 9, 5))
    assert a["pct"] is None
    assert a["scheduled"] == 0
    assert a["taken"] == 0
    assert a["late"] == 0
    assert a["missed"] == []


def test_adherence_ignores_rows_outside_the_7day_window():
    from protocol import adherence_7d
    today = date(2026, 9, 5)
    rows = [
        Row(date=date(2026, 8, 29), time="07:00", compound="BPC-157", dose_mg=0.25, taken_at=None),  # 7 days back, outside [today-6, today]
        Row(date=date(2026, 8, 30), time="07:00", compound="BPC-157", dose_mg=0.25,
            taken_at=datetime(2026, 8, 30, 15, 0, tzinfo=timezone.utc)),  # today-6, inside
    ]
    a = adherence_7d(rows, today=today)
    assert a["scheduled"] == 1
    assert a["taken"] == 1


def test_adherence_window_spanning_us_dst_fallback_nov1_uses_dates_only():
    """Sun 2026-11-01 is the US DST fall-back date. adherence_7d must produce
    the same counts it would for any other week because it NEVER converts
    taken_at to local time or does any tz arithmetic — it only ever compares
    plain `date` objects (row.date, and taken_at.date() for late-subclassing).
    This test proves DST is a non-event for this module."""
    from protocol import adherence_7d
    today = date(2026, 11, 1)  # window = Oct26..Nov1, straddles the DST boundary
    rows = [
        Row(date=date(2026, 10, 26), time="07:00", compound="Enclomiphene", dose_mg=6.25,
            taken_at=datetime(2026, 10, 26, 14, 0, tzinfo=timezone.utc)),
        Row(date=date(2026, 10, 31), time="22:00", compound="Tesamorelin", dose_mg=2.0,
            taken_at=None),  # missed
        Row(date=date(2026, 11, 1), time="22:00", compound="Tesamorelin", dose_mg=2.0,
            taken_at=None),  # scheduled today, not missed yet
    ]
    a = adherence_7d(rows, today=today)
    assert a["scheduled"] == 3
    assert a["taken"] == 1
    assert a["missed"] == [{"date": date(2026, 10, 31), "compound": "Tesamorelin"}]


# ── vial_status: mg walk ─────────────────────────────────────────────────

def test_vial_walk_across_escalations():
    from protocol import vial_status
    vial = Row(compound="Retatrutide", total_mg=20.0,
               reconstituted_on=date(2026, 8, 10), expiry_days=90)
    doses = [r for r in _csv_rows() if r.compound == "Retatrutide"]
    for r in doses[:2]:  # Aug 10 + Aug 17 taken (2mg each -> 4mg used)
        r.taken_at = datetime(r.date.year, r.date.month, r.date.day, 14, tzinfo=timezone.utc)
    s = vial_status([vial], doses, today=date(2026, 8, 18))[0]
    assert s["compound"] == "Retatrutide"
    assert s["mg_remaining"] == 16.0
    # walk: Aug24 3, Aug31 3, Sep7 3, Sep10 3 = 12 -> covered; Sep14 3 -> 15 <= 16 covered; Sep17 3 -> 18 > 16 NOT covered
    assert s["doses_left"] == 5
    assert s["runout_date"] == date(2026, 9, 17)
    assert s["reorder_by"] == date(2026, 9, 10)  # runout - 7 lead days
    assert s["reorder_flag"] is False  # today (Aug18) < reorder_by


def test_vial_walk_tb500_dose_step_down_mid_vial():
    """TB-500 steps 2.5mg (loading) -> 2.0mg (maintenance) at Sep 7. The walk
    must use each row's OWN dose_mg, not assume a constant per-dose amount —
    with total_mg=22.0 and 10mg already used, a naive constant-2.5mg walker
    would runout at Sep 7 (doses_left=4); the correct per-row walk covers
    through Sep 7 (2.0mg) and runs out at Sep 14 (doses_left=5)."""
    from protocol import vial_status
    rows = [r for r in _csv_rows() if r.compound == "TB-500"]
    for r in rows:
        if r.date in (date(2026, 8, 10), date(2026, 8, 13), date(2026, 8, 17), date(2026, 8, 20)):
            r.taken_at = datetime(r.date.year, r.date.month, r.date.day, 14, tzinfo=timezone.utc)
    vial = Row(compound="TB-500", total_mg=22.0, reconstituted_on=date(2026, 8, 10), expiry_days=90)
    s = vial_status([vial], rows, today=date(2026, 8, 21))[0]
    assert s["mg_remaining"] == 12.0
    assert s["doses_left"] == 5
    assert s["runout_date"] == date(2026, 9, 14)


def test_vial_walk_bpc157_expiry_beats_mg():
    """Generous mg (100mg vs ~21mg total protocol usage) but a short 14-day
    expiry — the vial expires long before it would ever run dry on mg."""
    from protocol import vial_status
    rows = [r for r in _csv_rows() if r.compound == "BPC-157"]
    vial = Row(compound="BPC-157", total_mg=100.0, reconstituted_on=date(2026, 8, 10), expiry_days=14)
    s = vial_status([vial], rows, today=date(2026, 8, 10))[0]
    assert s["runout_date"] == date(2026, 8, 24)  # expiry, not mg exhaustion
    assert s["doses_left"] == 14  # BPC-157 doses strictly before Aug 24
    assert s["reorder_by"] == date(2026, 8, 17)
    assert s["reorder_flag"] is False


def test_vial_walk_multi_vial_attribution_no_cross_contamination():
    """Two KPV vials: doses before the 2nd vial's reconstituted_on attribute
    to vial 1 only; doses on/after attribute to vial 2 only. Vial 1's future
    list must be EMPTY (all its window doses are in the past relative to
    vial 2's start) — a bug that fails to bound vial 1's window would instead
    walk vial 2's future doses as vial 1's own."""
    from protocol import vial_status
    rows = [r for r in _csv_rows() if r.compound == "KPV"]
    v2_start = date(2026, 9, 16)
    for r in rows:
        if r.date < v2_start:
            r.taken_at = datetime(r.date.year, r.date.month, r.date.day, 14, tzinfo=timezone.utc)
    vial1 = Row(compound="KPV", total_mg=20.0, reconstituted_on=date(2026, 8, 10), expiry_days=90)
    vial2 = Row(compound="KPV", total_mg=6.0, reconstituted_on=v2_start, expiry_days=90)
    results = vial_status([vial1, vial2], rows, today=v2_start, lead_time_days=7)
    assert len(results) == 2
    s1, s2 = results[0], results[1]  # vial_status preserves input vial order
    assert s1["mg_remaining"] == 4.0  # 20 - 16mg used (16 doses x 1mg before Sep16)
    assert s1["doses_left"] == 0      # nothing left in vial 1's own window
    assert s2["mg_remaining"] == 6.0  # nothing taken yet from vial 2
    assert s2["doses_left"] == 6
    assert s2["runout_date"] == date(2026, 9, 30)


# ── missed_line: action classification ────────────────────────────────

def test_missed_line_yesterday_is_retro_mark_regardless_of_window():
    from protocol import missed_line
    today = date(2026, 9, 10)
    rows = [Row(date=date(2026, 9, 9), time="07:00", compound="BPC-157", dose_mg=0.25, taken_at=None)]
    out = missed_line(rows, today)
    assert out == [{"date": date(2026, 9, 9), "compound": "BPC-157",
                     "rule": "confirm with your doctor", "action": "retro_mark"}]


def test_missed_line_older_with_default_null_window_is_none():
    from protocol import missed_line
    today = date(2026, 9, 10)
    rows = [Row(date=date(2026, 9, 7), time="07:00", compound="BPC-157", dose_mg=0.25, taken_at=None)]
    out = missed_line(rows, today)
    assert out[0]["action"] == "none"


def test_missed_line_older_within_override_window_is_taken_late():
    from protocol import missed_line
    today = date(2026, 9, 1)
    rows = [Row(date=date(2026, 8, 29), time="07:00", compound="BPC-157", dose_mg=0.25, taken_at=None)]
    custom_rules = {"BPC-157": {"missed_dose_rule": "confirm with your doctor", "late_window_hours": 96}}
    out = missed_line(rows, today, rules=custom_rules)
    assert out[0]["action"] == "taken_late"


def test_missed_line_older_outside_override_window_is_none():
    from protocol import missed_line
    today = date(2026, 9, 1)
    rows = [Row(date=date(2026, 8, 20), time="07:00", compound="BPC-157", dose_mg=0.25, taken_at=None)]
    custom_rules = {"BPC-157": {"missed_dose_rule": "confirm with your doctor", "late_window_hours": 96}}
    out = missed_line(rows, today, rules=custom_rules)
    assert out[0]["action"] == "none"


def test_missed_line_excludes_taken_and_not_yet_due_rows():
    from protocol import missed_line
    today = date(2026, 9, 10)
    rows = [
        Row(date=date(2026, 9, 9), time="07:00", compound="BPC-157", dose_mg=0.25,
            taken_at=datetime(2026, 9, 9, 14, 0, tzinfo=timezone.utc)),  # taken, excluded
        Row(date=date(2026, 9, 10), time="07:00", compound="BPC-157", dose_mg=0.25, taken_at=None),  # today, not due yet
    ]
    out = missed_line(rows, today)
    assert out == []


# ── fasted_dose_time ──────────────────────────────────────────────────

def test_fasted_dose_time_from_real_csv():
    from protocol import fasted_dose_time
    rows = _csv_rows()
    assert fasted_dose_time(rows, date(2026, 10, 5)) == "22:00"


def test_fasted_dose_time_none_when_nothing_at_or_after_21():
    from protocol import fasted_dose_time
    rows = _csv_rows()
    assert fasted_dose_time(rows, date(2026, 8, 10)) is None  # only 07:00 doses that day


def test_fasted_dose_time_boundary_exactly_21_00_counts():
    from protocol import fasted_dose_time
    rows = [Row(date=date(2026, 9, 1), time="21:00", compound="Tesamorelin", dose_mg=2.0, taken_at=None)]
    assert fasted_dose_time(rows, date(2026, 9, 1)) == "21:00"


def test_fasted_dose_time_20_59_does_not_count():
    from protocol import fasted_dose_time
    rows = [Row(date=date(2026, 9, 1), time="20:59", compound="Tesamorelin", dose_mg=2.0, taken_at=None)]
    assert fasted_dose_time(rows, date(2026, 9, 1)) is None
