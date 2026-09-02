# Re-verification of the 165 audit closures — 2026-09-01

The 09-01 status doc says all 165 findings are closed. That claim was checked against the code at HEAD (072f5f0) by eight independent read-only reviews, one finding at a time, judging whether the audit's PROPOSED MECHANISM exists and whether a BEHAVIOR test pins it. Commit messages and the status doc were not trusted.

Trigger: S021 had been 'closed' by rewording an LLM prompt while the mechanism kept fabricating check-in scores in prod for 13 days (real fix 072f5f0; all fabricated rows nulled).

## Tally

| verdict | count | meaning |
|---|---|---|
| REAL | 73 | proposed mechanism present and pinned by a behavior test or equivalent proof |
| PARTIAL | 86 | mechanism partly present, or present but with no behavior test, or a weaker variant; the finding's headline may or may not still reproduce (see gap) |
| COSMETIC | 3 | wording/comment/allowlist change while the failing mechanism remains |
| NOT_DONE | 1 | nothing shipped |
| SUPERSEDED | 2 | moot after the 2026-08-30 deload decision |

By severity: critical 4 REAL / 1 PARTIAL; high 23 REAL / 15 PARTIAL / 1 COSMETIC; medium 36 REAL / 50 PARTIAL / 1 COSMETIC / 2 SUPERSEDED; low 10 REAL / 20 PARTIAL / 1 COSMETIC / 1 NOT_DONE.

The systemic failure is test coverage: most PARTIALs shipped real code but skipped the VERIFY_HOW test the audit specified, so nothing stops a regression. A minority left the finding's headline behavior intact.

## Still-live defects that matter most (fix first)

_Update, later 2026-09-01 (commit after 64880e6): the first eleven below are fixed with behavior tests in tests/test_reverification_fixes.py; see the table for each._

- **S036** [high, COSMETIC] — Closed against a different bug. Update Run with one blank field on a Garmin day still nulls it and sets source='manual', locking Garmin out (app.py:13500-13505). No merge branch, no test.
- **S132** [medium, PARTIAL] — move-sets-day untouched (GET, no dry_run/audit); realign still DROPS completed_at/workout_duration_min/source (app.py:2385-2390) — active data loss.
- **S053** [medium, COSMETIC] — app.py:4444 set-save falsy-zero site was ALLOWLISTED in the lint with a wrong justification instead of fixed; target_weight 0 still never reaches SetLog.
- **S139** [low, COSMETIC] — No GarminClient.usable(); the 3 live-fallback sites (coach_assembler.py:410, app.py:12140, app.py:9516) still trigger server-IP OAuth → 429 → daemon cooldown. Only dead routes deleted.
- **S134** [low, PARTIAL] — Server still asks Claude for 'Estimated body fat %' and 'Aesthetic score 1-10' (app.py:10119-10125) — fabricated metrics; sync 45s call.
- **S137** [low, PARTIAL] — weekly_review protocol (coach_assembler.py:2147) still tells the coach to INVENT a grade; codified verdict never shown to it; zero tests.
- **S069** [medium, PARTIAL] — 'good enough' demo hook still forces angry mode in prod: app.py:9154, app.py:9307, coach_assembler.py:2962-2966.
- **S089** [medium, PARTIAL] — tests/coach_audit/test_specialist_audit.py still makes a REAL paid API call under plain pytest with a key set (observed POST); users.py wrong prod host.
- **S148** [low, NOT_DONE] — No commit. missed_line still has no lower date bound; every untaken dose since Aug 10 listed on card and in every coach prompt (protocol.py:505-550).
- **S130** [medium, PARTIAL] — GET /api/sets unbounded dump still live (app.py:4541); test cannot catch it.
- **S138** [low, PARTIAL] — 20 str(e) sites remain; debug/workouts-error + goal-error still return tracebacks; coach bubble still yields raw errors.
- **S052** [medium, PARTIAL] — meal_generator 16_8 still 6:30pm; read filter hardcodes meal_hour>=19 (app.py:3776) → strips the 7:30pm meal on Oct 5.
- **S008** [high, PARTIAL] — Legacy /api/morning-briefing path (app.py:12189, app.js:6836) still bypasses ALL_SECTIONS.
- **S117** [medium, PARTIAL] — Decision half is prompt wording only (coach_assembler.py:2570-2575); no rule, no marker test. S021 shape.
- **S083** [medium, PARTIAL] — Headline untouched: thumbs-down CoachFeedback never reaches the coach (app.py:3040-3062); duration/navy BF/WeeklyReport still not in context.
- **S156** [low, PARTIAL] — Psych-intake 404 still silently dropped (app.js:4830-4858); no started_at/pruning on _intake_jobs.
- **S153** [low, PARTIAL] — Client-only gate; /api/garmin/login (app.py:10181) still open; Disconnect undone by refresher.
- **S154** [low, PARTIAL] — showGroceryList (app.js:5264,7042), d.notes 10586, mealOverride.note 11556 still raw innerHTML; no escape test.

