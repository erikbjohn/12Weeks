# Garmin Wellness History + Header Strip Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist daily Garmin wellness (sleep, HRV, body battery, readiness, stress, resting HR, VO2max) and show today's numbers as a four-chip strip at the top of the day view.

**Architecture:** New `GarminWellness` daily table filled by `garmin_sync.sync_wellness()`, called from the existing throttled `/api/garmin/sync-activities` flow (today refreshed each sync; missing past days backfilled once, capped 14). A DB-only `GET /api/garmin/wellness` endpoint feeds the rebuilt `renderGarminBar()` strip — which reuses the dormant `.garmin-bar` CSS and existing render call site.

**Tech Stack:** Flask + SQLAlchemy, `garminconnect==0.2.40`, pytest, vanilla JS (inline-styled chips, existing CSS grid).

**Spec:** `docs/superpowers/specs/2026-06-12-garmin-wellness-history-design.md`

**Verified facts (do not re-derive):**
- `garminconnect` 0.2.40 has `get_rhr_day(cdate)` → dict; RHR value at `allMetrics.metricsMap.WELLNESS_RESTING_HEART_RATE[0].value`.
- `GarminClient` per-day getters already exist and return clean dicts: `_get_hrv(day)`, `_get_sleep(day)`, `_get_body_battery(day)`, `_get_training_readiness(day)`, `_get_training_status(day)`, `_get_stress(day)` (garmin_client.py:174-266), all via `_cached` (per-day keys, returns None on failure). `_rate_limited_until` is the rate-limit state.
- `renderGarminBar()` stub at static/app.js:9248 is ALREADY CALLED from the render path (app.js:9077) — rebuilding the body is sufficient, no new call wiring.
- `.garmin-bar` (padding/border/surface) and `.garmin-metrics` (auto-fit grid, minmax 90px) CSS survive at style.css:75-105.
- index.html line 71 is the slot: `<!-- Garmin removed -->`.
- The auto-pull fire-and-forget block + run-log cache fetch live at app.js ~5272-5285 (added by the activity-sync feature).
- `/api/garmin/sync-activities` endpoint exists (app.py, after garmin_logout); result dict from `garmin_sync.sync_activities`. `_user_today()` app.py:905. `timedelta` imported at app.py:11.
- Migration mechanism: `db.create_all()` creates NEW tables at boot — a new table needs NO `_migrations` entry.
- Test style: `tests/test_garmin_sync.py` has module-scoped `app_ctx`, `_mk_user`, `FakeGC` helpers — extend, don't duplicate.
- Honesty rules: NULL = "Garmin had nothing", never 0; the strip never shows invented/stale-as-fresh values; falsy-zero discipline (sleep_seconds 0 → NULL).

---

### Task 1: GarminWellness model

**Files:**
- Modify: `models.py` (after `GarminWorkoutLink`, ~line 392)

- [ ] **Step 1: Add the model**

```python
class GarminWellness(db.Model):
    """One row per user per date: daily wellness snapshot pulled from Garmin.
    All metric columns nullable — NULL means Garmin had nothing for that
    metric/day (never 0). Today's row is refreshed by each sync; past days are
    written once (an all-NULL row marks 'checked, nothing there' and stops
    re-fetching)."""
    __tablename__ = "garmin_wellness"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False)
    sleep_seconds = db.Column(db.Integer)
    sleep_score = db.Column(db.Integer)
    hrv_last_night = db.Column(db.Integer)
    hrv_weekly_avg = db.Column(db.Integer)
    hrv_status = db.Column(db.String(20))
    body_battery = db.Column(db.Integer)
    training_readiness = db.Column(db.Integer)
    training_status = db.Column(db.String(30))
    vo2max = db.Column(db.Float)
    stress_overall = db.Column(db.Integer)
    resting_hr = db.Column(db.Integer)
    raw_json = db.Column(db.Text)
    pulled_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (db.UniqueConstraint("user_id", "date"),)
```

- [ ] **Step 2: Smoke-verify**

