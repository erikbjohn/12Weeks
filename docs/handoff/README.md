# 12Weeks — Engineering handoff (2026-08-29)

> **2026-09-01 update:** read `HANDOFF-2026-09-01.md` first. All 165 findings below are closed; the open-items list in `product-intent.md` is superseded by its §4. The system description here is still accurate.

This folder is a complete handoff for a new engineering team. It was written by the outgoing AI assistant at the owner's request after a failed multi-agent audit run on 2026-08-28. Everything below is stated from the code, the production database, Render logs, and the owner's recorded decisions — not from memory. Where something is unverified it says so.

**Files in this folder**

| File | What it is |
|---|---|
| `README.md` | This document: system, access, current state, incidents, open work, how to proceed |
| `product-intent.md` | The owner's goals, **binding decisions**, recurring failure classes, open items, working preferences (56 KB) |
| `memory-export.md` | Verbatim export of 63 decision/preference memory files that lived outside the repo (143 KB). Read `MEMORY.md` section first — it is the index |
| `findings-2026-08-29.md` | 165 deduplicated improvement findings with file:line evidence — **unverified leads**, grouped by severity (508 KB) |
| `findings.json` | Same, machine-readable |
| `subsystem-maps.md` | 17 structured maps of the codebase: entry points, flows, invariants, smells, risks (771 KB) |

Also read, in the repo: `tasks/RESTART.md` (prior handoff notes through 2026-07-02), `docs/whole-app-audit-2026-07-01.md` (114-agent audit, 106 findings, all fixed 2026-07-02), `docs/spec-rev2-peptide-protocol-2026-08-10.html` (block-3 spec), `CLAUDE.md` in the parent directory (working rules the owner holds his engineers to — read them; they are strict and they are the standard).

---

## 1. What this is

A single-athlete training app. The athlete is also the owner and product designer: **Erik**, `erik@placemetry.com`, `user_id 1` in the app. (His Gmail is the Garmin/Render login, not an app user.) Behavioral economist; rooftop home gym in Pacific Beach with limited equipment; runs every day of the week; Garmin watch; on a 12-week doctor-prescribed peptide protocol tracked in-app; bad eyesight (large fonts, high contrast, 44 px targets are requirements, not preferences).

Product thesis: an AI coach that **"aligns aspirations with actions"** — flat, data-driven, never sycophantic, never contradicts the UI or itself, never invents a rationale, coaches the weight cut daily and reacts to the scale, and **codifies every decision into data** (a coach statement that is not written to the plan is a bug). Program stability is a first-class requirement equal to coaching quality; the owner burned out being QA for his own coach in block 1.

He is currently in **Block 3** (2026-08-10 → 2026-11-01), a recomp cut from 220 lb to 195 lb on a piecewise curve tied to the peptide ramp, with lift performance required to hold. Week 3 as of this document. He plans one week at a time, on Sundays. **Do not pre-build future weeks. Do not deploy while a planning run is in progress. Do not touch the live week's data.**

## 2. Stack and where things run

- **Backend:** Flask + SQLAlchemy, `app.py` (13.3k lines, 185 routes) plus ~30 modules. Python 3.12 on Render; local venv is Python 3.14 (`venv/`).
- **Frontend:** vanilla-JS PWA, `static/app.js` (13.6k lines), `static/style.css`, `static/sw.js`, `templates/index.html`. Assets are hash-cache-busted via `asset_url()`; `index.html` is `no-store`.
- **Coach:** Anthropic API. Chat is Opus 4.8 with tools (`coach_with_tools.py`); context is assembled by `coach_assembler.py` (2.8k lines; every athlete-facing agent must get every section — see decisions). Weekly planning agents in `coach_planning_*.py`. Model ids are pinned in several places with different spellings (finding S071).
- **Data:** Postgres on Render (`12weeks-db`, `render.yaml` declares plan `free` — confirm the plan and expiry policy in the dashboard). Schema in `models.py`; migrations are ad-hoc `ALTER TABLE` statements run at import time in `app.py` (see findings S044/S101/S160 — some of that boot block is destructive). **There is no database backup of any kind** (finding S001, critical). `/api/export` exists but is lossy.
- **Garmin:** `garmin_client.py`, `garmin_sync.py`; a 30-minute autosync daemon thread in `app.py`; a laptop-side token refresher (section 5).
- **Protocol:** `protocol.py` + `peptide_protocol.csv` (363 rows as of 2026-08-24; the tests still assert 312 — see section 7).
- **Push:** Web Push with a 5-minute scheduler daemon in `app.py` (morning brief, dose-night, Sunday recap).
- **Tests:** `venv/bin/python -m pytest -q -p no:cacheprovider` (≈6 s, 1009 tests) and `npx vitest run` (20 tests). No CI, no pre-push hook (finding S032).

