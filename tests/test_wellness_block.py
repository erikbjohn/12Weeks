"""tests/test_wellness_block.py — TDD for Task 8: Garmin wellness trend read
(coach context + weekly report), explicit "dark" mode when data is sparse.

Context: Garmin sync was repaired on prod 2026-08-10 — wellness rows exist
from that date onward, nothing earlier, so a pre-protocol baseline is
impossible. "Baseline" instead means the mean over the FIRST 14 calendar
days of data on/after 2026-08-10 (BASELINE_ANCHOR in coach_assembler.py),
gated on having >= 7 days of real data in that span.

wellness_trends() is a PURE function (no DB, no app context needed) — most
of its arithmetic/dark-gate/baseline behavior is tested directly. The
DB-backed section builders (_build_garmin, compute_weekly_metrics) use the
short-lived app-context fixture pattern from tests/test_protocol_api.py:
every DB touch opens its own `with app_.app_context():` block and returns
plain values (never attached ORM objects); calls that need current_user run
with NO context held open so Flask/flask_login push a correct fresh one — a
held-open module context leaks one client's current_user into the next
(see test_protocol_api.py / test_security_auth.py for the full rationale).
"""
from datetime import date, timedelta

import pytest


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
    yield app, db


def _app_do(app_, fn):
    with app_.app_context():
        return fn()


def _fresh_user(app_, db, email):
    """Create (or reset) a user + wipe their GarminWellness/AppState/
    WeeklyReport rows. Returns the user id (plain int, not a detached ORM
    object)."""
    def _do():
        from models import User, GarminWellness, AppState, WeeklyReport
        u = User.query.filter_by(email=email).first()
        if not u:
            u = User(email=email, timezone="America/Los_Angeles")
            db.session.add(u)
            db.session.commit()
        GarminWellness.query.filter_by(user_id=u.id).delete()
        AppState.query.filter_by(user_id=u.id).delete()
        WeeklyReport.query.filter_by(user_id=u.id).delete()
        db.session.commit()
        return u.id
    return _app_do(app_, _do)


def _add_rows(app_, db, rows):
    def _do():
        for r in rows:
            db.session.add(r)
        db.session.commit()
    _app_do(app_, _do)


def _client_for(app_, uid):
    client = app_.test_client()
    with client.session_transaction() as s:
        s["_user_id"] = str(uid)
        s["_fresh"] = True
    return client


# ---------------------------------------------------------------------------
# (a)(b)(c)(d) — wellness_trends() pure-function arithmetic + gates
# ---------------------------------------------------------------------------