Run: `venv/bin/python -c "import os; os.environ['DATABASE_URL']='sqlite:////tmp/gw1.db'; from app import app, db; ctx=app.app_context(); ctx.push(); db.create_all(); from models import GarminWellness; print(GarminWellness.__tablename__)"`
Expected: `garmin_wellness`.

- [ ] **Step 3: Commit**

```bash
git add models.py
git commit -m "Garmin wellness: daily GarminWellness snapshot table"
```

---

### Task 2: GarminClient — resting HR + per-day wellness aggregate (TDD)

**Files:**
- Modify: `garmin_client.py` (append to `GarminClient`, after `delete_workout`)
- Test: `tests/test_garmin_sync.py` (append)

- [ ] **Step 1: Write failing tests** (append to tests/test_garmin_sync.py)

```python
# ---------- GarminClient.get_wellness_for_day ----------

class _FakeApi:
    """Stub of the garminconnect.Garmin object for per-day getters."""
    def get_hrv_data(self, day):
        return {"hrvSummary": {"lastNightAvg": 52, "weeklyAvg": 55, "status": "BALANCED",
                               "baseline": {"lowUpper": 45, "balancedHigh": 70}}}
    def get_sleep_data(self, day):
        return {"dailySleepDTO": {"sleepTimeSeconds": 26640, "deepSleepSeconds": 5000,
                                  "lightSleepSeconds": 15000, "remSleepSeconds": 6000,
                                  "awakeSleepSeconds": 640,
                                  "sleepScores": {"overall": {"value": 82},
                                                  "quality": {"qualifierKey": "GOOD"}}}}
    def get_body_battery(self, day):
        return [{"charged": 80, "drained": 22}]
    def get_training_readiness(self, day):
        return {"score": 71, "level": "HIGH"}
    def get_training_status(self, day):
        return {"trainingStatus": "PRODUCTIVE", "weeklyTrainingLoad": 500, "mostRecentVO2Max": 48.0}
    def get_stress_data(self, day):
        return {"overallStressLevel": 31, "restStressDuration": 30000, "highStressDuration": 1200}
    def get_rhr_day(self, day):
        return {"allMetrics": {"metricsMap": {"WELLNESS_RESTING_HEART_RATE": [{"value": 47}]}}}


def _connected_client():
    from garmin_client import GarminClient
    gc = GarminClient(user_id=999)
    gc.api = _FakeApi()
    gc._connected = True
    return gc


def test_get_wellness_for_day_aggregates_all_metrics():
    gc = _connected_client()
    w = gc.get_wellness_for_day("2026-06-11")
    assert w["hrv"]["lastNight"] == 52 and w["hrv"]["weeklyAvg"] == 55
    assert w["sleep"]["durationSeconds"] == 26640 and w["sleep"]["score"] == 82
    assert w["bodyBattery"]["current"] == 58  # 80 charged - 22 drained
    assert w["trainingReadiness"]["score"] == 71
    assert w["trainingStatus"]["vo2max"] == 48.0
    assert w["stress"]["overall"] == 31
    assert w["restingHr"] == 47


def test_get_wellness_for_day_none_when_disconnected_or_rate_limited():
    import time as _time
    from garmin_client import GarminClient
    gc = GarminClient()
    assert gc.get_wellness_for_day("2026-06-11") is None  # not connected
    gc2 = _connected_client()
    gc2._rate_limited_until = _time.time() + 600
    assert gc2.get_wellness_for_day("2026-06-11") is None  # rate limited → fetch-failed, not 'no data'


def test_get_rhr_handles_missing_payload():
    gc = _connected_client()
    class NoRhrApi(_FakeApi):
        def get_rhr_day(self, day):
            return {"allMetrics": {"metricsMap": {}}}
    gc.api = NoRhrApi()
    gc._cache = {}
    w = gc.get_wellness_for_day("2026-06-10")
    assert w["restingHr"] is None
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/test_garmin_sync.py -q -k wellness_for_day` — FAIL (`get_wellness_for_day` missing).