### Production

- URL: **https://one2weeks-9ewf.onrender.com** (not `12weeks.onrender.com`).
- Render service **`12Weeks`**, id `srv-d741jechg0os739r4im0`, workspace `placemetry`, plan `starter`, 1 instance. Auto-deploys on push to `main`. Deploy takes ~2–4 minutes; confirm with `GET /api/debug/health` → `{"commit": "<sha>", ...}`.
- Dashboard env (names only): `ADMIN_API_KEY, ANTHROPIC_API_KEY, APP_URL, DATABASE_URL, FORWARDED_ALLOW_IPS, GOOGLE_API_KEY, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GUNICORN_CMD_ARGS, MULTIAGENT_ENABLED, SENDGRID_API_KEY, SENDGRID_FROM_EMAIL, WEB_CONCURRENCY`.
- **The dashboard start command is bare `gunicorn app:app`, and `GUNICORN_CMD_ARGS='--preload --access-logfile - --bind=0.0.0.0:10000'`, `WEB_CONCURRENCY=1`.** `render.yaml`'s `--timeout 300` and `Procfile` are **not** what runs: the real request timeout is gunicorn's default 30 s, and `--preload` means import-time daemon threads run in the gunicorn *master* while requests are served by the *worker* — two processes, two in-memory states. This caused the Garmin incident (section 6).
- Logs: `render logs -r srv-d741jechg0os739r4im0 --type app --start <RFC3339> --end <RFC3339> --text "a,b" -o json --confirm` after `render login` (device-code flow; the CLI token expires). App `INFO` logs are **not** emitted in prod (no logging config; root logger is WARNING) — only warnings, errors and gunicorn's own lines (finding S062).

### Admin and diagnostics (no browser, no LLM cost)

All `/api/admin/*` and `/api/debug/*` routes except `/api/debug/health` require header `X-Admin-Key: <ADMIN_API_KEY>` or an admin session. Useful:

- `POST /api/admin/debug/sql {"sql":"SELECT …"}` — read-only by a prefix check only (finding S133: a second statement after `;` executes). `POST /api/admin/debug/exec` — writes.
- `GET /api/debug/serve-as-user?email=…&path=/api/workouts` — the exact payload the athlete's UI receives (allowlisted paths). This is how to verify "what he sees" — the owner's rule is to audit served values, never raw rows.
- `GET /api/debug/today-status|full-day-state|api-workouts-as-user|show-sets?email=…` — what the coach is actually fed.
- `POST /api/admin/garmin/save-tokens {"email","tokens"}` — upload a garth token dump; the server restores the session and syncs immediately.
- `POST /api/admin/heal-prescriptions`, `/api/admin/replan-week`, `/api/admin/import-protocol` — see `subsystem-maps.md`.

**The admin key must be rotated on day one.** Its current value is the literal committed in `tasks/RESTART.md:79` (finding S003). Set a new value in the Render dashboard, write it to `~/.12weeks_admin_key` (0600) on the owner's laptop (the Garmin refresher reads it from there), and share it out-of-band. Also review S004 (invite acceptance can overwrite an existing account's password), S015 (destructive GET routes, no cookie flags/CSRF), S090 (any `@placemetry.com` mailbox self-registers as admin).

## 3. Non-negotiable rules from the owner

The full list with sources is in `product-intent.md` → *Decisions*. The ones a new team will trip over first:

1. **Codify, never advise.** Coach decisions must be written to data via structured markers (`[SWAP]`, `[SCHEDULE]`, `[NUTRITION]`, `[RUN]`, `[WEIGHT]`, `[PRESCRIPTION]`) or tools. Note finding S005: only the streaming chat path parses markers today.
2. **No static templates, no silent fallbacks.** A plan is coach-or-nothing. If a coach fails, the card says so (`coach_failures`); the engine never backfills. Exception the owner accepted: the run planner's 7-day floor — but see S082.
3. **Every athlete-facing agent gets every context section** (`ALL_SECTIONS`, commit `17fdc6a`). This was lost five times by hand-narrowing `requires` lists. Never narrow it; never write a test that an agent *lacks* a section.
4. **Every exercise ≥ 3 working sets, deload weeks included** (`MIN_SETS`, `7e9c02e`). A 2-set slot on a card is a bug.
5. **Volume trends up across the program** (sawtooth: deload *weeks* 4/8/12, never a deload *phase*). This superseded an earlier "Phase-3 hold" decision — the later one wins.
6. **He runs all 7 days.** A runless day in a plan is a bug. Saturday El Cajon Mountain trail run at least every other week.
7. **Main-page Stats are phase-scoped (this block only); Progress is all-time; never scope `/api/weights`.**
8. **Weekly planning stays asynchronous** (background job + client polling). Making it synchronous 502'd and destroyed weeks.
9. **Do not pre-bake future weeks; do not re-run planning to "see" a saved week** (`force_regen` deletes first).
10. **Garmin: never retry-loop the auth endpoint.** One controlled knock per 30-minute tick, from the daemon only. Deploys used to cost a Garmin login; be sparing.
11. **Gluten events** (5–8 lb of water over 1–2 weeks) are never coached as a failed cut. The current guard only holds for one day (S002, critical).
12. **Zero UI contradictions**: no two surfaces may disagree; verify on the served payload as the user.
13. **Protocol dose edits go to the prod DB immediately** via `debug/exec`; the CSV push follows. Never make him wait on a deploy for a schedule change.
14. **Bulk model calls use the Batch API** with presigned inputs — a standing rule across all his projects (see `CLAUDE.md` in the parent directory).
15. **Readability**: ≥16 px body, 44 px tap targets, high contrast. The set checkbox is 24 px today (S050).

## 4. State of the code (2026-08-29 ~00:30 ET)

- Branch `main`, HEAD **`548fb4e`** — deployed and confirmed live (`/api/debug/health` reports it).
- Working tree: this `docs/handoff/` folder is new and uncommitted. There are also many untracked scratch files at repo root (`*.png`, `wk10-*.json`, `scripts/check_*.py`, `scripts/preview_*.py`, `scripts/repro_planning_yes.py`) — safe to delete; **note S091: three of those untracked scripts scrape `sk-ant-` keys out of local transcripts — delete them.**
- Test suite on `548fb4e`: **933 passed, 5 failed, 71 skipped.** The five failures are pre-existing and unrelated to the last commit (section 7).
- Last five commits: `548fb4e` Garmin token clobber fix (2026-08-28); `17fdc6a` restore ALL_SECTIONS; `4a45e43` every agent sees scale + Garmin; `0860452` phase-scoped Stats; `dd436d3` evidence-based streak.

## 5. The Garmin lifeline (fragile — understand before touching)

Garmin Connect's OAuth2 token lives ~19–26 h. Refreshing it requires garth to run an OAuth1-signed *exchange*, and **Garmin rate-blocks that endpoint from Render's IP (429) while allowing it from the owner's laptop**. So:

- Tokens are minted/refreshed on the **owner's Mac** by a launchd job `com.12weeks.garmin-refresh` (`scripts/com.12weeks.garmin-refresh.plist`, runs `scripts/garmin_refresh_upload_auto.py` every 6 h + at login). Token file `~/.garmin_tokens.json` (0600); log `~/Library/Logs/garmin-refresh.log`; admin key `~/.12weeks_admin_key`. Fresh mint with MFA: `garmin_token_helper.py` (MFA code arrives in the owner's Gmail).
- The script uploads via `POST /api/admin/garmin/save-tokens`; as of `548fb4e` it uploads on **every** run (it used to trust a local marker).
- Server side: `garmin_client.py` holds one `GarminClient` per user per **process**; `try_restore_tokens` refuses the exchange when the stored token is expired unless called by the daemon; 429 → 900 s cooldown; the daemon (`_garmin_autosync_tick`, app.py ~10236) pulls activities + wellness every 30 min, first tick 30 min after boot.
- If the laptop is closed for >~24 h, sync dies until it wakes. **There is no failure signal** other than the Settings panel (finding S037). Runs still land when the athlete opens the app *if* the worker process has a valid token.
- Push of structured workouts to the watch happens only after weekly planning or via `POST /api/garmin/push-week` (login-required, manual). Rails: any rail that rewrites a run's detail must rewrite `segments_json`; prose wins on contradiction (`5e71317`).

## 6. Incident 2026-08-28 (resolved) — the split-brain token clobber

**Symptom:** the athlete's 18:28 ET run sat in Garmin Connect for 90 minutes while the app showed nothing, despite a valid token.