class TestWellnessTrendsPure:
    def test_zero_rows_is_dark_with_exact_dark_line(self):
        from coach_assembler import wellness_trends
        today = date(2026, 8, 19)
        out = wellness_trends([], today)
        assert out["dark"] is True
        assert out["dark_line"] == "Garmin wellness: no synced data for 7 of last 7 days"
        assert out["days_with_data_7d"] == 0
        assert out["rhr_7d"] is None
        assert out["rhr_28d"] is None
        assert out["hrv_7d"] is None
        assert out["sleep_score_7d"] is None
        assert out["baseline"] is None
        # "wellness" block itself is a non-empty dict — never omitted (rule 20)
        assert out is not None and out != {}

    def test_three_rows_in_window_dark_with_n_equals_4(self):
        from coach_assembler import wellness_trends
        from models import GarminWellness
        today = date(2026, 8, 19)
        rows = [
            GarminWellness(user_id=1, date=today, resting_hr=55),
            GarminWellness(user_id=1, date=today - timedelta(days=1), resting_hr=56),
            GarminWellness(user_id=1, date=today - timedelta(days=2), resting_hr=54),
        ]
        out = wellness_trends(rows, today)
        assert out["dark"] is True
        assert out["days_with_data_7d"] == 3
        assert out["dark_line"] == "Garmin wellness: no synced data for 4 of last 7 days"

    def test_ten_consecutive_days_means_and_baseline(self):
        """10 days seeded starting exactly at BASELINE_ANCHOR (2026-08-10):
        dark clears, 7d/28d means hand-computed, baseline gate passes (10 >= 7
        days of data in the 14-day baseline span) and is labeled 'since'
        the anchor date."""
        from coach_assembler import wellness_trends
        from models import GarminWellness
        start = date(2026, 8, 10)  # BASELINE_ANCHOR
        today = start + timedelta(days=9)  # 2026-08-19 — 10th consecutive day
        rhr_vals = [50, 51, 52, 53, 54, 55, 56, 57, 58, 59]
        hrv_vals = [60, 61, 62, 63, 64, 65, 66, 67, 68, 69]
        sleep_vals = [70 + i for i in range(10)]
        rows = [
            GarminWellness(
                user_id=1, date=start + timedelta(days=i),
                resting_hr=rhr_vals[i], hrv_last_night=hrv_vals[i],
                sleep_score=sleep_vals[i],
            )
            for i in range(10)
        ]
        out = wellness_trends(rows, today)

        assert out["dark"] is False
        assert out["days_with_data_7d"] == 7

        # 7d window = today-6..today -> the LAST 7 seeded days (indices 3..9)
        assert out["rhr_7d"] == round(sum(rhr_vals[3:]) / 7, 1)
        assert out["hrv_7d"] == round(sum(hrv_vals[3:]) / 7, 1)
        assert out["sleep_score_7d"] == round(sum(sleep_vals[3:]) / 7, 1)

        # 28d window: only 10 days of history exist, so it's all 10 rows
        assert out["rhr_28d"] == round(sum(rhr_vals) / 10, 1)
        assert out["hrv_28d"] == round(sum(hrv_vals) / 10, 1)

        # baseline: first 14 calendar days from the anchor; all 10 rows fall
        # inside it -> gate passes (10 >= BASELINE_MIN_DAYS=7)
        assert out["baseline"] == {
            "rhr": round(sum(rhr_vals) / 10, 1),
            "hrv": round(sum(hrv_vals) / 10, 1),
            "since": "2026-08-10",
        }

    def test_null_metric_rows_count_per_metric_not_per_row(self):
        """A row missing rhr but carrying hrv contributes to the hrv mean
        only (never silently zeroed or excluded from the OTHER metric's
        mean); it still counts once toward days_with_data_7d because SOME
        metric is present."""
        from coach_assembler import wellness_trends
        from models import GarminWellness
        today = date(2026, 8, 19)
        rows = [
            GarminWellness(user_id=1, date=today, resting_hr=None, hrv_last_night=62),
            GarminWellness(user_id=1, date=today - timedelta(days=1), resting_hr=58, hrv_last_night=None),
        ]
        out = wellness_trends(rows, today)
        assert out["rhr_7d"] == 58.0     # only the second row has resting_hr
        assert out["hrv_7d"] == 62.0     # only the first row has hrv_last_night
        assert out["days_with_data_7d"] == 2

    def test_four_days_in_window_clears_dark(self):
        """Exact dark-boundary pin: 4 of 7 days with data is the minimum that
        clears dark (< 4 stays dark, per test_three_rows_in_window_dark_with_n_equals_4)."""
        from coach_assembler import wellness_trends
        from models import GarminWellness
        today = date(2026, 8, 19)
        rows = [
            GarminWellness(user_id=1, date=today - timedelta(days=i), resting_hr=55 + i)
            for i in range(4)
        ]
        out = wellness_trends(rows, today)
        assert out["days_with_data_7d"] == 4
        assert out["dark"] is False
        assert out["dark_line"] is None

    def test_baseline_none_when_under_min_days(self):
        """Only 5 days of data in the 14-day baseline span (< BASELINE_MIN_DAYS
        of 7) -> baseline stays None, even though those 5 days are real data."""
        from coach_assembler import wellness_trends
        from models import GarminWellness
        start = date(2026, 8, 10)
        rows = [
            GarminWellness(user_id=1, date=start + timedelta(days=i), resting_hr=50 + i)
            for i in range(5)
        ]
        out = wellness_trends(rows, start + timedelta(days=4))
        assert out["baseline"] is None

    def test_window_override_used_for_7d_and_28d_trails_window_end(self):
        """A window override (weekly_report's use case) drives the 7d stats;
        the 28d window trails the OVERRIDE's end date, not `today`."""
        from coach_assembler import wellness_trends
        from models import GarminWellness
        week_monday = date(2026, 8, 10)
        week_sunday = week_monday + timedelta(days=6)
        rows = [
            GarminWellness(user_id=1, date=week_monday + timedelta(days=i), resting_hr=60)
            for i in range(7)
        ]
        # `today` deliberately far from the window to prove it's ignored for 7d/28d.
        out = wellness_trends(rows, date(2027, 1, 1), window=(week_monday, week_sunday))
        assert out["dark"] is False
        assert out["days_with_data_7d"] == 7
        assert out["rhr_7d"] == 60.0
        assert out["rhr_28d"] == 60.0  # all 7 rows fall in the 28d-trailing-window_end span