## Every finding

| id | sev | verdict | gap |
|---|---|---|---|
| S148 | low | UPDATED | SUPERSEDED — bounded by the S061/S085 actionability filter (≤72 h); older misses are dropped, not listed. |
| S036 | high | UPDATED | FIXED — run edit merges fields, Garmin row keeps source, edit tagged in notes; test. |
| S053 | medium | UPDATED | FIXED — set-save and boot backfill use `is not None`; allowlist entries removed; test stores target 0. |
| S139 | low | UPDATED | FIXED — GarminClient.usable(); all three request-path fetches gate on it; test. |
| S004 | critical | PARTIAL | No invite expiry; core vector closed. |
| S007 | high | PARTIAL | Endpoint test is a source grep; no SWAP/SORENESS persistence tests. |
| S008 | high | UPDATED | FIXED — briefing runs on build_filtered_context/assemble_prompt/coach_chat; legacy _build_coach_context + get_coach_response DELETED; briefing no longer defaults missing check-in scores to 5 (hidden fake data); tests. |
| S009 | high | PARTIAL | apiPost has no timeout; stalled socket holds _setSaving. |
| S015 | high | PARTIAL | /logout still GET; no cookie-flag test. |
| S016 | high | PARTIAL | No rendered-prompt test; no rule 21a clause. |
| S017 | high | PARTIAL | Zero tests for timeouts/stale-job restart. |
| S019 | high | PARTIAL | Test covers empty case only, sets wrong cache var. |
| S020 | high | PARTIAL | Split-line test doesn't exercise app.js readers; no trailing-buffer flush. |
| S021 | high | PARTIAL | Real mechanism landed 072f5f0; still LLM extractor not [CHECKIN] marker. |
| S023 | high | UPDATED | FIXED — coach_rules uses program_calendar.program_week; grep test. |
| S028 | high | PARTIAL | Only runs healed; WeeklyDaySchedule gap persists forever; meals/warmups untracked. |
| S031 | high | PARTIAL | Sunday still dimmed (app.js:10378, style.css:4344); 'Monday check-in' copy at app.js:12426; grep-only test. |
| S035 | high | PARTIAL | Rendered prompt untested. |
| S037 | high | PARTIAL | No test for dead-token alert; laptop notify path unexercised. |
| S041 | high | PARTIAL | No prompt test for run_detail. |
| S045 | medium | PARTIAL | No render-sequence guard; rest timer still orphaned on re-render (app.js:2046-2079). |
| S046 | medium | PARTIAL | No chase test; morning brief still counts scheduled not unchecked doses. |
| S047 | medium | PARTIAL | Zero tests for max_hr path; per-lap splits (step 2) not started. |
| S049 | medium | PARTIAL | No expiry: exceptions/commitments listed under CRITICAL forever (coach.py _format_memories). |
| S052 | medium | UPDATED | FIXED — 16:8 read filter honours the rail note's cutoff; test. |
| S054 | medium | PARTIAL | Clamp real; no test; heal-prescriptions not clamped. |
| S056 | medium | PARTIAL | Tripwire test not added. |
| S058 | medium | PARTIAL | Strength planner still blind to HRV/RHR/sleep; decision rule not written; no test. |
| S059 | medium | PARTIAL | No test; adherence_7d still excludes today. |
| S060 | medium | PARTIAL | No note input on weigh-in strip; only latest event surfaced; no events_last_10d. |
| S062 | medium | PARTIAL | Only basicConfig; app.py:9311 context-build failure still no traceback; weekly-report thread swallows silently; garmin DEBUG spam now prints at INFO. |
| S067 | medium | PARTIAL | Run PLANNER history block still has no pace/peak HR (coach_planning_runs.py:44-58); no test for max_hr mapping. |
| S069 | medium | UPDATED | FIXED — 'good enough' hook deleted from both chat paths and the assembler; test. |
| S071 | medium | PARTIAL | 10 _anthropic_client copies + model literals in 8 files remain; test only greps 4 stale spellings (cannot fail on the real condition). |
| S072 | medium | PARTIAL | Client still refetches whole /api/workouts after swaps (app.js:5558); no query-count test. |
| S073 | medium | PARTIAL | checkOnboardingComplete still 6 GETs/load; no onboarding_complete flag; retest status still fetched; no request-count pin. |
| S076 | medium | PARTIAL | Sunday recap text still lacks lifts_done/planned and weigh-ins/7 (weekly_report.py:395-420); no test. |
| S079 | medium | PARTIAL | schedule rows still written for all 7 days source='engine'; [DAY_SCHEDULE] not taught in markers; no S079 test. |
| S083 | medium | UPDATED | FIXED — last 10 CoachFeedback flags rendered as 'flagged' memories; test. |
| S086 | medium | PARTIAL | PR detection still all-time; no test. |
| S087 | medium | PARTIAL | Two copies of field list; scoreboard Tape delta unlabeled. |
| S089 | medium | UPDATED | FIXED — specialist smoke test carries live_llm marker (skipped without --live-coach). |
| S091 | medium | PARTIAL | No secret-scan guard. |
| S093 | medium | PARTIAL | No test for the N+1 case; client posts currentWeek. |
| S094 | medium | PARTIAL | No test; all-None fetch still counts as successful sync. |
| S096 | medium | PARTIAL | No temperature test; specialists not threaded. |
| S098 | medium | PARTIAL | No prompt test; SUNDAY_REVIEW trigger text still dictates narrative. |
| S099 | medium | PARTIAL | No intake_profile table test. |
| S100 | medium | UPDATED | FIXED — lifting_agent uses lift_history.e1rm; grep test. |
| S101 | medium | UPDATED | FIXED — canonicalization one-shot behind SystemFlag name_aliases_v1; dead exercise_log UPDATE removed. |
| S103 | medium | PARTIAL | Memo unpinned by any test. |
| S104 | medium | PARTIAL | 3 of 28 LLM sites instrumented; no LlmUsage table/endpoint. |
| S106 | medium | PARTIAL | 500-row scan remains; no test. |
| S107 | medium | PARTIAL | No test; NULL logged_date fallback. |
| S108 | medium | PARTIAL | Gate duplicated in two files; no test. |
| S110 | medium | PARTIAL | No thread test. |
| S114 | medium | PARTIAL | Calendar has no change field; no seeded test. |
| S116 | medium | PARTIAL | coach.py:237 still 'engine-computed targets'; CORE rule 9 says 'training engine' while rule 18 bans it; Tesamorelin rationale unconditional. |
| S117 | medium | PARTIAL | Decision half is prompt wording only (coach_assembler.py:2570-2575); no rule, no marker test. S021 shape. |
| S119 | medium | UPDATED | FIXED — swap overlay failure logged + reported in _overlay_errors (domain 'swap'). |
| S121 | medium | UPDATED | FIXED — run planner history cites activity_type/activity_name; test. |
| S122 | medium | PARTIAL | Shipped under S024; no test. |
| S123 | medium | PARTIAL | coach_multi_agent.py:421,563 + specialists send no temperature; no test. |
| S124 | medium | PARTIAL | _fetch_week_program still re-resolves 7 days; claims block ungated. |
| S127 | medium | PARTIAL | Judge pass still serial full-price messages.create; no Batch API. |
| S128 | medium | PARTIAL | Local week-formula copy; no test for the schedule-row-no-prescription case. |
| S129 | medium | PARTIAL | Athlete's 'yes' confirmations now never persisted anywhere. |
| S130 | medium | UPDATED | FIXED — GET /api/sets deleted (no caller); test asserts 405. |
| S131 | medium | PARTIAL | No test; _swapped_from key still unread. |
| S132 | medium | UPDATED | FIXED — realign copies completed_at/workout_duration_min/source. |
| S134 | low | UPDATED | FIXED — photo prompt no longer asks for body-fat % or an aesthetic score; test. |
| S135 | low | UPDATED | FIXED — same as S134 (dead render chain still present). |
| S136 | low | PARTIAL | Chat coach never sees the Z2 trend (coach_assembler has no aerobic hit). |
| S137 | low | UPDATED | FIXED — <week_verdict> rendered from the codified verdict; weekly_review GRADE must repeat it, never invent; test. |
| S138 | low | UPDATED | PARTIAL→ traceback endpoints now admin_required; ~20 str(e) sites remain. |
| S141 | low | PARTIAL | No test. |
| S142 | low | PARTIAL | Count-only assertion, magic +20 window. |
| S143 | low | PARTIAL | In-process throttle (per worker, resets on deploy); no test. |
| S144 | low | PARTIAL | Logout never clears CacheStorage on login.html. |
| S145 | low | PARTIAL | todayStr() 76 sites incl. popup keys + bodyweight POST dates — two clocks still disagree on travel days. |
| S146 | low | PARTIAL | CSS only; 18 div-onclick controls, ~no aria, 4/50 labels. |
| S147 | low | PARTIAL | index.html:103 still nukes all caches every load; offline launch impossible; push url ignored. |
| S152 | low | PARTIAL | lift_trend still calls lift_session_history per KEY_LIFT (~10 queries); no from_rows helper. |
| S153 | low | UPDATED | FIXED — /api/garmin/login 404s on Render without the admin key; test. |
| S154 | low | UPDATED | FIXED — grocery list, coach note, meal-override note escaped. |
| S155 | low | UPDATED | FIXED — coach layer keeps 80 rows. |
| S156 | low | UPDATED | FIXED — intake 404 surfaces as an error bubble, never a silent drop. |
| S160 | low | PARTIAL | 13 user_id columns still nullable; no SET NOT NULL. |
| S163 | low | PARTIAL | Specialists still max_retries=5 no timeout; no test. |
| S165 | low | PARTIAL | Three host_url fallbacks remain (app.py:3394,3466,3550); no test. |
| S088 | medium | SUPERSEDED | Deload-by-week abolished 2026-08-30; workout_data.py:1985/2037 dead literal. |
| S095 | medium | SUPERSEDED | Same as S088. |
| S001 | critical | REAL | No restore drill. |
| S002 | critical | REAL | Only detector pinned, not dashboard verdict. |
| S003 | critical | REAL |  |
| S005 | critical | REAL | Test spies the call, not persistence; anger/memory still stream-only. |
| S006 | high | REAL |  |
| S010 | high | REAL | app.py bounds untested. |
| S011 | high | REAL |  |
| S012 | high | REAL |  |
| S013 | high | REAL |  |
| S014 | high | REAL |  |
| S018 | high | REAL |  |
| S022 | high | REAL | No self_reported flag. |
| S024 | high | REAL |  |
| S025 | high | REAL | No one-tap glutened chip in UI. |
| S026 | high | REAL | Calendar-week not block-week regen; no test for recalibration branch. |
| S027 | high | REAL |  |
| S029 | high | REAL |  |
| S030 | high | REAL |  |
| S032 | high | REAL | Render deploy not gated on CI. |
| S033 | high | REAL |  |
| S034 | high | REAL |  |
| S038 | high | REAL | Historic body_battery rows not backfilled. |
| S039 | high | REAL | Settings button still offered, now 409s. |
| S040 | high | REAL |  |
| S042 | high | REAL | Grep-only test. |
| S043 | high | REAL |  |
| S044 | high | REAL |  |
| S048 | medium | REAL | source not in GET payload. |
| S050 | medium | REAL | CSS-only, no size assertion. |
| S051 | medium | REAL | No hero chip; no test. |
| S055 | medium | REAL | dup of S050. |
| S057 | medium | REAL |  |
| S061 | medium | REAL | Pure-function test only. |
| S063 | medium | REAL | vo2 days still get no timer. |
| S064 | medium | REAL | No today= kwarg / clock-drift test; freeze helper still in tests. |
| S065 | medium | REAL | Other pure-helper tests not added. |
| S066 | medium | REAL | MEALS_COMPLETE still de-escalates as completed_workout (app.py:9208); LOCKOUT_WARNING only writes a memory row. |
| S068 | medium | REAL |  |
| S070 | medium | REAL | No import-cycle invariant test. |
| S074 | medium | REAL | Endpoint behavior unit-tested only. |
| S075 | medium | REAL | No test for multi-statement rejection / READ ONLY txn (sqlite no-op). |
| S077 | medium | REAL | No prompt-content test. |
| S078 | medium | REAL |  |
| S080 | medium | REAL | No planner test that long run lands on the committed day. |
| S081 | medium | REAL | Prescribed e1RM still headline when nothing logged (labeled). |
| S082 | medium | REAL | No floor-path test; client may render floor day like a coach prescription (no 'floor' pill). |
| S084 | medium | REAL | app.py:4179 still serves dead phaseInfo; no DOM test. |
| S085 | medium | REAL | 72h filter, no 'N earlier missed' summary. |
| S090 | medium | REAL | Unit test only. |
| S092 | medium | REAL |  |
| S097 | medium | REAL | week_program not threaded. |
| S102 | medium | REAL | No auto-dedupe migration. |
| S105 | medium | REAL | No [SCHEDULE: skip] marker. |
| S109 | medium | REAL | No test. |
| S111 | medium | REAL | No conflict test. |
| S112 | medium | REAL | reset-password still accepts 6-char explicit password. |
| S113 | medium | REAL |  |
| S115 | medium | REAL | Detail only after tap. |
| S118 | medium | REAL | No 'show earlier'. |
| S120 | medium | REAL | No test; old rows keep wrong date. |
| S125 | medium | REAL | No test. |
| S126 | medium | REAL | Older misses vanish entirely, no residual count. |
| S133 | medium | REAL |  |
| S140 | low | REAL |  |
| S149 | low | REAL |  |
| S150 | low | REAL | No ordering test. |
| S151 | low | REAL | No golden equality test. |
| S157 | low | REAL | DeprecationWarning blanket-ignored. |
| S158 | low | REAL | No skip-allowlist guard. |
| S159 | low | REAL | No test. |
| S161 | low | REAL | No test. |
| S162 | low | REAL | Two spellings of the BW sentinel in one prompt; no test. |
| S164 | low | REAL | No test. |