- [ ] **Step 3: Implement** (append to `GarminClient` in garmin_client.py)

```python
    # ── Daily wellness snapshot (history persistence) ─────────────────────

    def _get_rhr(self, day):
        def fetch():
            data = self.api.get_rhr_day(day)
            try:
                vals = ((data or {}).get("allMetrics") or {}).get("metricsMap", {}) \
                    .get("WELLNESS_RESTING_HEART_RATE") or []
                v = vals[0].get("value") if vals else None
                return int(v) if v is not None else None
            except Exception:
                return None
        return self._cached(f"rhr_{day}", fetch)

    def get_wellness_for_day(self, day_iso):
        """All wellness metrics for one calendar date. Returns None for
        known-bad states (not connected / rate limited) so callers treat it as
        'fetch failed' and retry later; otherwise a dict whose per-metric
        values may be None (Garmin had nothing — safe to persist as NULL)."""
        if not self.connected:
            return None
        if time.time() < self._rate_limited_until:
            return None
        return {
            "hrv": self._get_hrv(day_iso),
            "sleep": self._get_sleep(day_iso),
            "bodyBattery": self._get_body_battery(day_iso),
            "trainingReadiness": self._get_training_readiness(day_iso),
            "trainingStatus": self._get_training_status(day_iso),
            "stress": self._get_stress(day_iso),
            "restingHr": self._get_rhr(day_iso),
        }
```

- [ ] **Step 4: Run tests**

Run: `venv/bin/python -m pytest tests/test_garmin_sync.py -q` — all pass (3 new, zero failures).
NOTE: `_get_body_battery` computes `current = latest.charged - latest.drained` from the last reading — the test expects 58 from (80, 22). If the real helper differs, fix the TEST expectation to match the real helper (read garmin_client.py:209-225), never the helper.

- [ ] **Step 5: Commit**

```bash
git add garmin_client.py tests/test_garmin_sync.py
git commit -m "Garmin wellness: per-day wellness aggregate + resting HR on GarminClient"
```

---

### Task 3: sync_wellness — persist + backfill (TDD)

**Files:**
- Modify: `garmin_sync.py` (append)
- Test: `tests/test_garmin_sync.py` (append)

- [ ] **Step 1: Write failing tests** (append; reuses `app_ctx`, `_mk_user`, `FakeGC`)