# ---------------------------------------------------------------------------
# (e) — weekly_report.compute_weekly_metrics carries "wellness"
# ---------------------------------------------------------------------------

class TestWeeklyReportWellness:
    def test_weekly_metrics_include_wellness_for_seeded_week(self, app_ctx):
        from weekly_report import compute_weekly_metrics
        from models import AppState, GarminWellness
        app_, db = app_ctx
        uid = _fresh_user(app_, db, "wellness-weekly@test.com")
        block_start = date(2026, 7, 27)  # Monday; week 3 Monday lands on BASELINE_ANCHOR
        week_num = 3
        week_monday = block_start + timedelta(days=(week_num - 1) * 7)
        assert week_monday == date(2026, 8, 10)

        rows = [AppState(user_id=uid, start_date=block_start)]
        rows += [
            GarminWellness(user_id=uid, date=week_monday + timedelta(days=i),
                            resting_hr=50 + i, hrv_last_night=60 + i, sleep_score=80)
            for i in range(7)
        ]
        _add_rows(app_, db, rows)

        with app_.app_context():
            m = compute_weekly_metrics(week_num, user_id=uid)

        assert "wellness" in m
        w = m["wellness"]
        assert w["dark"] is False
        assert w["days_with_data_7d"] == 7
        assert w["rhr_7d"] == round(sum(50 + i for i in range(7)) / 7, 1)
        assert w["hrv_7d"] == round(sum(60 + i for i in range(7)) / 7, 1)
        assert w["baseline"] is not None
        assert w["baseline"]["since"] == "2026-08-10"

    def test_weekly_metrics_wellness_present_and_dark_without_appstate(self, app_ctx):
        """No AppState row (unset block start) must still surface a wellness
        block — never omitted, per the rule-20 guard."""
        from weekly_report import compute_weekly_metrics
        app_, db = app_ctx
        uid = _fresh_user(app_, db, "wellness-noappstate@test.com")
        with app_.app_context():
            m = compute_weekly_metrics(5, user_id=uid)
        assert "wellness" in m
        assert m["wellness"]["dark"] is True


# ---------------------------------------------------------------------------
# (f) — prompt injection: dark line verbatim / lit numbers line
# ---------------------------------------------------------------------------

class TestPromptInjection:
    def test_dark_line_rendered_verbatim(self, app_ctx):
        from coach_assembler import _format_athlete_data, wellness_trends
        app_, db = app_ctx
        with app_.app_context():
            ctx = {"wellness": wellness_trends([], date(2026, 8, 19))}
            out = _format_athlete_data(ctx, ["garmin"])
        assert "Garmin wellness: no synced data for 7 of last 7 days" in out

    def test_lit_numbers_line_rendered(self, app_ctx):
        from coach_assembler import _format_athlete_data, wellness_trends
        from models import GarminWellness
        app_, db = app_ctx
        # Far outside the fixed baseline span (2026-08-10..2026-08-23) so
        # this test exercises the no-baseline branch cleanly; the
        # baseline-present branch is covered separately below.
        today = date(2026, 12, 1)
        rows = [
            GarminWellness(user_id=1, date=today - timedelta(days=i),
                            resting_hr=50, hrv_last_night=60, sleep_score=80)
            for i in range(7)
        ]
        with app_.app_context():
            ctx = {"wellness": wellness_trends(rows, today)}
            out = _format_athlete_data(ctx, ["garmin"])
        assert "wellness: RHR 7d avg 50.0 (28d 50.0)" in out
        assert "HRV 7d 60.0 (28d 60.0)" in out
        assert "sleep score 7d 80.0" in out
        assert "data 7/7 days" in out
        # No dark line leaking through when lit.
        assert "no synced data" not in out

    def test_lit_line_includes_baseline_when_present(self, app_ctx):
        from coach_assembler import _format_athlete_data, wellness_trends
        from models import GarminWellness
        app_, db = app_ctx
        start = date(2026, 8, 10)
        today = start + timedelta(days=9)
        rows = [
            GarminWellness(user_id=1, date=start + timedelta(days=i),
                            resting_hr=55, hrv_last_night=65)
            for i in range(10)
        ]
        with app_.app_context():
            ctx = {"wellness": wellness_trends(rows, today)}
            out = _format_athlete_data(ctx, ["garmin"])
        assert "baseline 55.0 since 2026-08-10" in out


