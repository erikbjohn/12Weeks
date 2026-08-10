# Peptide Protocol Integration + Block 3 Recomp — Design Spec

**Date:** 2026-08-10
**Status:** Approved approach (A), pending spec review
**Owner:** Erik

## Summary

Erik has a doctor-prescribed 12-week peptide protocol (2026-08-10 → 2026-11-01) in
`peptide_protocol.csv` (repo root; already corrected: enclomiphene 6.25mg, retatrutide
ramp shifted up one step per doctor's flexibility — 2mg wks 1-2, 3mg wks 3-6 with
twice-weekly from Sep 10, 4mg twice-weekly from Sep 21; doctor to confirm).

Block 2 ends today at week 7 (220.0 lbs). **Block 3 starts 2026-08-10, aligned 1:1
with the protocol.** Goal is a **recomp with co-equal lines**: scale 220 → **195 by
Nov 1** on a back-loaded curve, AND lift performance held or progressing. A week where
the scale wins but lifts slide is a bad week.

The protocol becomes first-class app data: tracked on the daily card, witnessed like
workouts/meals, known to the coach, and enforced in meal planning. Everything is
codified — nothing advisory-only (standing rule).

## Protocol contents (imported source of truth: peptide_protocol.csv)

| Compound | Schedule | App-relevant behavior |
|---|---|---|
| Enclomiphene 6.25mg oral | Daily 07:00 w/ breakfast | T support during cut |
| BPC-157 0.25mg inj | Daily 07:00 | Healing/gut |
| KPV 1mg inj | Mon/Wed/Fri 07:00 | Anti-inflammatory; separate syringe from BPC-157 |
| Retatrutide inj | 2mg wks 1-2 → 3mg wks 3-6 (2×/wk from Sep 10) → 4mg 2×/wk from Sep 21 | GLP-1/GIP/glucagon: appetite ↓, RHR ↑, drives the cut math |
| TB-500 | 2.5mg 2×/wk wks 1-4 (loading) → 2mg wkly Mon (maintenance) | Recovery |
| GHK-Cu 0.2mg | ~Every other day 16:00 from wk 5 (Sep 9) | Skin/repair |
| Tesamorelin 2mg | Nightly 22:00 **fasted (2+ hrs post-meal)** from wk 9 (Oct 5) | GH axis; imposes meal-timing rail; sleep quality load-bearing |

Doctor's original file had enclomiphene at 25mg (wrong, per Erik) and a 1-mg-start
retatrutide ramp (doctor said flexible; shifted up, Erik to confirm with doctor).

## 1. Data model

- **`PeptideDose`** table: `id, user_id, date, time, event_type (Oral/Injection),
  compound, dose_mg, syringe_units, site, notes, taken_at (nullable datetime)`.
  One row per scheduled dose event. `taken_at` set by the check-off; date-gated reads
  (a check-off only counts for its own date — same lesson as DayCompletion phantom-done).
- **Import:** admin endpoint `POST /api/admin/import-protocol` (X-Admin-Key), reads the
  CSV, upserts by `(user_id, date, time, compound)`. Idempotent: re-import updates
  dose/site/notes without duplicating rows or clearing existing `taken_at`. Rows in DB
  but no longer in CSV for future dates are deleted (past dates preserved). This is the
  dose-change management path: doctor adjusts → edit CSV → re-import.
- **`PROTOCOL_COMPOUNDS`** static dict (reference knowledge, not a plan — allowed under
  no-static): per compound — what it is, mechanism one-liner, coach-relevant effects
  (appetite, RHR, glucose, recovery), missed-dose rule (see §3), and watch-fors.
  Missed-dose rules start as "ask your doctor" placeholders until Erik fills in the
  doctor's actual guidance; the coach must state the codified rule, never improvise one.
- **`PeptideVial`** table (v1-lite inventory): `compound, reconstituted_on, total_doses,
  doses_used (derived from check-offs), expiry_days, reorder_flag`. Surfaces "N doses
  left / reorder by DATE" on the protocol card. No supplier integration.

## 2. Daily card UI

- New **Protocol** section on today's view: today's doses grouped by time
  (07:00 / 16:00 / 22:00), each showing compound, dose_mg, site, note, and a check-off
  toggle. Large fonts, high contrast, matches existing card sections (readability rule).
- Check-off stamps `taken_at` (server round-trip, persisted — no client-only state).
- Yesterday's unchecked doses show as a single quiet "missed: X, Y" line with the
  codified missed-dose rule per compound — informative, not a nag wall.
- From Oct 5, the 22:00 Tesamorelin row displays its fasting requirement and the
  computed "last meal by 20:00" bound.

## 3. Coach integration

- **Context block** (like cut_status): protocol summary, current retatrutide dose and
  next escalation date, 7-day adherence %, missed doses, vial reorder flags.
- **New tool `get_protocol_status`**: dose history, adherence over a window, upcoming
  schedule changes.