```python
# ---------- DB tests: sync_wellness ----------

def _wellness_payload(hrv=52, sleep_secs=26640, sleep_score=82, bb=58, ready=71,
                      vo2=48.0, stress=31, rhr=47):
    return {
        "hrv": {"lastNight": hrv, "weeklyAvg": 55, "status": "BALANCED"},
        "sleep": {"durationSeconds": sleep_secs, "score": sleep_score},
        "bodyBattery": {"current": bb},
        "trainingReadiness": {"score": ready},
        "trainingStatus": {"status": "PRODUCTIVE", "vo2max": vo2},
        "stress": {"overall": stress},
        "restingHr": rhr,
    }


class WellnessGC(FakeGC):
    def __init__(self, by_day=None, default=True):
        super().__init__()
        self.by_day = by_day or {}
        self.default = default
        self.fetched_days = []

    def get_wellness_for_day(self, day_iso):
        self.fetched_days.append(day_iso)
        if day_iso in self.by_day:
            return self.by_day[day_iso]
        return _wellness_payload() if self.default else None


def test_sync_wellness_creates_today_and_backfills(app_ctx):
    app_, db = app_ctx
    from models import GarminWellness
    from garmin_sync import sync_wellness
    u = _mk_user(db, "well1@test.com")
    today = date(2026, 6, 12)
    res = sync_wellness(WellnessGC(), u.id, today=today)
    assert res["wellness_error"] is None
    row = GarminWellness.query.filter_by(user_id=u.id, date=today).first()
    assert row.sleep_seconds == 26640 and row.sleep_score == 82
    assert row.hrv_last_night == 52 and row.hrv_weekly_avg == 55
    assert row.body_battery == 58 and row.training_readiness == 71
    assert row.vo2max == 48.0 and row.stress_overall == 31 and row.resting_hr == 47
    # backfilled the full 14-day window on first sync
    assert GarminWellness.query.filter_by(user_id=u.id).count() == 15


def test_sync_wellness_refreshes_today_but_not_past(app_ctx):
    app_, db = app_ctx
    from models import GarminWellness
    from garmin_sync import sync_wellness
    u = _mk_user(db, "well2@test.com")
    today = date(2026, 6, 12)
    sync_wellness(WellnessGC(), u.id, today=today)
    yesterday = today - timedelta(days=1)
    gc2 = WellnessGC(by_day={
        today.isoformat(): _wellness_payload(bb=23),
        yesterday.isoformat(): _wellness_payload(bb=99),
    })
    res2 = sync_wellness(gc2, u.id, today=today)
    assert GarminWellness.query.filter_by(user_id=u.id, date=today).first().body_battery == 23
    assert GarminWellness.query.filter_by(user_id=u.id, date=yesterday).first().body_battery == 58
    assert gc2.fetched_days == [today.isoformat()]  # past days not re-fetched
    assert GarminWellness.query.filter_by(user_id=u.id).count() == 15  # no dupes


def test_sync_wellness_null_metrics_and_zero_sleep(app_ctx):
    app_, db = app_ctx
    from models import GarminWellness
    from garmin_sync import sync_wellness
    u = _mk_user(db, "well3@test.com")
    today = date(2026, 6, 12)
    payload = {"hrv": None, "sleep": {"durationSeconds": 0, "score": None},
               "bodyBattery": None, "trainingReadiness": None,
               "trainingStatus": None, "stress": None, "restingHr": None}
    gc = WellnessGC(by_day={(today - timedelta(days=i)).isoformat(): payload for i in range(15)})
    sync_wellness(gc, u.id, today=today)
    row = GarminWellness.query.filter_by(user_id=u.id, date=today).first()
    assert row is not None
    assert row.sleep_seconds is None  # 0 normalized to NULL, never falsy-zero
    assert row.hrv_last_night is None and row.body_battery is None


def test_sync_wellness_fetch_failure_reports_error_and_retries_later(app_ctx):
    app_, db = app_ctx
    from models import GarminWellness
    from garmin_sync import sync_wellness
    u = _mk_user(db, "well4@test.com")
    today = date(2026, 6, 12)
    res = sync_wellness(WellnessGC(default=False), u.id, today=today)  # all fetches fail
    assert res["wellness_error"] is not None
    assert GarminWellness.query.filter_by(user_id=u.id).count() == 0  # nothing written → retried next sync
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/test_garmin_sync.py -q -k sync_wellness` — FAIL (import error). Also add `timedelta` to the test file's datetime import if missing (`from datetime import date, timedelta`).

- [ ] **Step 3: Implement** (append to garmin_sync.py)