# ---------------------------------------------------------------------------
# (g) — _build_garmin works with the live Garmin client disconnected
# ---------------------------------------------------------------------------

class _StubGarmin:
    """Stand-in for GarminClient: always disconnected, never reachable."""
    connected = False

    def try_restore_tokens(self, user_id):
        return False

    def get_today_summary(self):
        raise AssertionError("must never be called while disconnected")


class TestBuildGarminDbOnly:
    def test_wellness_populated_from_db_when_client_disconnected(self, app_ctx, monkeypatch):
        from models import GarminWellness
        app_, db = app_ctx
        uid = _fresh_user(app_, db, "wellness-disconnected@test.com")
        today = date(2026, 8, 19)
        rows = [
            GarminWellness(user_id=uid, date=today - timedelta(days=i),
                            resting_hr=52, hrv_last_night=61, sleep_score=77)
            for i in range(7)
        ]
        _add_rows(app_, db, rows)

        import app as appmod
        monkeypatch.setattr(appmod, "_get_garmin", lambda uid=None: _StubGarmin())

        from coach_assembler import _build_garmin, _user_today
        from flask_login import login_user
        from models import User
        with app_.test_request_context():
            u = User.query.get(uid)
            login_user(u, force=True)
            monkeypatch.setattr(
                "coach_assembler._user_today", lambda: today
            )
            out = _build_garmin()

        # 2026-08-28: DB-FIRST. Today's synced row now feeds "garmin" directly
        # (zero live calls) even though the live client is disconnected — the
        # old `garmin is None` here was exactly the gap that made the coach
        # say "I can't pull Garmin" with last night's row sitting in the DB.
        assert out["garmin"]["hrv"]["lastNight"] == 61
        assert out["garmin"]["sleep"]["score"] == 77
        assert out["garmin"]["source"].startswith("garmin_wellness")
        assert out["readiness"]["score"] is not None
        w = out["wellness"]
        assert w["dark"] is False
        assert w["days_with_data_7d"] == 7
        assert w["rhr_7d"] == 52.0

    def test_wellness_query_failure_degrades_to_dark_not_a_dropped_section(self, app_ctx, monkeypatch):
        """Fix round 1, minor #3: a GarminWellness query failure must not
        discard the whole garmin section (garmin_data/readiness are unrelated
        to this DB read) — it degrades to a dark wellness block instead."""
        from models import GarminWellness, User
        app_, db = app_ctx
        uid = _fresh_user(app_, db, "wellness-query-boom@test.com")

        import app as appmod
        monkeypatch.setattr(appmod, "_get_garmin", lambda uid=None: _StubGarmin())

        class _RaisingQuery:
            def filter_by(self, **kwargs):
                raise RuntimeError("simulated DB failure")

        # Reading the CURRENT `query` value (what monkeypatch.setattr does
        # internally, to restore it after the test) requires an app context
        # — flask-sqlalchemy's query descriptor binds to the active session.
        with app_.app_context():
            monkeypatch.setattr(GarminWellness, "query", _RaisingQuery())

        from coach_assembler import _build_garmin
        from flask_login import login_user
        with app_.test_request_context():
            u = User.query.get(uid)
            login_user(u, force=True)
            out = _build_garmin()

        assert "wellness" in out
        assert out["wellness"]["dark"] is True
        assert out["wellness"]["dark_line"] == "Garmin wellness: no synced data for 7 of last 7 days"


# ---------------------------------------------------------------------------
# Fix round 1 — weekly-report wellness must actually reach the user:
# generate_report_narrative's prompt, and GET /api/weekly-report/<week>.
# ---------------------------------------------------------------------------