**Root cause (proven from Render logs + a local `--preload` repro):** with `--preload`, the autosync daemon thread lives in the gunicorn master; the token upload is handled by the worker. Worker loads fresh token Tn and writes it to the DB. Master's next tick still holds T(n-1) (valid), syncs, then `persist_tokens_if_changed` sees "my dump ≠ row" and **overwrites the DB with the older token**. When T(n-1) expires, every master tick knocks the exchange → 429 → cooldown, until the next laptop upload. Logs show this burst on Aug 25 (8 h), Aug 27 (twice), Aug 28 — the daemon was dead 5–8 h/day, masked because the worker kept the fresh token and the athlete's page loads pulled the runs. Two deploys on Aug 28 restarted both processes *after* the clobber, so both restored the stale token; page loads then 503'd silently.

**Fix shipped `548fb4e`:** `persist_tokens_if_changed` is monotonic (never regresses to an older `expires_at`); new `GarminClient.stored_token_is_newer()`; the tick and `/api/garmin/sync-activities` reload from the DB when the stored token is newer; refresher uploads every run. Contract pinned in `tests/test_garmin_token_monotonic.py` (9 tests).

**Watch after 2026-08-29 03:21 ET** (next laptop upload): `garmin_tokens.updated_at` must not be rewritten with an older-expiry token by the ~03:53 tick, and there must be no `oauth/exchange` 429 burst around 09:53 ET.

**Related, not fixed:** every tick logs `Garmin fetch tr_<date> failed: 'list' object has no attribute 'get'` — the training-readiness endpoint now returns a list; training readiness is never stored (`garmin_client.py` `_get_training_readiness`). One 30 s `WORKER TIMEOUT` kill on Aug 25.

## 7. Known-broken right now

1. **5 failing tests (pre-existing):** `tests/test_block3_guards.py::…::test_peptide_protocol_csv_integrity` and three in `tests/test_protocol_import.py` assert a 312-row protocol CSV; the CSV has 363 rows since the 2026-08-24 protocol edits (`715497f`, `7fc9106`, `ecc06a5`) and the guards were last bumped 2026-08-19. Update the expected counts after confirming the rows are intended. `tests/test_i3_i4_fixes.py::test_legacy_user_no_flags_old_ratio_logic_intact` is a clock-bomb (finding S064: `weekly_report.compute_weekly_metrics` windows on server `date.today()`).
2. **No database backup** (S001). Do this first: `pg_dump --format=custom` from the Render external URL on a schedule, off-box.
3. **Leaked admin key** (S003) — rotate (section 2).
4. **Training readiness never stored** (section 6).
5. **Real gunicorn timeout is 30 s, not 300** — long requests (planning, weekly report) rely on background jobs; anything synchronous over 30 s gets SIGKILLed and the daemon clocks reset.

## 8. What the 2026-08-28 audit produced, and what it did not

An automated 15-lens code audit ran three times on 2026-08-28. Discovery completed (17 subsystem maps, 1,006 raw findings → 165 unique after script dedup). The adversarial verification, planning and synthesis stages **never completed** — two runs halted on exhausted usage credits, one on a 64k output-token cap, and a relaunch re-executed cached work. The owner paid for this and received no plan; that failure is documented in the assistant's feedback queue and is the reason for this handoff.

What survives is in `findings-2026-08-29.md` / `findings.json` and `subsystem-maps.md`. **Every finding is an unverified lead** with a file:line the finder opened. In the July 2026 audit, roughly a third of raw findings were refuted on verification; expect a similar rate. The critical/high items were spot-checked by hand before writing this document and the following were confirmed against the code at `17fdc6a`/`548fb4e`:

- S003 admin key literal in `tasks/RESTART.md:79`; compared via `os.environ.get('ADMIN_API_KEY')` at `app.py:107`.
- S004 invite-accept POST assigns `existing.password_hash = generate_password_hash(password)` for a pre-existing account (`app.py` ~3079–3095).
- S005/S007 `_parse_coach_markers` has exactly one call site (`app.py:9249`, the streaming path).
- S015 `/restart-plan`, `/redo-measurements`, `/redo-equipment`, `/reset-onboarding` are GET routes (`app.py:3422–3463`); no `SESSION_COOKIE_*`/`SameSite` config anywhere in `app.py`.
- S009/S014 `apiPost` (`static/app.js:1006–1032`) logs non-OK responses with `console.error` and does not roll back or queue.
- S016/S035 `curve_target_today` / `on_curve` are computed and returned by `_build_cut_status` (`coach_assembler.py:953–982`) — whether they are rendered into the prompt was not re-checked by hand.
- S017 `coach_planning_program.py:61` constructs `anthropic.Anthropic(api_key=…, max_retries=3)` with no timeout.
- S031 Sunday hero literal "Rest Day / Streak mile only · Recovery · Hydrate" at `static/app.js` ~10038–10044.
- S032 no `.github/`, no `.git/hooks/pre-push`, no `pytest.ini`/`pyproject.toml`.
- S039 `POST /api/state` writes `start_date` verbatim with no validation (`app.py` ~4154).
- S011/S030 `protocol.py:254` filters escalations to `compound == "Retatrutide"`.
- S062 no `logging.basicConfig`/`dictConfig` anywhere in `app.py`.