```python
# ---------------------------------------------------------------------------
# WELLNESS: daily sleep/HRV/readiness snapshots → GarminWellness history
# ---------------------------------------------------------------------------

WELLNESS_BACKFILL_DAYS = 14


def wellness_fields(day_data):
    """Map GarminClient.get_wellness_for_day output to GarminWellness columns.
    Zero-length sleep normalizes to NULL (no datum, not a falsy zero)."""
    sleep = day_data.get("sleep") or {}
    hrv = day_data.get("hrv") or {}
    bb = day_data.get("bodyBattery") or {}
    tr = day_data.get("trainingReadiness") or {}
    ts = day_data.get("trainingStatus") or {}
    stress = day_data.get("stress") or {}
    return {
        "sleep_seconds": sleep.get("durationSeconds") or None,
        "sleep_score": sleep.get("score"),
        "hrv_last_night": hrv.get("lastNight"),
        "hrv_weekly_avg": hrv.get("weeklyAvg"),
        "hrv_status": hrv.get("status"),
        "body_battery": bb.get("current"),
        "training_readiness": tr.get("score"),
        "training_status": ts.get("status"),
        "vo2max": ts.get("vo2max"),
        "stress_overall": stress.get("overall"),
        "resting_hr": day_data.get("restingHr"),
    }


def sync_wellness(gc, user_id, today=None):
    """Snapshot today's wellness (refreshed every sync — body battery moves)
    and backfill missing past days once, capped at WELLNESS_BACKFILL_DAYS.
    A successfully-fetched day with no data writes an all-NULL row (stops
    re-fetching); a FAILED fetch writes nothing (retried next sync)."""
    from models import db, GarminWellness

    result = {"wellness_upserted": 0, "wellness_backfilled": [], "wellness_error": None}
    today = today or date.today()

    existing = {r.date for r in GarminWellness.query.filter(
        GarminWellness.user_id == user_id,
        GarminWellness.date >= today - timedelta(days=WELLNESS_BACKFILL_DAYS),
    ).all()}
    targets = [today] + [today - timedelta(days=i)
                         for i in range(1, WELLNESS_BACKFILL_DAYS + 1)
                         if today - timedelta(days=i) not in existing]

    for d in targets:
        data = gc.get_wellness_for_day(d.isoformat())
        if data is None:
            if d == today:
                result["wellness_error"] = "wellness fetch failed (not connected or rate limited)"
            break  # known-bad client state — later days would fail the same way
        fields = wellness_fields(data)
        row = GarminWellness.query.filter_by(user_id=user_id, date=d).first()
        if row is None:
            row = GarminWellness(user_id=user_id, date=d)
            db.session.add(row)
        for k, v in fields.items():
            setattr(row, k, v)
        row.raw_json = json.dumps({k: data.get(k) for k in
                                   ("hrv", "sleep", "bodyBattery", "trainingReadiness",
                                    "trainingStatus", "stress", "restingHr")})
        row.pulled_at = datetime.now(timezone.utc)
        result["wellness_upserted"] += 1
        if d != today:
            result["wellness_backfilled"].append(d.isoformat())
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        log.exception("Garmin wellness commit failed")
        result["wellness_error"] = f"DB commit failed: {e}"
    return result
```

- [ ] **Step 4: Run tests**

Run: `venv/bin/python -m pytest tests/test_garmin_sync.py -q` — all pass. Then whole suite: `venv/bin/python -m pytest tests/ -q -p no:cacheprovider 2>&1 | tail -2` — no new failures.

- [ ] **Step 5: Commit**

```bash
git add garmin_sync.py tests/test_garmin_sync.py
git commit -m "Garmin wellness: sync_wellness with today-refresh + capped one-shot backfill"
```

---

### Task 4: Endpoint + sync hook

**Files:**
- Modify: `app.py` (models import; `garmin_sync_activities` endpoint; new endpoint after it)

- [ ] **Step 1: Import the model**

Add `GarminWellness` to the `from models import (...)` block at app.py top.

- [ ] **Step 2: Hook wellness into the sync endpoint**

In `garmin_sync_activities` (app.py, after the `if not result.get("error"): _garmin_sync_last[...] = now` line, before `return jsonify(result)`):

```python
    # Wellness snapshot rides the same throttled sync; failures are independent
    # of the activity sync and reported separately.
    try:
        result["wellness"] = garmin_sync.sync_wellness(gc, current_user.id, today=_user_today())
    except Exception as e:
        logging.exception("[GARMIN] wellness sync failed")
        result["wellness"] = {"wellness_error": str(e)[:200]}
    return jsonify(result)
```

(`import garmin_sync` is already at the top of this function.)

- [ ] **Step 3: Add the wellness read endpoint** (directly after `garmin_sync_status`)

