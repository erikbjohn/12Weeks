# Peptide Protocol Integration + Block 3 Recomp — Design Spec (rev 2)

**Date:** 2026-08-10 (rev 2, same day — incorporates all 48 findings from the
adversarially-verified multi-agent review; see
`docs/spec-review-peptide-protocol-2026-08-10.html`)
**Status:** Approved approach (A); rev 2 pending user review
**Owner:** Erik

## Summary

Erik has a doctor-prescribed 12-week peptide protocol (2026-08-10 → 2026-11-01) in
`peptide_protocol.csv` (repo root; corrected: enclomiphene 6.25mg; retatrutide ramp
shifted up one step per doctor's stated flexibility — 2mg wks 1-2, 3mg wks 3-6 with
twice-weekly from Sep 10, 4mg twice-weekly from Sep 21 (wk 7); doctor to confirm).

Block 2 ends today at week 7 (220.0 lbs). **Block 3 starts 2026-08-10, aligned 1:1
with the protocol.** Goal is a **recomp with co-equal lines**: scale 220 → **195.0 by
Nov 1** on a back-loaded curve (§5), AND lift performance held or progressing (§5b).
A week where the scale wins but lifts slide is a bad week.

The protocol becomes first-class app data: tracked on the daily card, witnessed like
workouts/meals, known to the coach, and enforced in meal planning. Everything is
codified — nothing advisory-only (standing rule).

## Protocol contents (imported source of truth: peptide_protocol.csv)

| Compound | Schedule | App-relevant behavior |
|---|---|---|
| Enclomiphene 6.25mg oral | Daily 07:00 w/ breakfast | T support during cut |
| BPC-157 0.25mg inj | Daily 07:00 | Healing/gut |
| KPV 1mg inj | Mon/Wed/Fri 07:00 | Anti-inflammatory; separate syringe from BPC-157 |
| Retatrutide inj | 2mg wks 1-2 → 3mg wks 3-6 (2×/wk Mon+Thu from Sep 10) → 4mg 2×/wk from Sep 21 | GLP-1/GIP/glucagon: appetite ↓, RHR ↑, drives the cut math |
| TB-500 | 2.5mg 2×/wk wks 1-4 (loading) → 2mg wkly Mon (maintenance, from Sep 7) | Recovery |
| GHK-Cu 0.2mg | **Wed/Fri/Sun 16:00**, wks 5-12 (Sep 9 → Nov 1) | Skin/repair |
| Tesamorelin 2mg | Nightly 22:00 **fasted (2+ hrs post-meal)** from wk 9 (Oct 5) | GH axis; meal-timing rail; sleep load-bearing |

This table is orientation only. **Any statement about when a dose is due — coach
context, `get_protocol_status`, card copy — must be derived from imported PeptideDose
rows, never from this prose or from PROTOCOL_COMPOUNDS**, so a doctor's CSV edit can
never create a served contradiction.

Doctor's original file had enclomiphene at 25mg (wrong, per Erik) and a 1-mg-start
ramp (doctor said flexible; shifted up; Erik to confirm with doctor).

## 0. Deploy sequencing (new — precondition for everything below)

All block-3 code (models/migrations, import endpoint, protocol card + API, meal rail,
curve function, detectors, serve-as-user debug endpoint) is **deployed and verified
responding in prod BEFORE any §6 data op runs**. (This is logically forced anyway:
step 4's import endpoint doesn't exist until deployed.)

**Deploy freeze:** no push to main from the moment §6 step 2 begins until §6 step 8
verification completes. The weekly-generation job runs in an in-process daemon thread
(`_GEN_JOBS`); a Render deploy mid-flow kills it between per-domain commits, leaving a
partially written week with no surfaced error (the Planning-Display-Recovery failure).
If the job is interrupted anyway: re-POST `/api/admin/replan-week` for the same week —
the generate-first atomic swap makes re-runs non-destructive. Never hand-patch partial
rows. `generate-status` "done" is NOT evidence of completeness (its fallback passes if
ANY coach lift row exists) — §6 gates on DB/served truth instead.

## 1. Data model

### PeptideDose

`id, user_id, date (Date), time (Text "HH:MM"), event_type (Oral/Injection), compound,
dose_mg, syringe_units, site, notes, taken_at (DateTime UTC, nullable)`.
One row per scheduled dose event.

**Check-off semantics (timezone-explicit):**
- The row's own `date` column is the **sole authority** for which day a dose counts
  toward. Adherence for date D = rows with `date == D AND taken_at IS NOT NULL`.
  Reads NEVER derive the counted day from `taken_at` — 22:00 America/Los_Angeles is
  05:00/06:00 UTC the *next* day, so any `taken_at.date()` comparison marks every
  on-time Tesamorelin check-off (all 28 rows, Oct 5 → Nov 1) as missed. `taken_at`
  is audit trail only.
- **Two distinct recording operations — do not conflate them:**
  1. **Check-off / retro-mark (UNGATED):** the toggle endpoint accepts doses whose
     `date` is user-local today **or yesterday** (retro window = 1 day). A tap on
     yesterday's missed-line entry is a plain retro attribution — it records an
     on-time take that wasn't tapped (covers the after-midnight 22:00 check-off and
     the forgot-to-tap case) and counts as **on-time** for the dose's own date. No
     `late_window_hours` gate applies — this is recording reality, not a dosing
     decision. Preserves the phantom-done lesson: no bulk backfill beyond yesterday.
  2. **Taken-late (DOCTOR-GATED, separate action/endpoint
     `POST /api/protocol/dose/<id>/late`):** for doses older than yesterday but still
     within their compound's `late_window_hours` (measured from scheduled date+time).
     Denied while the rule is the null placeholder — UI/coach say exactly "confirm
     with your doctor". Counts as taken-**late** for the dose's own scheduled date
     (flagged separately in adherence). This is the mechanism for weekly compounds,
     where multi-day late windows are plausible: effective late horizon =
     `late_window_hours`, not the 1-day retro horizon, and the missed-line lookback
     extends to any dose still inside its late window.
  User-local dates via `utils_time` / zoneinfo — never a fixed UTC offset (DST ends
  02:00 Sun 2026-11-01, the final protocol day, which itself has a 22:00 dose).