Not hand-checked: everything else. S001 (no backup) and S002 (gluten guard = last 3 rows) were checked at the cited lines and look right but were not exercised.

## 9. Suggested first two weeks (opinion, from the confirmed items only)

Sequence for the live block: nothing that touches the current week's rows; deploy at most once a day, never during Sunday planning (~afternoon, owner's local time, America/Indianapolis in the app).

1. Off-box `pg_dump` on a schedule (S001). Rotate the admin key (S003). Delete the key-scraping scratch scripts and `cookies.txt` (S091). Set cookie `SameSite=Lax; Secure` and convert or delete the four destructive GET routes (S015). Fix invite-accept password overwrite (S004).
2. Add a CI workflow running pytest + vitest on push (S032); fix the 5 red tests (section 7).
3. Non-OK `/api/sets` responses must roll back the checkmark and queue (S009/S014) — this is the athlete's most-tapped control.
4. Call `_parse_coach_markers` from the non-streaming chat path too (S005/S007) — otherwise a whole class of coach decisions is advisory-only, which violates rule 1.
5. Render the block-3 curve verdict into the coach's `<cut_status>` (S016/S035) so the coach and the scoreboard judge the same thing (rule 12).
6. Extend the gluten/water-spike guard to a multi-day window (S002) — this is the failure the owner named as *the* block-1 failure.
7. Everything else: work down `findings-2026-08-29.md` by severity, verifying each at the cited lines first.

## 10. Runbook snippets

```bash
# tests
venv/bin/python -m pytest -q -p no:cacheprovider
npx vitest run

# prod health / commit
curl -s https://one2weeks-9ewf.onrender.com/api/debug/health

# read-only SQL (admin key from the Render dashboard, NOT from any file in this repo)
curl -s -X POST https://one2weeks-9ewf.onrender.com/api/admin/debug/sql \
  -H "X-Admin-Key: $ADMIN_API_KEY" -H "Content-Type: application/json" \
  -d '{"sql":"SELECT id,week,day_idx,log_date,source,distance_miles FROM run_log WHERE user_id=1 ORDER BY log_date DESC LIMIT 7"}'

# what the athlete's UI is served
curl -s "https://one2weeks-9ewf.onrender.com/api/debug/serve-as-user?email=erik@placemetry.com&path=/api/workouts" -H "X-Admin-Key: $ADMIN_API_KEY"

# Garmin: what Garmin has vs what prod pulled (laptop, no exchange)
venv/bin/python -c "import garth,os;garth.client.loads(open(os.path.expanduser('~/.garmin_tokens.json')).read());print(garth.connectapi('/activitylist-service/activities/search/activities',params={'startDate':'2026-08-27','endDate':'2026-08-30','limit':10,'start':0}))"

# Render logs (after `render login`)
render logs -r srv-d741jechg0os739r4im0 --type app --start 2026-08-28T22:00:00Z --end 2026-08-29T01:00:00Z --limit 500 --direction forward -o text --confirm
```

## 11. Program calendar facts

- `AppState.start_date` = 2026-08-10 (Monday). Week N = start + 7·(N−1); `day_idx` = weekday, Mon = 0. Weeks 1–12 of block 3 are stored as weeks 1–12; **block 1 history is parked at weeks 25–36 and block 2 at 13–18** in the same tables (transition 2026-08-10). Several queries still read parked rows as "recent" (S010, S034, S040).
- Deload weeks: 4, 8, 12 — but the constant is duplicated and drifts across files (S088/S095).
- App timezone for the athlete: `America/Indianapolis` (user row); the server runs UTC. Date bugs are a recurring class (S110, S120, S145).
- Source of truth for lifts is `SetLog` (`ExerciseLog` is dead). Runs: `RunLog` (source `garmin` | manual). Plans: `WeeklyPrescription`, `WeeklyRunPlan`, `WeeklyMealPlan`, `WeeklyDaySchedule`. Doses: `PeptideDose` (+ `taken_at`). Weight: `BodyWeight` (daily strip). Coach memory: `CoachMemory`, `CoachRule`.
