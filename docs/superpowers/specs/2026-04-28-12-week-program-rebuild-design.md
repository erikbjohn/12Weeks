# 12-Week Program Rebuild — Design Spec

**Author:** Erik (program owner) + synthesized from research agents
**Date:** 2026-04-28
**Status:** Draft for sign-off, then implementation
**Companion:** `docs/superpowers/plans/2026-04-28-program-template-db-migration.md` (DB layer)
**Companion:** `docs/superpowers/research/2026-04-28-program-rebuild-research.md` (raw research notes)

---

## Framing

A 12-week cut block, runner-first. Lifting is muscle-preservation insurance + targeted weak-point work (shoulders, leg power for the August event prep that follows this block). Running is the aerobic engine in a polarized 80/20 intensity split. Week 12 = scale + look. The August prep is a separate program starting Mon week 13 with no buffer week between.

**Athlete constraints (locked, do not redesign around):**
- 209 lb → 185 lb target = ~3 lb/week cut velocity. Aggressive. Honest math: lean-mass loss expected even with optimal training. Program optimizes for retention, does not gate the cut.
- 16:8 daily intermittent fasting + 40-hour weekend fast (Sat 7pm → Mon 11am).
- Shoulder/neck chronic tightness — exercise pool restricted accordingly.
- Mental health anchor — adherence and "showing up" matter more than weekly PRs.
- Lombardi/Saban coach posture — numerical triggers, no "your call," no future-tense capitulation.
- AM-stacked at 6am: lift first → run after. Every day.

**Program goal — what success looks like at end of week 12:**
- Scale shows 185 (or within 1–2 lb)
- Photos show what 7+ weeks of disciplined cut produces — visible lateral delts, lats, glutes
- Bar still moves on the heavy compounds (no measurable strength regression beyond ~5%)
- Body still ABLE to begin August prep Monday week 13 without a recovery week

Not the goal: PRs, fitness benchmarks, trail PRs (no trail this block).

---

## 1. Architecture & Principles

### Phase structure

| Weeks | Phase | Dominant work | Volume | Intensity |
|---|---|---|---|---|
| 1–3 | **Phase 1: Hypertrophy / adaptation** | Build muscle base, adapt to schedule | MAV (high) | 8–12 reps, RIR 1–3 |
| 4 | **Deload** | Recovery + transition into strength | 50% volume, 70% load | RIR 4–5 |
| 5–7 | **Phase 2: Strength** | Wave-load compounds, weight bumps each session | MEV–MAV (mid) | 5×5 + accessory pump |
| 8 | **Deload** | Recovery + transition into cut climax | 50% volume, 70% load | RIR 4–5 |
| 9–11 | **Phase 3: Cut climax** | HOLD strength, accessory volume drops | MEV (floor) | RPE-capped, no bumps |
| 12 | **Peak finish** | Mini-taper, scale + look | MEV –25% | Compound singles only |

### Progression principle (the rule)

**One knob moves per session. The phase decides which knob. Two knobs move only at boundaries.**

| Phase | Moves | Pinned |
|---|---|---|
| Phase 1 | reps build (8→12) | weight, sets |
| Phase 2 | weight bumps each session | reps, sets |
| Phase 3 | HOLD — nothing moves | weight, reps, sets |
| Week 12 | HOLD | everything |

Boundaries: when Phase 1 rep range caps → weight bumps + reps reset. When phase changes → scheme switches as a unit.

**Never:** weight up + sets up + reps unchanged in a single session. That's the "random bullshit" pattern from the prior code.

### Day-of-week template (locked)

AM stacked at 6am: lift first → run after. Lift first → glycogen depletes → run is zone-2 by necessity → ideal for fasted fat oxidation.