- **Toggle is bidirectional** (matches the toggleSet convention): one endpoint
  (`POST /api/protocol/dose/<id>/toggle`, `{taken: true|false}`), server round-trip,
  persisted. Un-check nulls `taken_at`; the missed line and adherence % recompute
  from current state at read time, so an un-checked dose reappears as missed —
  intended. Nothing dose-related is ever a stored counter; all counts are derivations.
- Phantom-done cannot structurally recur: check-offs attach to per-date rows, not
  floating week/day slots. Do NOT port the `parse_completion_date` mechanic.

### Import: `POST /api/admin/import-protocol?email=<user>` (X-Admin-Key)

The CSV has no user column; the endpoint takes an explicit `email` parameter.

- **Upsert key: `(user_id, date, compound)`** — `time` is an updatable payload field
  like dose/site/notes, so a doctor's time edit (e.g. GHK-Cu 16:00→18:00) is a plain
  UPDATE that inherently preserves `taken_at`. Verified: every compound appears at
  most once per date across all 292 CSV rows. The importer **validates and rejects**
  any CSV with duplicate `(date, compound)` rows, so the key assumption is enforced,
  not assumed.
- **Immutability rules (mirror the past-week lock):**
  1. Import never updates, inserts, or deletes a row whose `date` < user-local today.
  2. On rows with `taken_at` set: import never deletes, and never updates
     **dose_mg** (the record of what was actually injected is immutable — a dose_mg
     divergence on a taken row is skipped + reported); metadata fields (time, site,
     notes, syringe_units) MAY be updated in place, preserving `taken_at` (a time
     edit on an already-taken dose is harmless bookkeeping, not history rewriting).
     Today's still-untaken rows remain fully editable — the legitimate same-day
     dose-change path.
  3. Deletion (rows in DB, absent from CSV): only where `date` > today, OR
     (`date` == today AND `taken_at IS NULL`).
  4. If the CSV drops a checked-off row for today: keep it, annotate "removed from
     protocol" — never silently contradict the adherence record.
- **Divergence report:** the import response lists every skipped past/taken-row
  divergence — `{skipped: [{date, compound, field, db_value, csv_value}]}` — so
  CSV-vs-history drift is visible, never silent. Genuine historical corrections
  (mis-logged dose) require an explicit `force_past=true` admin flag that logs the diff.
- **Whole-file integrity:** import asserts imported row count == CSV data row count
  (currently 292) and per-compound counts match; a partial import fails loudly.
- **Meal-plan reconciliation (see §4):** after upsert, diff the set of fasted-22:00
  dates within the currently planned window (current week only — future weeks are
  never pre-baked); regenerate affected unlogged days' meal plans (reusing the
  logged-meal/past-day protection from `/api/meals/regenerate`) and report which
  days were regenerated in the import response.
- Idempotent: re-import with an unchanged CSV is a no-op.

### PROTOCOL_COMPOUNDS (static reference dict — allowed under no-static as reference
knowledge, precedent: food_safety_block)

Per compound: what it is, mechanism one-liner, coach-relevant effects (appetite, RHR,
glucose, recovery, escalation-week transients like GI slowdown/water masking), and a
missed-dose rule with BOTH prose and a machine-readable `late_window_hours`.

- **Carries NO schedule/cadence text.** Cadence is always derived from PeptideDose.
- Missed-dose rules ship as `"confirm with your doctor"` placeholders with
  `late_window_hours = null` until Erik enters the doctor's actual guidance; while
  null, late check-off is denied and UI/coach say exactly the canonical string
  "confirm with your doctor" — the coach never improvises dosing advice (rule 20).
- **Card boundary:** card content is limited to CSV-derived fields (compound, dose_mg,
  syringe_units, site, notes, computed fasting bound) plus the per-compound
  missed-dose rule. Mechanism, effects, and watch-fors are **coach-context-only**,
  never rendered in UI.

**Late-take path (codified, not advisory):** the doctor-gated operation defined in
§1's "two distinct recording operations" — applies only to doses older than the 1-day
retro horizon and still inside `late_window_hours`; stamps `taken_at = now (UTC)` on
the PAST dose row (server round-trip), counts taken-late for its own scheduled date.
Outside the window: display-only, permanently missed. Adherence % = (on-time incl.
retro-marked + late-within-window) / scheduled, with late count reported separately
in coach context. Rules implying schedule shifts ("push subsequent doses") route
through CSV edit → re-import for the future rows.

### PeptideVial (mg-based inventory — v1-lite)

`id, user_id, compound, total_mg, reconstituted_on (Date), expiry_days, notes`.
No stored dose counts — a vial holds **mg**, and dose size changes mid-vial
(retatrutide 2→3→4mg draws 20u→30u→40u from the same stock; TB-500 steps 2.5→2mg).