- **CORE_PROMPT additions** (new rule):
  - Coach knows the stack and interprets scale, appetite, GI, and recovery through it
    (e.g., a stall the week of a dose escalation reads differently than week 10).
  - Protein floor is enforced hardest during dose escalations / appetite crashes.
  - **Recomp tripwire:** sustained lift-performance decline (beyond deload weeks) means
    the coach surfaces the cut-speed vs. training-volume trade-off to Erik explicitly.
    Never silently cuts lifting volume (standing rule).
  - Missed doses: state the codified per-compound rule from PROTOCOL_COMPOUNDS; if the
    rule is unfilled, say "confirm with your doctor" — never invent dosing advice
    (no-confabulation rule 20 applies).
  - **Garmin side-effect watch:** coach's weekly read includes RHR/HRV/sleep trends from
    the existing Garmin sync; sustained RHR rise or HRV/sleep degradation is flagged
    against the retatrutide/tesamorelin timeline. Data already flows; this is a read.
  - From Oct 5, stricter time-of-day coaching: late meals/screens blunt the 22:00
    tesamorelin (GH pulse); late check-ins get called out per time-of-day rule.
  - GLP-1 hygiene knowledge: fiber and hydration emphasized; alcohol flagged as hitting
    harder with delayed gastric emptying.
- **Lab reminders:** simple reminder dates (baseline + ~week 8: T/E2, IGF-1, fasting
  glucose/A1c, lipids) stored in AppState-adjacent config; coach mentions when due.
  Scheduling is Erik+doctor's; the app only reminds.

## 4. Meal-plan rail (code-enforced)

- Meal generator reads PeptideDose: on any date with a 22:00 fasted dose, dinner is
  scheduled to END by 20:00. Enforced in code like the volume floor — not a suggestion.
  Card shows the why ("Tesamorelin at 10pm requires 2h fasted").
- Meal plans bias fiber + hydration explicitly while on retatrutide (constipation /
  dehydration are the boring GLP-1 failure modes).
- Protein floor: explicit g/day floor held through appetite suppression; meals sized so
  the floor is reachable even at reduced appetite (protein-dense, smaller volume).

## 5. Block 3 goal — dual-line recomp, back-loaded curve

- **Line 1 (scale):** 220 → 195 by 2026-11-01 on a piecewise curve keyed to the ramp:
  ~1.25 lb/wk weeks 1-2 (2mg), ~2.0 lb/wk weeks 3-6 (3mg), ~2.5 lb/wk weeks 7-12
  (4mg 2×/wk). Sums to ≈25.5 lbs. Dashboard projection and cut_status judge "on pace"
  against THIS curve, never a straight line (a linear line falsely fails weeks 1-2 and
  masks a week-8 stall).
- **Line 2 (lifts):** weekly tonnage and e1RM trend must hold or progress, deload weeks
  (4/8/12) excepted. This is co-equal: the weekly review reports both lines.
- **Recomp measurement:** weekly waist measurement folded into the coach's weekly read
  (body_measurements already exists); day-0 baseline (photos and/or DEXA) is on Erik
  this week — the app records whatever he captures. Scale+lifts alone cannot
  distinguish fat loss from muscle loss; waist is the cheap third signal.
- Gluten/water guard (C4) carries over unchanged; anchors on de-spiked weight.

## 6. Block 2 → 3 transition (prod ops, reversible)

Same playbook as the block-1→2 transition:
1. Record pre-state row counts for all 22 week-keyed tables (rollback data).
2. Re-stamp block-2 history week += 12 (block-2 weeks 1-7 → 13-19). coach_memory
   excluded — carries across blocks.
3. AppState: start_date = 2026-08-10, current_week = 1; cut anchor = 220.0 with the §5
   curve; block goal = dual-line recomp.
4. Import protocol CSV.
5. Regenerate week 1 via /api/admin/replan-week.
6. Verify SERVED state (no-UI-contradictions rule): today = not_started, week-1 plan
   floor-enforced, runs 7/7, meal plans respect (future) rails, protocol card renders
   today's 4 doses, no block-2 weight drawing a false line.
Rollback: week -= 12 on the 22 tables, restore AppState, delete imported PeptideDose.

## 7. Known-landmine fix in scope

- **Week-12 retest lock bug** (open since June: week-12 retest locks the whole app)
  fires at the END of this block — fix it in this work, not on Nov 1.
- (Second known open item — coach narrating template on unplanned days — is NOT in
  scope here; tracked separately.)

## 8. Testing

- Unit: import idempotency (re-import preserves taken_at, updates doses, deletes only
  future removed rows); curve math (piecewise targets sum and evaluate correctly);
  meal-window rail (dinner ≤ 20:00 iff fasted 22:00 dose); check-off date-gating;
  vial dose-count derivation.
- Coach: context block renders protocol + adherence from real seeded data;
  get_protocol_status returns real rows; missed-dose response cites codified rule;
  prompt-rule regression via existing judge cases where applicable.
- UI smoke: protocol section renders today's doses, check-off persists across reload.
- Prod verification through served endpoints (audit what the user SEES), per standing
  rule. No deploy-polling; push and verify once live.

## Out of scope

- Side-effect journaling UI (coach chat captures it conversationally; revisit later).
- Supplier/pharmacy integration for inventory.
- Any medical dosing decisions — dose values come from Erik's doctor via the CSV.