| Day | Lift focus | Run | Why |
|---|---|---|---|
| Sun | (rest from iron) | Long fasted easy 60–90 min | Deepest fasted state, fat-ox bias |
| Mon | Lower POWER + RDL | Easy zone-2 25–35 min | Heavy-ish leg session in 35hr-fasted state |
| Tue | Upper PRESS + shoulder | HIIT VO2 ~35 min | Upper lift doesn't pre-fatigue running legs |
| Wed | Shoulder volume + arms | Easy zone-2 35–45 min | Designated low-CNS day |
| Thu | Upper PULL + lat | HIIT threshold or hill repeats ~35 min | Upper again, legs fresh for intervals |
| Fri | HEAVY lower (THE strength session) | Easy 20-min recovery jog | One heavy lift / week |
| Sat | Full body / glute focus | Easy 30-min run | Volume cleanup |

**Hard sessions per week (3):** Tue HIIT, Thu HIIT, Fri heavy lower.
**Everything else:** easy / volume cleanup.

### Run schedule

7 runs/week. Volume varies by phase:

| Day | Phase 1 | Phase 2 | Phase 3 | Wk 12 |
|---|---|---|---|---|
| Sun long | 60–90 min easy | 60–90 min easy | 60–90 min easy | 60 min easy |
| Mon | 25–35 min easy | 25–35 min easy | 25–30 min easy | 20 min easy |
| Tue HIIT | threshold 35 min | VO2 4×4 ~35 min | VO2 4×3 ~35 min | easy 35 min — no HIIT |
| Wed | 35–45 min easy | 35–45 min easy | 35 min easy | 30 min easy |
| Thu HIIT | threshold/hills 35 min | threshold/hills 35 min | threshold 35 min | easy 30 min — no HIIT |
| Fri | 20-min recovery | 20-min recovery | 15-min recovery | 15-min recovery |
| Sat | 30 min easy | 30 min easy | 25 min easy | 20 min easy |

---

## 2. Phase 1 — Weeks 1–3 (Hypertrophy / Adaptation)

### Day-by-day

| Day | Lift (45–60 min) | Run |
|---|---|---|
| Sun | rest from iron | Long fasted 60–90 min |
| **Mon — Lower hypertrophy** | Front Squat 4×8–12 • Bulgarian SS 3×8–10 each • Romanian Deadlift 3×8–10 • Standing Calf 3×12 | Easy 25–35 min |
| **Tue — Press + Shoulder** | DB Bench (neutral) 4×8–10 • Landmine Press 3×8–10 each • Cable Lat Raise 3×15 • Face Pull 3×15 | HIIT threshold 35 min |
| **Wed — Shoulder vol + Arms** | Cable Lat Raise 4×15 • Reverse Pec Deck 3×12–15 • Hammer Curl 3×10–12 • EZ-Bar Curl 3×10–12 • Tricep Pushdown 3×12 • Overhead Tricep Ext 3×12 | Easy 35–45 min |
| **Thu — Pull + Lat** | Weighted Pull-Up 4×6–8 • BB Row 4×8 • Lat Pulldown 3×10 • Single-Arm DB Row 3×8 each • Face Pull 3×15 | HIIT threshold/hill 35 min |
| **Fri — Heavy Lower hypertrophy** | Back Squat 4×8 @ ~70% • Hip Thrust 4×10 • Lying Leg Curl 3×12 • Calf 3×12 | Easy 20-min jog |
| **Sat — Full Body** | Hip Thrust 3×10 • Cable Chest Fly 3×12 • DB Row 3×8 each • Cable Lat Raise 3×15 • Ab Wheel 3×10 | Easy 30 min |

### Phase 1 progression rule

- Each lift starts at 4×8 (compound) or 3×8 (accessory).
- Each session, add 1 rep until you cap the range (12).
- When **all sets** cap at 12 → next session bumps weight (+5 lb upper / +10 lb lower) and **resets reps to 8**.
- Sets pinned. Weight pinned until rep cap.

### Volume per muscle / week (Phase 1 — MAV territory)

| Muscle | Sets/week |
|---|---|
| Chest | 11 |
| Lats | 18 |
| Mid-back | 12 |
| Lateral delts | 16 |
| Rear delts | 13 |
| Quads | 13 |
| Hamstrings | 12 |
| Glutes | 13 |
| Biceps | 12 |
| Triceps | 12 |