- **Attribution (window-based, no FK):** a dose row belongs to the vial for its
  compound with the greatest `reconstituted_on <= dose.date` (window ends at the next
  vial's `reconstituted_on`). Re-import stays idempotent with zero vial bookkeeping.
- **Derivations (computed at read time):**
  `mg_used` = Σ dose_mg of taken rows in the vial's window;
  `mg_remaining` = total_mg − mg_used;
  run-out date = walk FUTURE scheduled PeptideDose rows in date order, subtracting
  dose_mg until the first uncoverable dose (exact across the Aug 24, Sep 10, Sep 21
  boundaries — no dose-size assumptions);
  effective run-out = min(mg run-out, reconstituted_on + expiry_days) — BPC-157 at
  0.25mg/day hits expiry before exhaustion, so both bounds are needed;
  `reorder_flag` fires when today >= effective run-out − lead_time (default 7 days);
  "N doses left" = count of fully coverable future doses (integer, never fractional).
- Creation: "new vial" action on the protocol card or
  `POST /api/admin/add-vial` (X-Admin-Key).

### LabReminder

`id, user_id, label (Text), due_date (Date), completed_at (DateTime, nullable)`.
Replaces rev-1's nonexistent "AppState-adjacent config". Created at §6 transition:
baseline panel due 2026-08-10, week-8 panel due 2026-09-28 (Monday of week 8, derived
once from start_date at creation, never recomputed). Label carries the panel text
("Week-8 labs: T/E2, IGF-1, fasting glucose/A1c, lipids") — no panel schema; the app
only reminds. Coach context includes reminders where `completed_at IS NULL AND
due_date <= today+7`; completing (card check-off round-trip or
`POST /api/admin/complete-lab-reminder`) stops the mentions permanently.

## 2. Daily card UI

- New **Protocol** section on today's view (served by `GET /api/protocol/today`):
  today's doses grouped by time (07:00 / 16:00 / 22:00), each showing compound,
  dose_mg, syringe_units, site, note, and the check-off toggle. Large fonts, high
  contrast, matches existing card sections (readability rule). Renders **one row per
  PeptideDose row for the date — orals included** (day 0 = 5 rows, see §6).
- Missed-dose line: a single quiet "missed: X, Y" line showing each compound's
  codified missed-dose rule (or the canonical "confirm with your doctor" placeholder,
  rendered as e.g. "missed: KPV — no doctor guidance on file; confirm handling with
  your doctor"). **Yesterday's entries are always tappable ("mark taken" — the
  ungated retro-mark, §1 op 1).** Older entries still inside their compound's
  `late_window_hours` are tappable as "taken late" (§1 op 2, doctor-gated); the
  line's lookback extends to any dose still inside its late window. Informative,
  not a nag wall.
- From Oct 5, the 22:00 Tesamorelin row displays its fasting requirement and the
  computed "last meal by 20:00" bound — **even on days where no meal plan exists**.

## 3. Coach integration

**Context block** (like cut_status), all values derived from PeptideDose rows:
protocol summary, current retatrutide dose, next escalation date, `escalation_window`
flag (true for 7 days after any escalation, with expiry), 7-day adherence % (late
count separate), missed doses, vial reorder flags, due LabReminders, and
PROTOCOL_COMPOUNDS watch-fors for the compounds currently in play (the field's named
consumer — it has no other).

**Escalation (defined):** any scheduled increase in WEEKLY retatrutide mg exposure,
**derived from PeptideDose rows** (week-over-week scheduled-mg-sum increase), never a
hardcoded date list. Under this definition all three dates count: Aug 24 (2→3mg),
Sep 10 (3→6 mg/wk, the frequency doubling — the largest relative jump), Sep 21
(6→8 mg/wk).

**New tool `get_protocol_status`:** dose history, adherence over a window, upcoming
schedule changes (derived, as above).

**CORE_PROMPT additions** (new rule; numbering appended after existing rules,
consistent with rule 20 no-confabulation and rule 21 cut-coaching, which are both
UNCHANGED):
- Coach knows the stack and interprets scale/appetite/GI/recovery through it — but
  **bounded, gluten-guard-style**: anomaly attribution is allowed ONLY when
  `escalation_window` is true AND the effect is listed in PROTOCOL_COMPOUNDS
  watch-fors for the current compound/dose stage. Correlation, never causation: the
  coach cites the dated event ("escalated to 4mg on 9/21; stall overlaps the
  window"), never asserts the drug caused it. Direction is explicit: a stall inside
  an escalation window may be GI/water masking — hold the deficit, expect it to
  clear within the window; a stall at stable dose is a real stall — tighten. Rule 21
  still fires every response: pace named against the §5 curve with the number, one
  cut directive per response; scale silence is never acceptable. Anomalies matching
  no codified watch-for get rule-20 treatment ("that looks wrong / I don't know") —
  never a drug story.
- Protein floor enforced hardest during escalation windows / appetite crashes.
- **Recomp tripwire reacts to the computed flag** (§5b), never to the coach's own
  impression: when `lift_decline_suspected` is true, surface the cut-speed vs
  training-volume trade-off to Erik explicitly, with the underlying numbers. Never
  silently cut lifting volume (standing rule).
- Missed doses: state the codified per-compound rule; if placeholder, say exactly
  "confirm with your doctor".
- **After-10pm carve-out (amends rule 6 in the same change — two prompt rules must
  not contradict):** on any date where PeptideDose has a scheduled dose at or after
  21:00, protocol interactions (check-off, dose/site questions, side-effect notes)
  from 30 min before the scheduled time until 45 min after are protocol compliance —
  no late-hours callout; the coach closes toward sleep ("Dose done. Screens off.").
  The window derives from PeptideDose, never a hardcoded 22:00. All other after-10pm
  interactions still get the rule-6 callout, sharpened by the tesamorelin/GH-pulse
  rationale. On dose nights the chat_opened 22:0x greeting prompts the unchecked dose,
  not a sleep scold.
- GLP-1 hygiene knowledge: fiber and hydration emphasized; alcohol flagged as hitting
  much harder with delayed gastric emptying.

**Garmin wellness watch (a BUILD, not a read — no coach-path code reads GarminWellness
today):**
- Extend `coach_assembler._build_garmin` to also query GarminWellness (DB-only; sync
  already writes the table) and emit 7-day and 28-day RHR/HRV/sleep-score deltas.
  RHR can ONLY come from GarminWellness (`get_today_summary()` has no restingHr).
- Add the same wellness trends to `weekly_report.compute_weekly_metrics` (§5's "the
  weekly review reports both lines" requires it; it computes zero wellness metrics
  today).
- **Empty/sparse data renders explicitly** ("Garmin wellness: no synced data for N of
  last 7 days") — never omitted. Silence + a prompt rule demanding trend-flagging is
  a rule-20 confabulation setup.
- **Pre-protocol baseline:** at import time, store mean RHR/HRV over the 14-28 days
  before 2026-08-10; sustained trends are judged against that anchor (a rolling
  window slowly absorbs a drug-induced rise) and flagged against the
  retatrutide/tesamorelin timeline.
- §6 verifies GarminWellness rows actually exist for the trailing 7 days (live
  wellness E2E is still unproven); if empty, the watch ships dark **and says so**.

## 4. Meal-plan rail (code-enforced)

- **Hookpoint:** `meal_generator` stays DB-free and dateless (pure function). The
  weekly-generation/regenerate callers in app.py (which already map week/day_idx →
  date) query PeptideDose for a fasted 22:00 dose on each date and pass
  `eating_window_end_override` + a fasting note into `generate_meal_plan` (new
  parameters).
- **Operational definition of "dinner ends by 20:00":** on override days the eating
  window end used by `_compute_meal_times` is clamped to min(protocol window end,
  19:30), so the LAST meal of the day — not just the meal named "Dinner"; under the
  "none" protocol the last meal is a 9:00pm snack — starts no later than 19:30,
  ending by ~20:00. The two concrete violators found in code both respect the clamp:
  the "none" protocol's 9:00pm window end and the hardcoded "8:00pm"
  protein-supplement meal.
- **No-rows behavior:** generation with zero PeptideDose rows (import not yet run)
  applies no rail and does not crash — and does NOT silently apply a hardcoded
  fallback rail (no-static rule).
- **Reconciliation:** pre-existing plans that span a fasted-dose date after a
  (re-)import are regenerated for unlogged, non-past days (see §1 import) — a plan
  generated before import must never keep serving a post-20:00 dinner while the
  protocol card on the same screen says "last meal by 20:00".
- The card shows the why ("Tesamorelin at 10pm requires 2h fasted"), sourced from the
  caller-supplied note (meals render only a start time).
- Meal plans bias fiber + hydration explicitly while on retatrutide; protein floor
  held through appetite suppression (protein-dense, smaller-volume meals).

## 5. Block 3 goal — dual-line recomp, back-loaded curve

**goal_type stays `"cut"`.** This is load-bearing, not cosmetic. "Recomp" (a valid
goal_type) would silently disable: `cut_status` (returns None unless cut) → CORE_PROMPT
rule 21 + the C4 gluten/water guard never fire (the exact block-1 failure); deficit
calorie math (recomp = flat TDEE−100, cannot produce this curve); and coach-prescribed
fast days (silently remapped to rest). Do NOT widen the cut_status gate to compose for
recomp — it flips the fast-day gates and re-derives the whole cut path; keeping "cut"
is the minimal correct choice. "Dual-line recomp" is the block's framing, expressed
via §5b + the waist signal. `TrainingGoal: goal_type="cut", target_weight=195.0`,
tdee refreshed at transition.

### Line 1 (scale): the curve

Single authority — this 12-row table (weeks keyed to the retatrutide ramp; week N =
days 7(N-1)..7N-1 from start_date 2026-08-10, the codebase's `days//7 + 1`
convention; week 3 begins Aug 24 = first 3mg dose, week 7 begins Sep 21 = first 4mg
2×/wk; the Sep 10 frequency doubling is an escalation (§3) but deliberately NOT a
curve boundary — expect weeks 5-6 to run at or ahead of 2.0; ahead-of-curve there is
not a red flag; do not "fix" this by adding a wk-5 boundary):

| Week | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| lb/wk | 1.25 | 1.25 | 2.0 | 2.0 | 2.0 | 2.0 | 2.5 | 2.5 | 2.5 | 2.5 | 2.5 | 2.0 |
| End-of-week target | 218.75 | 217.5 | 215.5 | 213.5 | 211.5 | 209.5 | 207.0 | 204.5 | 202.0 | 199.5 | 197.0 | **195.0** |

Sums to exactly 25.0 lb; `curve[week=12] == goal.target_weight == 195.0` (unit-test
invariant). Week 12 softens to 2.0 matching the deload week.

**Canonical evaluation — ONE function, ONE constant, in goal_engine, imported
everywhere, never re-implemented:**
- `curve(date)`: piecewise-linear DAILY interpolation; a week-N-day-1 date accrues at
  the NEW week's rate. Pinned test values: curve(2026-08-23) = 217.5;
  curve(2026-08-24) accrues at 2.0/7; curve(2026-09-20) = 209.5; curve(2026-09-21)
  accrues at 2.5/7; curve(2026-11-01) = 195.0.
- `CURVE_TOLERANCE_LB = 1.5`, defined once. Three-state judgment: behind if
  weight > curve(date)+tol; ahead if < curve(date)−tol; else on-pace. (Kills the
  existing ±1.0 vs ±1.5 split.)
- The compared weight is always the **de-spiked** weight (C4-consistent) — a gluten
  event must not read "behind" while the guard says it isn't.

**Anchor:** the day-0 block-3 weigh-in — first BodyWeight row with
log_date >= 2026-08-10, de-spiked — with 220.0 as seed until that row exists. The
transition inserts a day-0 BodyWeight row (220.0, 2026-08-10) so cut_status and the
dashboard anchor correctly from minute one. Re-anchoring is **endpoint-preserving**
(195.0 by Nov 1 stays fixed; per-phase rates rescale proportionally — Cut Mode
Priority rule: the 12-week target IS the goal), happens exactly once, never again
mid-block. Generated by a NEW curve builder taking the anchor explicitly — never
`project_weight_curve` (its front-loaded 1.5× metabolic shape is the inverse of a
titrating GLP-1 ramp, and its pa_weight anchor is the known drift bug).

**Projection surfaces inventory (ALL served consumers, each with a fate — leaving any
on the old line violates no-UI-contradictions):**
1. **Canonical store:** the 12 targets written once at transition into
   `TrainingGoal.weight_projection` as `[{week, projected}]` — the shape
   weekly_report and the client already consume.
2. Dashboard `linear_plan` (straight line) — **replaced** by the curve values. No
   straight line is served anywhere.
3. Dashboard `on_pace` badge — **redefined**: de-spiked current weight vs
   curve(today) ± tolerance (was: linear extrapolation vs final target — falsely
   fails weeks 1-2 by design).
4. Dashboard `projected_final_weight` (trailing-14-day rate) — **kept** (an honest
   "where you'll land" estimate), clearly distinct from the plan curve.
5. `cut_status` — pace fields stay descriptive but gain `curve_target_today` /
   `on_curve` from the canonical store; proj_at_week_12 judged against the curve.
   Coach badge and dashboard badge can never disagree.
6. `weekly_report.weight_vs_projected` — works unchanged once weight_projection
   holds the curve (cheapest win); must agree with the dashboard badge (verified §6).
7. Client `_projectWeightCurve` (app.js) — **retired** for block 3; the client
   renders only the served canonical curve (a client-recomputed parallel model is a
   silent-fallback violation).
8. `POST /api/goal/recalibrate` — **retired** (route returns 410; goal_engine
   function deleted). Justification: zero client callers (orphan); weekly generation
   already auto-recalibrates through `_despiked_current_weight`; one authenticated
   call overwrites weight_projection with a linear curve AND tightens calories from
   raw non-de-spiked weight — violating §5 and C4 in a single call.
9. `/api/admin/debug/regenerate-projection` — **rewritten** to regenerate the
   piecewise curve from the stored anchor (or refuse), never the old calorie model.
10. `_compute_goal_for_user` / any path calling `project_weight_curve` — guarded by a
    `projection_mode` marker (TrainingGoal column or SystemFlag
    `projection_mode=piecewise_block3`): while set, generic regeneration preserves
    the piecewise shape or refuses without an explicit override.
11. The weekly-generation deficit block's linear
    `required_weekly = (current−target)/weeks_remaining` — becomes curve-aware
    (reads next week's curve delta), or weekly generation itself keeps emitting the
    linear judgment §5 forbids.
12. `POST /api/deficit-plan` (calorie-recommendation endpoint) — serves an `on_pace`
    computed linearly from RAW (non-de-spiked) weight. **Retired (410)**, same
    rationale and disposition as recalibrate: zero client callers (verified — no
    references in static/ or templates/), and left live it can serve a linear,
    non-de-spiked pace judgment contradicting the canonical badge. If ever revived,
    it must route through `curve()` + `CURVE_TOLERANCE_LB` on de-spiked weight.

### Line 2 (lifts): code-enforced decline detector (§5b)

New shared reader `lift_trend.py` built on `lift_history.lift_session_history`
(SetLog-only, movement-matched): per key lift, weekly max e1RM; weekly tonnage =
Σ(weight × reps_completed) over working sets — bodyweight sentinel sets
(target_weight=0) excluded from tonnage (falsy-zero landmine: use `is None` checks,
never truthiness).

**`lift_decline_suspected` = TRUE when, excluding deload weeks 4/8/12 and comparing
against the best of the trailing 3 non-deload weeks: e1RM down ≥5% on ≥2 of the 5 key
lifts for 2 consecutive non-deload weeks, OR weekly tonnage down ≥10% for 2
consecutive non-deload weeks.** (Defaults; Erik-tunable.) Emitted with its underlying
numbers into the coach context (the `water_spike_suspected` pattern) and into
`weekly_report.compute_weekly_metrics` — one shared definition function for both
(same must-match discipline as `_despiked_current_weight`).

### Recomp measurement

Weekly waist measurement folded into the coach's weekly read (body_measurements
exists); day-0 baseline (photos and/or DEXA) is on Erik this week — the app records
whatever he captures. Scale+lifts alone cannot distinguish fat loss from muscle loss.

### Gluten/water guard (C4) — slope-aware, consolidated

"Carries over unchanged" was wrong: at 2.5 lb/wk, a genuine 5-6 lb spike over a
7-10-day weigh-in gap observes as +1.4..+3.5 — mostly under the 3 lb floor — so the
guard would miss real gluten events exactly when the deficit logic would tighten on
them. Changes:
1. **Slope-aware band:** `adjusted_step = observed_step +
   expected_weekly_loss(week) × (step_days / 7)` using the SAME §5 curve function;
   fire on 3 ≤ adjusted_step ≤ 8. Clamp at step_days ≤ 10 (the existing window) so a
   stale gap can't manufacture a spike from a genuine regain.
2. **One shared detector** (e.g. `cut_guard.detect_water_spike`) imported by BOTH
   `coach_assembler._build_cut_status` and `app._despiked_current_weight`, replacing
   the two comment-enforced copies — both change in the same commit.
3. The recalibrate path that fed raw weight into deficit tightening is retired
   outright (§5 item 8).

## 6. Block 2 → 3 transition (prod ops, reversible)

**The rev-1 "same playbook as last time" was unsafe:** block-1 history ALREADY
occupies weeks 13-24 (re-stamped 2026-06-29), so "block-2 += 12 → 13-19" collides —
unique-constrained tables (set_log; run_log, where Erik ran 7/7 in both blocks so
every slot collides; day_completion; weekly_checkin; …) abort mid-UPDATE while
unconstrained plan tables silently merge two blocks; with no block column the merged
rows are then indistinguishable and the unscoped rollback ("week −= 12") is
unexecutable AND would drag block-1 into weeks 1-12 and decrement never-shifted
coach_memory. The playbook was only safe last time because 13-24 was empty; that
precondition is now false. Additionally, today (2026-08-10) is day 0 of BOTH block-2
week 7 and block-3 week 1, so today's already-written rows (Garmin-pulled RunLog,
blur-saved SetLog, DayCompletion) must be re-homed, not archived.

**Table set (the literal list — forward cascade and rollback run over EXACTLY these
21 tables, referenced from one constant in the migration script, never re-derived):**
`session_analysis, exercise_log` (dead writer, still holds legacy block-1 rows —
shift it), `set_log, exercise_swap, exercise_completion, warmup_completion, run_log,
day_completion, progress_photo, weekly_checkin, garmin_activity,
garmin_workout_link, weekly_report, weekly_schedule_override, meal_plan_override,
run_override, weekly_prescription, weekly_meal_plan, weekly_run_plan, weekly_warmup,
weekly_day_schedule`.
**Excluded** (each with reason): `coach_memory` (never shifted — carries across
blocks); `AppState.current_week` (restored by its own step);
`BodyweightRetest.week_number` (historical block-1 retest data with a UNIQUE
(user_id, week_number) index — pre-flight confirms against the block-1→2 record how
it was handled then; default: excluded, it is display-only history). A pre-flight
assert greps models.py for week-bearing models and fails if the set differs from
this list (catches schema drift between spec-writing and execution).

**Runbook:**
0. Deploy all block-3 code; verify endpoints respond (§0). Deploy freeze begins at
   step 2.
1. **Pre-flight record (rollback data):** per shifted table, the per-(user_id, week)
   histogram (`SELECT week, COUNT(*) … GROUP BY week`) + MIN/MAX week — NOT raw
   counts (counts are invariant under UPDATE and can detect nothing); per-table
   inventory of week-7 rows (today's — drives the re-home); full TrainingGoal
   snapshot (goal_type, target_weight, weight_projection, phase_plan, daily
   calories/macros/tdee); transition timestamp; pre-flight assert: destination
   ranges 25-36 empty in every shifted table (the precondition rev-1 skipped).
2. **Re-stamp cascade — ONE transaction, oldest first** (non-deferrable unique
   constraints make statement order the only collision protection):
   a. `UPDATE t SET week = week + 12 WHERE user_id=:erik AND week BETWEEN 13 AND 24`
      → block-1 lands 25-36 (source/target disjoint, safe);
   b. `UPDATE t SET week = week + 12 WHERE user_id=:erik AND week BETWEEN 1 AND 6`
      → block-2's completed weeks land 13-18 (13-24 now vacant);
   c. **Re-home today:** remaining week-7 rows (only today's, 2026-08-10) →
      `week = 1, day_idx = 0` — today's logged run/lifts live on block-3's day-0
      card; no phantom "week 19", no double-count;
   d. Set AppState `start_date = 2026-08-10, current_week = 1` **in this same
      transaction** — `_current_week()` recomputes from start_date per request, so
      one atomic commit closes the step-b→d live-write race (no separate quiesce;
      run at a low-traffic moment anyway);
   e. Assert per-statement rowcounts equal the pre-flight histogram sums for each
      range, and post-histograms inside the transaction (block-1 intact at 25-36,
      block-2 at 13-18, weeks 2-12 empty) before COMMIT; any mismatch → ROLLBACK,
      zero partial state. Persist the executed (table, from-range, to-range,
      rowcount) list.
   Invariant going forward: at EVERY transition each prior block shifts +12, oldest
   (highest range) first; current block = 1-12, previous = 13-24, higher = older.
   (Optional out-of-scope hardening: an explicit `block` column would kill this
   collision class permanently.)
3. **TrainingGoal:** goal_type stays "cut"; target_weight = 195.0; tdee refreshed;
   weight_projection = the §5 canonical table via the new curve builder (anchor
   220.0 explicit); projection_mode marker set. Insert day-0 BodyWeight row (220.0,
   2026-08-10). (None of this lives in AppState — AppState has only
   current_week/baseline_done/start_date/traveling/user_id.)
4. Import protocol CSV (`?email=erik@placemetry.com`); assert 292 rows, per-compound
   counts, zero taken. Create LabReminders (baseline 2026-08-10; week-8 panel
   2026-09-28). Record vial state as Erik reconstitutes.
5. Regenerate week 1 via `/api/admin/replan-week` (async background job; default
   preserve_through_day = −1 replans all 7 days — correct for a fresh block; pass no
   preserve value). Gate completion on DB truth, not job status (§0).
6. **Forced Garmin sync** (`POST /api/garmin/sync-activities {"force": true}`);
   verify today's GarminActivity + RunLog sit at week 1 day 0. Expected + harmless:
   this sync nulls week/day_idx on Aug 7-9 GarminActivity audit rows inside the
   3-day pull window — documented so nobody panic-debugs it.
7. Erik confirms the shifted ramp with his doctor (2mg start) — if it changes, edit
   CSV → re-import (the designed path).
8. **Served-state verification (no-UI-contradictions: audit SERVED values). The
   check → proving-endpoint mapping is THIS table; every endpoint is §6b's
   serve-as-user allowlist, an existing `?email=` debug GET, or the new
   coach-context debug read:**

   | Check | Proving endpoint |
   |---|---|
   | Today's card shows ACTUAL state — Garmin run visible on block-3 w1d0; pre-transition lift sets shown in_progress/complete (NOT rev-1's "today = not_started", which would pass while lying) | `/api/debug/today-status`, serve-as-user `path=/api/workouts` |
   | Zero rows at week 7 or 19 in any shifted table; block-1 intact at 25-36; block-2 at 13-18; histograms match | direct DB via `/api/admin/debug/exec` (data check, not a served surface) |
   | Served lift history still returns BOTH parked blocks' sessions (guards any reader implicitly assuming prior block = weeks 13-24, which moved) | serve-as-user `path=/api/progress` |
   | Coach context: **non-null cut_status**, anchor 220 / target 195, week-1 curve pace ~1.25 lb/wk (fails loudly if anyone set goal_type="recomp"); protocol block present; wellness block present or explicitly dark | `GET /api/debug/coach-context?email=` (new, §6b — assembled context blocks, no LLM call) |
   | Coach-prescribed fast day survives as meal_type=fast_day (not rest) | serve-as-user `path=/api/meals` |
   | Week-1 plan complete in ALL THREE domains — WeeklyPrescription rows on planned train days (floor-enforced), WeeklyRunPlan 7/7, **WeeklyMealPlan rows present** (the per-domain-commit partial-generation failure §0 guards) | `/api/debug/api-workouts-as-user`, `/api/debug/run-plan`, serve-as-user `path=/api/meals` |
   | Protocol card renders **exactly the PeptideDose rows for today — 2026-08-10 = 5 events, all 07:00: oral Enclomiphene 6.25 + injections BPC-157 0.25, KPV 1, Retatrutide 2, TB-500 2.5** — count cross-checked against the CSV at verification time (guards dropping the oral row) | serve-as-user `path=/api/protocol/today` |
   | Dashboard: piecewise curve present, NO straight-line plan series; on_pace badge, cut_status.on_curve, weekly_report weight_vs_projected, and coach's stated pace all agree; projection day-0 = 220.0 regardless of pa_weight | serve-as-user `path=/api/progress` + `path=/api/stats/projection-inputs`, `/api/debug/coach-context` |
   | Week-12 retest lock stays dead: due_and_pending = false (§7) | serve-as-user `path=/api/bodyweight-retest/status` |
   | GarminWellness rows exist for trailing 7 days, or the wellness watch explicitly reports itself dark (§3) | serve-as-user `path=/api/garmin/wellness?days=7` |

**Rollback (exact scoped inverse; ORDER IS LOAD-BEARING — the discriminators below
only work in this sequence):**

Note first: the forward cascade's structural claim needs one carve-out — after
forward step 2, every legitimate historical row sits at week ≥ 13 **except the
re-homed 2026-08-10 rows at w1d0**, which are legitimate block-2 history living at
week 1. Every rollback predicate below respects that carve-out by discriminating on
`date == 2026-08-10`.

1. **Un-re-home FIRST:** log-table rows at week=1, day_idx=0 dated 2026-08-10 →
   week 7 (their original block-2 home). This must precede parking — if parking ran
   first, these rows would already sit at week 101 and the w1d0 selector would match
   nothing, stranding Erik's real training in the parking range.
2. **Park, never delete, real block-3 training:** log-table rows
   (SetLog/RunLog/DayCompletion/ExerciseCompletion/WarmupCompletion/
   GarminWorkoutLink/GarminActivity) with week ≤ 12 **AND row-date > 2026-08-10** →
   week += 100 (Phase-Rebuild lesson: never destroy logged history). The date
   predicate excludes the just-restored week-7 rows.
3. Delete regenerable block-3 rows: week ≤ 12 rows in the **non-log** shifted tables
   only — the 5 plan tables (WeeklyPrescription/WeeklyRunPlan/WeeklyMealPlan/
   WeeklyWarmup/WeeklyDaySchedule) plus the overrides/session_analysis/
   weekly_checkin/weekly_report/progress_photo/exercise_swap. Log tables are NEVER
   in a delete statement — anything real in them was parked in step 2 or restored in
   step 1.
4. Newest-first un-shift, one transaction, same 21 tables:
   `week −= 12 WHERE week BETWEEN 13 AND 18` (block-2 → 1-6; weeks 1-6 are vacant —
   block-3 rows were parked/deleted, and the restored rows sit at week 7, untouched
   by BETWEEN 13 AND 18), then `week −= 12 WHERE week BETWEEN 25 AND 36`
   (block-1 → 13-24). Verify against pre-flight histograms.
5. Restore AppState AND the snapshotted TrainingGoal fields (the 195 target + curve
   live in TrainingGoal — restoring AppState alone leaves a false 220→195 line over
   block-2 data, the exact false-line class 55b9b4c hardened against). Clear
   projection_mode.
6. Delete imported PeptideDose, PeptideVial, and LabReminder rows (scoped to user +
   the 2026-08-10..2026-11-01 range).
7. Verify SERVED state post-rollback: dashboard shows block-2 target/curve (no 195,
   no §5 curve, no ON-PACE vs 195), cut_status non-null, today's run/lifts visible
   on block-2 week-7 day 0.

## 6b. Debug surface for served-state verification

Rev-1's §6 checks weren't executable: meals/progress/projection payloads are
login-only and the protocol payload is new. Two additions:

1. `GET /api/debug/serve-as-user?email=&path=` (X-Admin-Key) — reusing the proven
   test-client impersonation pattern from `api-workouts-as-user`, with `path`
   validated against an explicit GET-only allowlist: `/api/workouts`, `/api/meals`,
   `/api/progress`, `/api/stats/projection-inputs`, `/api/protocol/today`,
   `/api/garmin/wellness`, `/api/bodyweight-retest/status`. Allowlist + GET-only
   keeps it from becoming a request proxy.
2. `GET /api/debug/coach-context?email=` (X-Admin-Key) — returns the assembled coach
   context blocks (cut_status, protocol, wellness, today_status) with **no LLM
   call**, consistent with the existing audit-the-coach's-inputs debug pattern. This
   is the proving endpoint for every "coach context contains X" check; no GET path
   serves the assembled context today.

Existing endpoints (today-status, run-plan, api-workouts-as-user, admin debug/exec)
stay. The §6 step-8 table maps every check to its endpoint.

## 7. Regression guards (NOT fix items — both bugs are already fixed)

- **Week-12 retest lock: ALREADY FIXED** 2026-06-29 (commit 71a2a93:
  `RETEST_WEEKS = ()`; status endpoint can never report due_and_pending; POST rejects
  all retest weeks; regression-pinned by `tests/test_no_retest_gate.py`). Rev-1
  scheduled fixing it from a stale memory note (since corrected). Residual scope
  here: the §6 served check (due_and_pending = false) + a guard that nothing in this
  block's changes repopulates RETEST_WEEKS or adds new blocking gates in the app.js
  init path before renderAll() (the morning-check-in gate is the pattern that can
  reproduce a whole-app lock). Optional hygiene, separate decision: deleting the dead
  client-side gate/modal code — but NOT the `/deltas` display code, which renders
  historical block-1 retest data. (Pre-fix, the lock would have fired at week-12
  START, Oct 26 — not Nov 1.)
- **Coach-narrates-template-on-unplanned-days: ALREADY FIXED** 2026-06-29 (3671d58).
  Verify on prod; not tracked as open.

## 8. Testing

**Import / data model:**
- Idempotency: unchanged re-import is a no-op; updates apply without duplicating or
  clearing taken_at; import rejects duplicate (date, compound) CSVs.
- Midday re-import with today's 07:00 doses checked + a future dose changed →
  taken_at intact, updates applied.
- Time change on a checked-off today dose → single row, new time (metadata update
  allowed on taken rows), taken_at preserved (regression for the (date, compound)
  key); dose_mg change on the same taken row → skipped + reported in the divergence
  list (the injected-history record is immutable).
- Removing an unchecked today dose → gone from served card; removing a CHECKED today
  dose → row kept + annotated.
- Property: no import ever deletes a taken_at-bearing row or updates its dose_mg;
  past rows immutable (no insert/delete; divergences reported).
- Whole-file integrity: an import whose row count or per-compound counts mismatch
  the CSV fails loudly (partial import is impossible to miss).
- Un-check-then-reload persists; vial doses-left rises by one after un-check
  (derivation, not counter).

**Vial mg-derivation (boundary-spanning fixtures, hand-computed expected values):**
- A retatrutide vial spanning Aug 24 (2→3mg) and Sep 10 (frequency doubling):
  served doses-left and reorder date match hand-computed mg walk.
- A retatrutide vial spanning Sep 21 (3→4mg 2×/wk): same assertion.
- A TB-500 vial spanning the Sep 7 2.5→2mg step-down: same assertion.
- Expiry-beats-mg-depletion for a slow compound (BPC-157 0.25mg/day or GHK-Cu):
  effective run-out = expiry date, not mg exhaustion.
- Multi-vial attribution (sequential BPC-157 vials): check-offs land on the correct
  vial's reconstituted_on window; doses-left computed per-vial.

**LabReminder:**
- Surfaces in coach context only within its due window (completed_at IS NULL AND
  due_date <= today+7); disappears permanently once completed_at is set; never
  resurfaces.

**Timezone / check-off:**
- Check-off at 22:05 America/Los_Angeles (05:05 UTC next day) counts for the dose's
  own date; card + 7-day adherence agree.
- Next-morning retro-mark (§1 op 1, UNGATED) of yesterday's 22:00 Tesamorelin dose
  with its rule still the null placeholder → SUCCEEDS via the toggle endpoint,
  counts on-time for yesterday (the two operations are distinct: this is not a
  late-take). The toggle write-gate rejects doses dated 2+ days back or future.
- 16:00 PST dose (= 00:00 UTC next day) counts for its own date.
- Adherence window spanning Sun 2026-11-01 (DST fall-back; final day has a 22:00
  dose) computes correctly via zoneinfo.
- Taken-late (§1 op 2, GATED, `/late` endpoint, doses older than yesterday): within
  late_window counts in adherence (flagged late) + vial math; outside window
  rejected server-side; compounds with the null placeholder rule reject taken-late
  (while retro-mark for yesterday still works, per the test above); a late-stamped
  past row never renders today's card as done.

**Curve:**
- `curve[12] == target_weight == 195.0`; deltas sum to 25.0.
- Pinned boundaries: curve(2026-08-23)=217.5; curve(2026-08-24) accrues at 2.0/7
  (≈217.21, NOT ≈217.32); curve(2026-09-20)=209.5; curve(2026-09-21) accrues at
  2.5/7; curve(2026-11-01)=195.0.
- Exactly the §5 slope table (slope(week 5) == 2.0 — pins "no wk-5 boundary" against
  well-meaning fixes).
- On-pace: weigh-in equal to curve(t) mid-week in EACH phase → on-pace;
  curve(t)+tol+0.1 → behind; boundary dates continuous (no jump); dashboard and
  cut_status return identical status for identical inputs; week-1 1.25 lb/wk actual
  → ON PACE; week-8 stall (actual 0 vs 2.5) → OFF PACE.
- Anchor: first weigh-in ≠ 220 (223.5 spiked and 218.0) → consistent curve,
  dashboard, cut_status; no day-1 "behind" artifact; served projection day-0 = 220.0
  regardless of pa_weight.
- Gluten guard attenuation: 5 lb spike at 7- and 10-day gaps on week-8 slope →
  fires after slope adjustment.

**cut_status / goal gating:**
- Block-3 seeded state → `_build_cut_status` returns non-null incl. gluten-guard
  fields; assembled prompt contains `<cut_status>`; WATER_SPIKE_SUSPECTED fires on a
  seeded 3-8 lb spike-on-downtrend.
- Coach-prescribed fast day serves meal_type=fast_day (not rest).

**Line-2 detector:** synthetic SetLog sequences that must trip (e1RM path, tonnage
path), must not trip, and must not trip across a deload week; weekly_report and
context block emit identical values (shared function).

**Meal rail:**
- Fasted-dose date → every meal time parses ≤ 19:30 regardless of fasting protocol
  (including "none" and the supplement meal); no dose → protocol window unchanged.
- Zero PeptideDose rows → no crash, no rail.
- Re-import adding/moving a fasted dose over an existing current-week plan →
  affected unlogged days regenerated/flagged; logged-meal + past days untouched.
- Served full-day payload on a fasted date: all meal times ≤ 20:00 AND the protocol
  row bound present (no-UI-contradictions).
- UI smoke: the 20:00 bound renders on the protocol row even with no meal plan.

**Coach / judge regression cases:**
- Escalation-week stall → coach cites the dated escalation, issues a cut directive,
  asserts no causation.
- 22:10 post-dose message → no late-hours scold; 23:30 non-dose message → scolded.
- Missed dose with placeholder rule → exactly "confirm with your doctor".
- Wellness: sparse data renders the explicit "no synced data" line (never silence).

**UI smoke:** protocol section renders one row per PeptideDose for the date (orals
included); check-off persists across reload; no watch-for/mechanism text in the
rendered protocol section.

**Transition (integration, against a prod-shaped fixture):** cascade produces
block-1@25-36 / block-2@13-18 / today@w1d0, histograms match; rollback restores
exactly pre-state (incl. TrainingGoal) with block-3 logs parked, not deleted.

**Prod verification:** through the §6b served endpoints only, per the standing rule.
No deploy-polling; push, note it's deploying, verify once live.

## Out of scope

- Side-effect journaling UI (coach chat captures it conversationally; revisit later).
- Supplier/pharmacy integration for inventory.
- `block` column migration (noted as the durable fix for the re-stamp collision
  class; this transition uses the cascade).
- Deleting dead client-side retest gate code (separate decision; §7).
- Any medical dosing decision — dose values come from Erik's doctor via the CSV.