```python
@app.route("/api/garmin/wellness")
@login_required
def garmin_wellness():
    """Stored wellness history (DB only — never triggers a Garmin call)."""
    days = max(1, min(90, request.args.get("days", default=1, type=int) or 1))
    since = _user_today() - timedelta(days=days - 1)
    rows = GarminWellness.query.filter(
        GarminWellness.user_id == current_user.id,
        GarminWellness.date >= since,
    ).order_by(GarminWellness.date.desc()).all()
    return jsonify([{
        "date": r.date.isoformat(),
        "sleep_hours": round(r.sleep_seconds / 3600, 1) if r.sleep_seconds else None,
        "sleep_score": r.sleep_score,
        "hrv": r.hrv_last_night,
        "hrv_weekly_avg": r.hrv_weekly_avg,
        "body_battery": r.body_battery,
        "readiness": r.training_readiness,
        "resting_hr": r.resting_hr,
        "stress": r.stress_overall,
        "vo2max": r.vo2max,
    } for r in rows])
```

- [ ] **Step 4: Verify**

1. Route smoke (no login → 401 JSON, proving the route exists and is gated):
`venv/bin/python -c "import os; os.environ['DATABASE_URL']='sqlite:////tmp/gw4.db'; from app import app; c=app.test_client(); print(c.get('/api/garmin/wellness').status_code)"` → `401`.
2. Full suite: `venv/bin/python -m pytest tests/ -q -p no:cacheprovider 2>&1 | tail -2` — no new failures.
3. Boot: `venv/bin/python -c "import os; os.environ['DATABASE_URL']='sqlite:////tmp/gw4b.db'; import app; print('ok')"` → ok.

- [ ] **Step 5: Commit**

```bash
git add app.py
git commit -m "Garmin wellness: history endpoint + wellness snapshot in the throttled sync"
```

---

### Task 5: Header strip (frontend)

**Files:**
- Modify: `templates/index.html` (line 71)
- Modify: `static/app.js` (globals ~line 168; load batch ~5272; auto-pull block ~5272-5284; `renderGarminBar` ~9248)

- [ ] **Step 1: Re-add the bar div**

Replace `<!-- Garmin removed -->` (index.html:71) with:

```html
<div class="garmin-bar" id="garmin-bar" style="display:none"></div>
```

NOTE: this places the strip above the chat overlay, below the progress overlay — same region it originally lived. If the visual position relative to `today-nav` looks wrong in the smoke test (Step 6), move the div to immediately BEFORE `<div id="today-nav" class="today-nav"></div>` (~line 55) instead; either slot is acceptable, day-view-top is the spec intent.

- [ ] **Step 2: Global state**

Near `let garminConnected = false;` (app.js ~168) add:

```js
let _wellnessToday = null; // today's GarminWellness row (served by /api/garmin/wellness?days=1)
```

- [ ] **Step 3: Fetch with the load batch**

Immediately after the run-log cache fetch line (`try { const rlRes = await fetch('/api/run-log'); _runLogCache = await rlRes.json(); } catch(e) { _runLogCache = {}; }` at ~app.js:5285) add:

```js
    // Today's wellness strip data (DB-only; server returns [] or [today's row])
    try {
      const wRes = await fetch('/api/garmin/wellness?days=1');
      const w = wRes.ok ? await wRes.json() : [];
      _wellnessToday = (w && w.length) ? w[0] : null;
    } catch(e) { _wellnessToday = null; }
```

- [ ] **Step 4: Refresh the strip after the auto-sync resolves**

In the existing fire-and-forget auto-pull block (~app.js:5272), extend the `.then(d => { ... })` so that after the run-log refresh logic it ALSO refreshes wellness when the sync wasn't throttled:

```js
      .then(d => {
        if (d && (d.days_filled || []).length) {
          return fetch('/api/run-log').then(r => r.json())
            .then(j => { _runLogCache = j; renderDetail(); })
            .then(() => d);
        }
        return d;
      })
      .then(d => {
        if (d && !d.throttled) {
          return fetch('/api/garmin/wellness?days=1').then(r => (r.ok ? r.json() : []))
            .then(w => { _wellnessToday = (w && w.length) ? w[0] : null; renderGarminBar(); });
        }
      })
      .catch(() => {});
```