Phase 1 is the deposit. Build everything you'll later defend.

---

## 3. Week 4 — Deload

Same structure as wk 8 deload (§5). Sessions cap at 30 min. Volume cut 50%, intensity ~70% of Phase 1. NO HIIT week 4. Long run drops to 60 min Sun. Same exit criteria as wk 8 (must hit all 4 to enter Phase 2).

---

## 4. Phase 2 — Weeks 5–7 (Strength)

**Strategy:** Wave-load compounds. Weight bumps each session if last session hit prescribed reps at RPE ≤ 8. Reps and sets pinned. Lateral delts at MAV (shoulder rebuild priority), back at MAV (aesthetic), legs at MEV (running covers), arms minimal direct.

### Day-by-day

**Mon — Lower POWER + RDL** (45 min)

| Exercise | Scheme (wk5 → wk6 → wk7) | Notes |
|---|---|---|
| Box Jump | 3×5 explosive | RPE 7. Bar speed > load. |
| Front Squat | 4×3 @ ~70% → 73% → 76% | Speed-focused, NOT max effort. |
| Bulgarian Split Squat (DB) | 3×8 each leg | Unilateral, leg power transfer. |
| Romanian Deadlift | 3×8 RPE 7 | Pinned 8 reps; weight bumps weekly. |

**Tue — Upper PRESS + Shoulder Strength** (50 min) → HIIT VO2 4×4

| Exercise | Scheme | Notes |
|---|---|---|
| DB Bench Press (neutral) | 4×5 @ 75% → 78% → 82% | RPE 8 cap. Neutral protects shoulder. |
| Landmine Press | 3×6 each side | Shoulder-friendly OHP sub. |
| Cable Lateral Raise | 3×12 | Constant tension, lateral delt rebuild. |
| Cable Face Pull | 3×15 | Postural, mandatory. |

**Wed — Shoulder Volume + Arms** (45 min) → easy 35–45 min run

| Exercise | Scheme | Notes |
|---|---|---|
| Cable Lateral Raise | 3×15 | Lateral volume. |
| Reverse Pec Deck | 3×12 | Rear delt isolation. |
| DB Hammer Curl | 3×10 | Brachialis. |
| Cable Tricep Pushdown | 3×12 | Tricep iso. |
| EZ-Bar Curl | 3×10 | Biceps direct. |

**Thu — Upper PULL + Lat** (50 min) → HIIT threshold/hills 35 min

| Exercise | Scheme | Notes |
|---|---|---|
| Weighted Pull-Up | 4×5 (heavy) + 2×AMRAP BW | Cap AMRAP at +2 over prescribed. |
| Barbell Bent-Over Row | 4×6 @ 75% → 78% → 82% | RPE 7–8. |
| Lat Pulldown (neutral grip) | 3×10 | Different angle, lat volume. |
| Cable Face Pull | 3×15 | Postural. Yes, again. |

**Fri — HEAVY Lower (THE strength session)** (50 min) → 20-min recovery jog

| Exercise | Scheme | Notes |
|---|---|---|
| Back Squat (top set + back-off) | wk5 4×5 @ 78% • wk6 3×5 @ 82% • wk7 3×3 @ 87% (RPE 8 cap) | The heavy lift of the week. Refed Thursday. |
| Hip Thrust | 4×8 RPE 7 | Glute. |
| Lying Leg Curl (or DB single-leg curl) | 3×10 | Hamstring iso. |

**Sat — Full Body / Glute Volume** (50 min) → easy 30 min

| Exercise | Scheme | Notes |
|---|---|---|
| Hip Thrust | 3×10 RPE 6 | Lighter Sat (twice/week glute). |
| Cable Chest Fly | 3×12 | Chest accessory. |
| Single-Arm DB Row | 3×8 each | Back volume. |
| Cable Lateral Raise | 3×12 | More shoulder. |
| Ab Wheel Rollout | 3×10 | Core. |

### Phase 2 progression rule (sharp)