class TestNarrativeDataLinesWellness:
    def test_lit_week_narrative_includes_numbers_line(self):
        from weekly_report import _build_narrative_data_lines
        from coach_assembler import wellness_trends
        from models import GarminWellness
        today = date(2026, 12, 1)  # outside the fixed baseline span
        rows = [
            GarminWellness(user_id=1, date=today - timedelta(days=i),
                            resting_hr=50, hrv_last_night=60, sleep_score=80)
            for i in range(7)
        ]
        metrics = {"week": 4, "workouts_completed": 5,
                   "wellness": wellness_trends(rows, today)}
        lines = _build_narrative_data_lines(metrics)
        joined = "\n".join(lines)
        assert "wellness: RHR 7d avg 50.0 (28d 50.0)" in joined
        assert "HRV 7d 60.0 (28d 60.0)" in joined
        assert "sleep score 7d 80.0" in joined
        assert "data 7/7 days" in joined

    def test_dark_week_narrative_includes_dark_line_verbatim(self):
        from weekly_report import _build_narrative_data_lines
        from coach_assembler import wellness_trends
        metrics = {"week": 5, "workouts_completed": 0,
                   "wellness": wellness_trends([], date(2026, 8, 19))}
        lines = _build_narrative_data_lines(metrics)
        assert "Garmin wellness: no synced data for 7 of last 7 days" in lines

    def test_missing_wellness_key_does_not_crash(self):
        """Older/partial metrics dicts (no 'wellness' key at all) must not
        break narrative building — just no wellness line."""
        from weekly_report import _build_narrative_data_lines
        lines = _build_narrative_data_lines({"week": 1, "workouts_completed": 3})
        assert not any("wellness" in l.lower() for l in lines)


class TestGenerateEndpointIncludesWellness:
    def test_generate_response_metrics_include_wellness(self, app_ctx):
        app_, db = app_ctx
        uid = _fresh_user(app_, db, "wellness-generate-endpoint@test.com")
        client = _client_for(app_, uid)
        resp = client.post("/api/weekly-report/generate")
        assert resp.status_code == 200
        body = resp.get_json()
        assert "wellness" in body["metrics"]


class TestGetEndpointIncludesWellness:
    def test_get_endpoint_returns_correct_week_window_wellness(self, app_ctx):
        from models import AppState, GarminWellness, WeeklyReport
        app_, db = app_ctx
        uid = _fresh_user(app_, db, "wellness-get-endpoint@test.com")
        block_start = date(2026, 7, 27)  # Monday; week 3 Monday == BASELINE_ANCHOR
        week_num = 3
        week_monday = block_start + timedelta(days=(week_num - 1) * 7)
        assert week_monday == date(2026, 8, 10)

        rows = [
            AppState(user_id=uid, start_date=block_start),
            WeeklyReport(user_id=uid, week=week_num, report_date=week_monday),
        ]
        rows += [
            GarminWellness(user_id=uid, date=week_monday + timedelta(days=i),
                            resting_hr=50 + i, hrv_last_night=60 + i, sleep_score=80)
            for i in range(7)
        ]
        _add_rows(app_, db, rows)

        client = _client_for(app_, uid)
        resp = client.get(f"/api/weekly-report/{week_num}")
        assert resp.status_code == 200
        body = resp.get_json()
        assert "wellness" in body
        w = body["wellness"]
        assert w["dark"] is False
        assert w["days_with_data_7d"] == 7
        assert w["rhr_7d"] == round(sum(50 + i for i in range(7)) / 7, 1)
        assert w["hrv_7d"] == round(sum(60 + i for i in range(7)) / 7, 1)
        assert w["baseline"] is not None
        assert w["baseline"]["since"] == "2026-08-10"

    def test_get_endpoint_wellness_dark_for_report_with_no_garmin_rows(self, app_ctx):
        from models import AppState, WeeklyReport
        app_, db = app_ctx
        uid = _fresh_user(app_, db, "wellness-get-endpoint-dark@test.com")
        block_start = date(2026, 7, 27)
        week_num = 3
        _add_rows(app_, db, [
            AppState(user_id=uid, start_date=block_start),
            WeeklyReport(user_id=uid, week=week_num,
                         report_date=block_start + timedelta(days=14)),
        ])
        client = _client_for(app_, uid)
        resp = client.get(f"/api/weekly-report/{week_num}")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["wellness"]["dark"] is True
        assert body["wellness"]["dark_line"] == "Garmin wellness: no synced data for 7 of last 7 days"