(Replace the block's existing `.then`/`.catch` chain with the above — preserve the existing first-stage run-log behavior exactly.)

- [ ] **Step 5: Rebuild renderGarminBar()** (app.js:9248, replace the stub body)

```js
function renderGarminBar() {
  const el = document.getElementById('garmin-bar');
  if (!el) return;
  const w = _wellnessToday;
  if (!w) { el.style.display = 'none'; return; }
  const GOOD = '#4ade80', WARN = '#fbbf24', BAD = '#ef4444', NEUTRAL = 'var(--text)';
  const dim = '<span style="color:var(--muted)">&mdash;</span>';
  function band(v, good, warn) { return v == null ? NEUTRAL : (v >= good ? GOOD : (v >= warn ? WARN : BAD)); }
  function chip(html, color) {
    return '<div class="garmin-metric" style="font-family:\'DM Mono\',monospace;font-size:16px;text-align:center;padding:6px 4px;color:' + color + '">' + html + '</div>';
  }
  let hrvColor = NEUTRAL;
  if (w.hrv != null && w.hrv_weekly_avg) {
    const ratio = w.hrv / w.hrv_weekly_avg;
    hrvColor = ratio >= 1 ? GOOD : (ratio >= 0.85 ? WARN : BAD);
  }
  el.innerHTML = '<div class="garmin-metrics">' +
    chip(w.sleep_hours != null
      ? '&#128564; ' + w.sleep_hours + 'h' + (w.sleep_score != null ? ' &middot; ' + w.sleep_score : '')
      : '&#128564; ' + dim, band(w.sleep_score, 80, 60)) +
    chip(w.hrv != null ? 'HRV ' + w.hrv : 'HRV ' + dim, hrvColor) +
    chip(w.body_battery != null ? '&#128267; ' + w.body_battery : '&#128267; ' + dim, band(w.body_battery, 60, 30)) +
    chip(w.readiness != null ? 'Ready ' + w.readiness : 'Ready ' + dim, band(w.readiness, 70, 40)) +
    '</div>';
  el.style.display = '';
}
```

(`renderGarminBar()` is already called from the render path at app.js:9077 — no call wiring needed. The all-NULL-row case renders four dimmed chips by design: Garmin connected but no data yet today is honest "—", whereas no row at all hides the strip.)

- [ ] **Step 6: Verify**

1. `node --check static/app.js` → silent.
2. `npx vitest run 2>&1 | tail -3` → pass.
3. Browser smoke (mirror the activity-sync feature's smoke): temp sqlite + verified smoke user, start `DATABASE_URL='sqlite:////tmp/gw_ui.db' PORT=5058 venv/bin/python app.py`, insert a GarminWellness row for today for the smoke user directly via a python one-liner, log in with playwright, confirm: strip shows 4 chips with the inserted values; delete the row + reload → strip hidden; row with NULLs → dimmed dashes. Screenshot for the record. Kill server when done.

- [ ] **Step 7: Commit**

```bash
git add templates/index.html static/app.js
git commit -m "Garmin wellness: four-chip header strip (sleep/HRV/body battery/readiness)"
```

---

### Task 6: Final review, merge, deploy, live check

- [ ] **Step 1:** Final whole-branch review (integration seams: sync hook result shape vs frontend reads; endpoint NULL handling; strip honesty rules; standing rules) + full suite + boot smoke.
- [ ] **Step 2:** Merge to main, verify tests on merged result, push (Render auto-deploys; do NOT poll the deploy).
- [ ] **Step 3:** Live with Erik: open the app → strip shows last night's real sleep/HRV/BB/readiness (first sync of the day fills it); numbers match Garmin Connect.

---

## Execution notes

- Work on a feature branch (`garmin-wellness`) off main; main auto-deploys on push.
- Extend `tests/test_garmin_sync.py` — `app_ctx`/`_mk_user`/`FakeGC` already exist there; don't redefine them.
- The strip must never show yesterday's row as today — the endpoint's `days=1` window guarantees `[]` or `[today]`; don't weaken that.
- Keep wellness failures out of the activities sync path and vice versa (independent error fields).