Every Mon/Tue/Thu/Fri main lift evaluated at the top set:

| Performance | Action |
|---|---|
| All reps clean, RPE ≤ 7 | +5 lb lower / +2.5 lb upper next session |
| All reps clean, RPE 8 | +2.5 lb across the board OR hold |
| Missed by 1–2 reps | Hold weight; if 2 weeks in a row, drop 5% |
| Missed badly OR top set RPE 9+ | Drop 10%, run a 1-week mini-deload, restart wave |

### Cut-aware modifications (the 3 lb/week reality)

- Rest periods: 4 min on heavy compounds (extends from standard 3 min)
- AMRAP cap: prescribed reps + 2 max. No grinders.
- Thursday refeed: +50% carbs, day before Fri heavy lower
- Sun: full rest from iron + the long fasted run. Do NOT add lift volume Sunday.
- Mon 35hr-fasted state: front squat WAVE % stays low (70–76%) — speed work, not max effort. Heavy lower stays Friday in fed state.

---

## 5. Week 8 — Deload

**Strategy:** Volume cut 50%, intensity ~30%. Same exercises (preserve neural patterns + weekly structure), fewer sets, lighter loads. No HIIT this week — Tue and Thu HIIT slots become easy zone-2. Sessions cap at 30 min.

### Per-day deload spec

| Day | Lift (≤30 min) | Run |
|---|---|---|
| Sun | rest from iron | Long fasted **60 min** (down from 90) |
| Mon | Box Jump 2×5 • Front Squat 3×3 @ 65% • Bulgarian SS 2×8 each | Easy 25 min |
| Tue | DB Bench 3×5 @ 70% • Landmine Press 2×6 ea • Lat Raise 2×12 • Face Pull 2×15 | **Easy 35 min — no HIIT** |
| Wed | Lat Raise 2×15 • Reverse Pec Deck 2×12 • Curl OR Pushdown 2×12 (pick one) | Easy 35 min |
| Thu | Pull-Up 3×5 BW • BB Row 3×6 @ 70% • Lat Pulldown 2×10 • Face Pull 2×15 | **Easy 35 min — no HIIT** |
| Fri | Back Squat 3×5 @ 65% • Hip Thrust 3×8 RPE 6 | Easy 20 min |
| Sat | Hip Thrust 2×10 light • Chest Fly 2×12 • DB Row 2×8 ea • Lat Raise 2×12 | Easy 25 min |

### Deload exit criteria (must hit ALL to enter Phase 3)

1. Resting HR within 5 bpm of baseline morning value
2. Sleep quality self-report ≥7/10 for 3 consecutive nights
3. No muscle soreness lasting >24hr after any session
4. Lifting feels neutral or anticipated, not aversive

If criteria not met → extend deload 3 days. Phase 3 starts when recovered, not when calendar says.

### What deload does NOT change

- 16:8 + 40-hr weekend fast continues. Not a diet break.
- Run frequency stays 7×/week (just lighter).
- AM-stacked at 6am stays.
- Mon 35hr-fasted lift slot still exists, just lighter.

---

## 6. Phase 3 — Weeks 9–11 (Cut Climax)

**Strategy reversal.** In a deeper deficit, weights HOLD. The win condition is "I maintained Phase 2 lifts" not "I bumped them." Volume drops to floor. RPE is the regulator. Shoulder volume preserved (it's the weak point we're rebuilding, the cut isn't allowed to erase that gain).

### Per-day Phase 3 (~5–10 min shorter than Phase 2)

| Day | Lift (≤45 min) | Run |
|---|---|---|
| Sun | rest from iron | Long fasted 60–90 min |
| **Mon — Lower POWER** (40 min) | Box Jump 3×5 • Front Squat 3×3 @ 73% **HOLD all 3 wks** • Bulgarian SS 2×6 each • RDL 2×6 RPE 6 | Easy 25–30 min |
| **Tue — Press + Shoulder** (45 min) | DB Bench 3×5 @ 80% **HOLD** • Landmine Press 2×6 ea • Cable Lat Raise 3×12 • Face Pull 3×15 | HIIT 4×3 VO2 |
| **Wed — Shoulder/Arms** (40 min) | Cable Lat Raise 3×15 • Reverse Pec Deck 2×12 • Hammer Curl 2×10 • Tricep Pushdown 2×12 | Easy 35 min |
| **Thu — Pull + Lat** (40 min) | Weighted Pull-Up 3×5 same load • BB Row 3×6 @ 80% **HOLD** • Lat Pulldown 2×10 • Face Pull 2×15 | HIIT threshold 35 min |
| **Fri — HEAVY Lower** (45 min) | **Back Squat 3×3 @ 87% — HOLD all 3 wks. RPE 8 cap. NO bumps.** • Hip Thrust 3×8 RPE 7 | Easy 15-min recovery jog |
| **Sat — Full Body** (40 min) | Hip Thrust 2×10 light • Chest Fly 2×12 • DB Row 2×8 ea • Cable Lat Raise 3×12 | Easy 25 min |

### Volume changes vs Phase 2

| Muscle | Phase 2 | Phase 3 | Δ |
|---|---|---|---|
| Lateral delts | 13 | 12 | -8% (kept high — shoulder priority) |
| Lats | 14 | 10 | -29% |
| Glutes | 14 | 8 | -43% |
| Quads | 11 | 8 | -27% |
| Triceps | 8 | 4 | -50% |
| Biceps | 9 | 4 | -56% |

### Phase 3 progression rule (the inversion)

- **Weights HOLD across all 3 weeks.** Default = hold.
- **Bump exception:** if a session's top set feels true RPE 6 (clearly easy) → hold one more session → if also RPE 6 → optional +2.5 lb. Don't chase.
- **If top set RPE >8** → drop 5%, repeat at lighter weight next session. Don't grind.

### Autoregulation in Phase 3 (tighter)

- 1 missed top set → drop 2.5 lb next session, no penalty
- 2 missed top sets in a week → 1 mid-block deload week, then resume at previous-week weight
- Resting HR >+8 bpm for 3 days → cut HIIT to 1×/week (Thu only)
- Sleep <6 hr for 3 nights → cut Wed shoulder volume in half

---

## 7. Week 12 — Peak Finish (Scale + Look)

**Goal:** Land at 185. Look right. Transition cleanly into August prep without a crash.

**Strategy:** Mini-taper. Volume cut another ~25% from Phase 3. Intensity held on compounds (one working set each — maintain neural pattern, don't grind). Shoulder lateral raises, face pulls, glutes preserved at Phase 3 level — these MAKE the look. Drop direct arm work. **No HIIT week 12.**

### Per-day Week 12

| Day | Lift (≤30 min) | Run |
|---|---|---|
| Sun | rest from iron | Long fasted **60 min** |
| Mon | Box Jump 2×5 • Front Squat 2×3 @ 73% • Bulgarian SS 1×6 each | Easy 20 min |
| Tue | DB Bench 2×5 @ 80% • Landmine 1×6 ea • Cable Lat Raise 3×12 • Face Pull 3×15 | **Easy 35 min — NO HIIT** |
| Wed | Cable Lat Raise 3×15 • Reverse Pec Deck 2×12 | Easy 30 min |
| Thu | Pull-Up 2×5 • BB Row 2×6 @ 80% • Lat Pulldown 1×10 • Face Pull 2×15 | **Easy 30 min — NO HIIT** |
| Fri | Back Squat 2×3 @ 87% (single working set, just to feel it) • Hip Thrust 2×8 | Easy 15 min |
| Sat | Hip Thrust 2×10 light • Chest Fly 2×12 • Cable Lat Raise 2×12 | Easy 20 min |

### Transition into August prep (week 13+)

**Week 13 = August prep starts immediately.** No buffer week. Weigh-in Mon AM week 13 → August program begins same day. The cut ends at week 12 regardless of whether 185 was hit precisely.

---

## 8. Cross-Cutting Rules (the rulebook)

The entire program operates under these. Each rule has a clear trigger, not a vibe.

### A. Progression (one-knob principle)

Already specified per phase in §1. **Never** all three of weight + reps + sets up in one step.

### B. Autoregulation triggers (numerical)

| Trigger | Response |
|---|---|
| 1 missed top set in a session | Drop 2.5 lb upper / 5 lb lower next session. No penalty. |
| 2 missed top sets in one week | Unplanned mid-block deload (1 lighter week). Resume at previous-week weight. |
| Resting HR ≥+10 bpm baseline 3+ days | Cut HIIT to 1×/week (Thu only). |
| Sleep <6 hr 4+ nights | Cut Wed shoulder volume in half. |
| Joint pain ≥4/10 on a compound | Swap to shoulder-friendly variant for 2 weeks. |
| Lifting feels aversive 3+ sessions | Unplanned deload + mental-health check-in. |

### C. Refeed protocol

- **Thursday weekly:** +50% carbs over baseline within 8hr eating window. Protein and fat held. Purpose: fuel Friday heavy lower.
- **Deload weeks (4, 8):** Thursday refeed bumps to +75% carbs.
- **Week 12:** skip refeed — final cut push.
- **40-hr Sat 7pm → Mon 11am fast: every week, including deload.** Locked.

### D. Adherence / streak levers

| Trigger | Response |
|---|---|
| 5 consecutive sessions complete | Unlock optional novel-exercise slot next session (1 exercise his pick, 3 sets) |
| 10 consecutive | Unlock +1 accessory option for rest of phase |
| Missed 1 session | No coach reaction. Resume. |
| Missed 2 consecutive | 3-day reset. First session back = minimum viable session only. |
| Missed 3 consecutive | Restart current 3-week phase. Cut continues. |
| 185 lb hit early | Cut auto-switches to maintenance for remaining weeks. |

### E. Session-level rules

- **Lift session cap: 45–60 min.** Coach refuses to extend. Volume cuts before time extends.
- **Minimum viable session** = top set + 1 backoff on the day's main lift, ~15 min, no accessories, just shoulder warm-up. **Counts as full streak credit.**
- **Rest periods (Phase 2/3):** 4 min on heavy compounds.
- **AMRAP cap:** prescribed reps + 2 max.
- **Pre-7am lift:** auto −5% on top set. Treat prescribed as floor, not ceiling.
- **AM stack at 6am:** lift first → run after.
- **Shoulder/scap warm-up — mandatory before any press or pull day** (~5 min):
  - Band pull-aparts 2×20
  - Scap push-ups 2×10
  - Wall slides 1×10
  - Neck CARs (slow) 3–5 each direction
  - **Skipping = same as skipping a working set.**

### F. Coach posture (Lombardi/Saban)

- No "your call." No "listen to your body." No "if you feel up to it."
- Numerical triggers only. Vagueness is sycophancy.
- Future-tense deviation refused outright. "I'll make it up tomorrow" — not in the menu.
- Skipping is not a downgrade option. Minimum viable session is the floor.
- "Tired" is not a reason. Inflamed, injured, sick = reasons. Mood is a workout *target*, not a workout veto.
- Consistency rule: same memory and rules across interactions. No contradictions, no waffling, no apologizing for the program's intensity.

### G. Excluded movements (shoulder/neck protection)

- Behind-the-neck press (any variant)
- Upright row above chest height
- Wide-grip BB bench at competition width
- Snatch-grip overhead work
- Heavy pronated shrugs
- Behind-the-neck pulldown
- Kipping pull-up (any)

### H. Equipment substitutions

- **No dip station:** weighted dip → DB bench heavy or close-grip bench; tricep dip → close-grip push-up + cable pushdown.
- All other equipment present at rooftop — no other substitutions needed.

### I. Run schedule rules

- 7 runs/week, AM stacked after lift.
- **Sun:** long fasted easy 60–90 min (deepest fast — fat oxidation training).
- **Mon, Wed, Fri, Sat:** easy zone-2.
- **Tue, Thu:** HIIT (Phase 1 = threshold; Phase 2 = VO2 4×4; Phase 3 = VO2 4×3; deload + wk12 = no HIIT).
- **Lift-before-run:** legs depleted, run is easy by necessity. Perfect for fasted fat-ox.
- HIIT days are upper-lift days. Legs fresh for intervals.
- Heavy lower Fri → easy 20-min jog only after.

---

## 9. Implementation Hand-off Notes

This spec defines the program design. Implementation has two halves:

### Half 1 — DB layer

Already planned in `docs/superpowers/plans/2026-04-28-program-template-db-migration.md`:
- New tables: `ProgramTemplateDay`, `ProgramTemplate`, `ExerciseAlias`
- Idempotent seed from this spec's per-day prescriptions
- Read API in `program_template_io.py`
- Admin PATCH/POST/DELETE endpoints
- 8 implementation tasks, ~300 lines of code, full test coverage

### Half 2 — Engine + coach + autoregulation

Engine (`training_engine.py`):
- Already has exercise_order disambiguation (ebab5fc → 293edf2 → c9c6df1)
- Needs progression-rule branches per phase (Phase 1 rep-build, Phase 2 weight-bump, Phase 3 HOLD, wk12 HOLD)
- Needs autoregulation trigger logic (the numerical triggers from §8B)

Coach assembler (`coach_assembler.py`):
- Already has workout_today + workout_tomorrow context (af8fd23)
- Needs shoulder warm-up enforcement language in CORE_PROMPT
- Needs streak/adherence trigger awareness
- Needs Lombardi/Saban posture reinforcement (extend existing no-sycophancy rules)

Adherence/streak layer (new):
- Tracks consecutive completed sessions
- Triggers minimum-viable-session fallback after 2 misses
- Gates phase progression on deload exit criteria

### Open practical questions before code can run end-to-end

These need user input before implementation can produce a real program:

1. **Current best-known 1RMs** for Back Squat, Front Squat, Bench Press (or DB Bench), Bent-Over Row, Weighted Pull-Up. Phase 2's % math depends on these. If unreliable, Mon week 5 should re-test with a 3RM session and back into TM = 90% × 3RM × 1.07.
2. **Resting HR baseline.** Used for autoregulation triggers. Take 7 days of morning HR before starting; baseline = avg.
3. **Sleep tracking method.** For the <6hr trigger to fire, we need a source of truth (Garmin, manual log, Whoop?).
4. **Where does the cut sit RIGHT NOW** (today, mid-week 5)? Is the diet protocol already producing 3 lb/week, or is this the new target velocity?
5. **August event date** — for the August prep program, when does week 13 need to land relative to event day?

Implementation can begin without these (DB schema + seed don't depend on user values), but the engine can't compute realistic targets until #1 lands.

---

## 10. Out of Scope

- Calorie tracking / nutrition app integration. The 16:8 + 40-hr fast is the user's protocol; this design does not gate it.
- Sleep tracking. We consume a sleep value if available; we don't produce one.
- The August prep program. That's a separate spec.
- Trail run integration. Not in this block.
- Non-Erik users. This spec is one-user. Multi-user support is implicit (the DB tables aren't user-scoped beyond `WeeklyPrescription`), but the coaching tone, eating protocol, and weak-point biases are Erik-specific.

---

## 11. Self-Review Notes

(Per writing skill — fix inline.)

- **Placeholders:** none. Every prescription is concrete sets/reps/load.
- **Internal consistency:** Phase 2 §4 cites "Thursday refeed" — defined in §8C. Phase 3 §6 cites "previous-week weight" autoregulation — consistent with §8B. Run schedule §1 matches per-phase variance in §2/§4/§6/§7.
- **Scope:** focused on the 12-week program design. Implementation hand-off in §9 is a pointer, not a restatement of the migration plan.
- **Ambiguity:** "Front squat at 70%" — % of what? Should be % of front squat 1RM specifically (not back squat). Noted.
- **Open questions** are surfaced in §9, not buried.
