"""tests/test_protocol_import.py — TDD for POST /api/admin/import-protocol.

Covers the full §1 import-immutability contract from
docs/superpowers/specs/2026-08-10-peptide-protocol-integration-design.md:
validate-first duplicate rejection, user-local "today" resolution
(never the server's UTC date), upsert-by-(user_id, date, compound),
past-row + taken-dose_mg immutability (force_past is an explicit override
for the past-date lock ONLY — it never overrides a taken row's dose_mg
immutability), the delete/keep-and-annotate pass, and the whole-file
integrity check.

"Today" is controlled by monkeypatching `appmod._user_today_for` — the
admin endpoint has no logged-in current_user in the right timezone, so it
always resolves "today" via that helper (User.timezone ->
utils_time.user_local_today), never the server's UTC date. This is the
single, consistent seam used across every test below.
"""
import csv
import os
from datetime import date, datetime

import pytest

REAL_CSV_PATH = "tests/fixtures/peptide_protocol_snapshot.csv"  # resolved relative to app.py's directory (snapshot 2026-09-03)
CSV_FIELDS = ["Date", "Time", "Event_Type", "Compound", "Dose_mg", "Syringe_Units", "Site", "Notes"]


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def _fresh_user(app_, db, email):
    from models import User, PeptideDose
    u = User.query.filter_by(email=email).first()
    if not u:
        u = User(email=email, timezone="America/Los_Angeles")
        db.session.add(u)
        db.session.commit()
    PeptideDose.query.filter_by(user_id=u.id).delete()
    db.session.commit()
    return u


def _set_today(monkeypatch, d):
    import app as appmod
    monkeypatch.setattr(appmod, "_user_today_for", lambda user: d)


def _client(app_, monkeypatch, admin_key="test-admin-key-long-enough-for-guard-01"):
    monkeypatch.setenv("ADMIN_API_KEY", admin_key)
    return app_.test_client()


def _post_import(client, email, admin_key="test-admin-key-long-enough-for-guard-01", **body):
    return client.post(
        f"/api/admin/import-protocol?email={email}",
        json=body,
        headers={"X-Admin-Key": admin_key},
    )


def _row(date_s, time_s, event_type, compound, dose_mg, syringe="-", site="-", notes=""):
    return {
        "Date": date_s, "Time": time_s, "Event_Type": event_type, "Compound": compound,
        "Dose_mg": dose_mg, "Syringe_Units": syringe, "Site": site, "Notes": notes,
    }


def _write_csv(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _peptide_rows(db, user_id):
    from models import PeptideDose
    return PeptideDose.query.filter_by(user_id=user_id).all()


def _get_row(db, user_id, d, compound):
    from models import PeptideDose
    return PeptideDose.query.filter_by(user_id=user_id, date=d, compound=compound).first()


# ── (a) fresh import: 381 rows, per-compound counts match the real CSV ──────

def test_fresh_import_381_rows_per_compound_counts(app_ctx, monkeypatch):
    app_, db = app_ctx
    u = _fresh_user(app_, db, "import-fresh@test.com")
    _set_today(monkeypatch, date(2026, 8, 10))  # earliest CSV date — nothing is past
    client = _client(app_, monkeypatch)

    r = _post_import(client, u.email, csv_path=REAL_CSV_PATH)
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()

    assert body["row_count"] == 381
    assert body["imported"] == 381
    assert body["updated"] == 0
    assert body["deleted"] == 0
    assert body["skipped"] == []
    assert body["meal_days_regenerated"] == []

    from collections import Counter
    with open(REAL_CSV_PATH, newline="") as f:
        expected = Counter(row["Compound"] for row in csv.DictReader(f))
    assert body["per_compound"] == dict(expected)

    from models import PeptideDose
    assert PeptideDose.query.filter_by(user_id=u.id).count() == 381


# ── (b) idempotent re-import: unchanged CSV is a no-op ──────────────────────

def test_idempotent_reimport_is_a_noop(app_ctx, monkeypatch):
    app_, db = app_ctx
    u = _fresh_user(app_, db, "import-idem@test.com")
    _set_today(monkeypatch, date(2026, 8, 10))
    client = _client(app_, monkeypatch)

    r1 = _post_import(client, u.email, csv_path=REAL_CSV_PATH)
    assert r1.status_code == 200, r1.get_data(as_text=True)

    r2 = _post_import(client, u.email, csv_path=REAL_CSV_PATH)
    assert r2.status_code == 200, r2.get_data(as_text=True)
    body2 = r2.get_json()
    assert body2["imported"] == 0
    assert body2["updated"] == 0
    assert body2["deleted"] == 0
    assert body2["skipped"] == []
    assert body2["row_count"] == 381

    from models import PeptideDose
    assert PeptideDose.query.filter_by(user_id=u.id).count() == 381


# ── (c) midday re-import: today's dose checked + a FUTURE dose_mg changed ──

def test_midday_reimport_taken_today_intact_future_dose_updated(app_ctx, monkeypatch, tmp_path):
    app_, db = app_ctx
    u = _fresh_user(app_, db, "import-midday@test.com")
    _set_today(monkeypatch, date(2026, 8, 20))
    client = _client(app_, monkeypatch)

    csv_path = str(tmp_path / "protocol.csv")
    _write_csv(csv_path, [
        _row("2026-08-20", "07:00", "Injection", "BPC-157", "0.25", "10u", "Thigh", "today"),
        _row("2026-08-21", "07:00", "Injection", "BPC-157", "0.25", "10u", "Thigh", "future"),
    ])
    r1 = _post_import(client, u.email, csv_path=csv_path)
    assert r1.status_code == 200, r1.get_data(as_text=True)
    assert r1.get_json()["imported"] == 2

    today_row = _get_row(db, u.id, date(2026, 8, 20), "BPC-157")
    today_row.taken_at = datetime(2026, 8, 20, 14, 5, 0)
    db.session.commit()
    taken_at_before = today_row.taken_at
    today_id = today_row.id

    _write_csv(csv_path, [
        _row("2026-08-20", "07:00", "Injection", "BPC-157", "0.25", "10u", "Thigh", "today"),
        _row("2026-08-21", "07:00", "Injection", "BPC-157", "0.5", "10u", "Thigh", "future — dose raised"),
    ])
    r2 = _post_import(client, u.email, csv_path=csv_path)
    assert r2.status_code == 200, r2.get_data(as_text=True)
    body2 = r2.get_json()
    assert body2["imported"] == 0
    assert body2["updated"] == 1
    assert body2["deleted"] == 0
    assert body2["skipped"] == []

    db.session.expire_all()
    today_row = _get_row(db, u.id, date(2026, 8, 20), "BPC-157")
    assert today_row.id == today_id
    assert today_row.taken_at == taken_at_before
    assert today_row.dose_mg == 0.25

    future_row = _get_row(db, u.id, date(2026, 8, 21), "BPC-157")
    assert future_row.dose_mg == 0.5


# ── (d) time change on a checked-off today dose → in-place update ──────────

def test_time_change_on_checked_today_dose_preserves_taken_at(app_ctx, monkeypatch, tmp_path):
    app_, db = app_ctx
    u = _fresh_user(app_, db, "import-timechange@test.com")
    _set_today(monkeypatch, date(2026, 8, 20))
    client = _client(app_, monkeypatch)

    csv_path = str(tmp_path / "protocol.csv")
    _write_csv(csv_path, [_row("2026-08-20", "07:00", "Injection", "BPC-157", "0.25", "10u", "Thigh", "n")])
    r1 = _post_import(client, u.email, csv_path=csv_path)
    assert r1.status_code == 200, r1.get_data(as_text=True)

    row = _get_row(db, u.id, date(2026, 8, 20), "BPC-157")
    row.taken_at = datetime(2026, 8, 20, 8, 0, 0)
    db.session.commit()
    taken_at_before = row.taken_at
    row_id = row.id

    _write_csv(csv_path, [_row("2026-08-20", "08:00", "Injection", "BPC-157", "0.25", "10u", "Thigh", "n")])
    r2 = _post_import(client, u.email, csv_path=csv_path)
    assert r2.status_code == 200, r2.get_data(as_text=True)
    body2 = r2.get_json()
    assert body2["updated"] == 1
    assert body2["imported"] == 0
    assert body2["deleted"] == 0

    from models import PeptideDose
    rows = PeptideDose.query.filter_by(user_id=u.id, date=date(2026, 8, 20), compound="BPC-157").all()
    assert len(rows) == 1  # no duplicate row from the (user_id, date, compound) upsert key
    assert rows[0].id == row_id
    assert rows[0].time == "08:00"
    assert rows[0].taken_at == taken_at_before


# ── (e) dose_mg change on a taken row → skipped + reported ─────────────────

def test_dose_mg_change_on_taken_row_is_skipped_and_reported(app_ctx, monkeypatch, tmp_path):
    app_, db = app_ctx
    u = _fresh_user(app_, db, "import-dosemgtaken@test.com")
    _set_today(monkeypatch, date(2026, 8, 20))
    client = _client(app_, monkeypatch)

    csv_path = str(tmp_path / "protocol.csv")
    _write_csv(csv_path, [_row("2026-08-20", "07:00", "Injection", "BPC-157", "0.25", "10u", "Thigh", "n")])
    r1 = _post_import(client, u.email, csv_path=csv_path)
    assert r1.status_code == 200

    row = _get_row(db, u.id, date(2026, 8, 20), "BPC-157")
    row.taken_at = datetime(2026, 8, 20, 8, 0, 0)
    db.session.commit()

    _write_csv(csv_path, [_row("2026-08-20", "07:00", "Injection", "BPC-157", "0.5", "10u", "Thigh", "n")])
    r2 = _post_import(client, u.email, csv_path=csv_path)
    assert r2.status_code == 200, r2.get_data(as_text=True)
    body2 = r2.get_json()
    assert body2["updated"] == 0
    assert body2["imported"] == 0
    assert len(body2["skipped"]) == 1
    entry = body2["skipped"][0]
    assert entry["date"] == "2026-08-20"
    assert entry["compound"] == "BPC-157"
    assert entry["field"] == "dose_mg"
    assert entry["db_value"] == 0.25
    assert entry["csv_value"] == 0.5
    assert entry["reason"]  # human-readable explanation present (non-empty string)

    db.session.expire_all()
    row = _get_row(db, u.id, date(2026, 8, 20), "BPC-157")
    assert row.dose_mg == 0.25
    assert row.taken_at is not None


# ── (f) removing today's dose: unchecked → deleted; checked → kept+annotated ─

def test_removing_today_dose_unchecked_deleted_checked_kept_and_annotated(app_ctx, monkeypatch, tmp_path):
    app_, db = app_ctx
    u = _fresh_user(app_, db, "import-remove@test.com")
    _set_today(monkeypatch, date(2026, 8, 20))
    client = _client(app_, monkeypatch)

    csv_path = str(tmp_path / "protocol.csv")
    _write_csv(csv_path, [
        _row("2026-08-20", "07:00", "Injection", "BPC-157", "0.25", "10u", "Thigh", "unchecked, will be removed"),
        _row("2026-08-20", "07:00", "Injection", "KPV", "1", "10u", "Love handle", "checked, will be removed"),
        _row("2026-08-25", "07:00", "Oral", "Enclomiphene", "6.25", "-", "-", "unrelated future row"),
    ])
    r1 = _post_import(client, u.email, csv_path=csv_path)
    assert r1.status_code == 200, r1.get_data(as_text=True)
    assert r1.get_json()["imported"] == 3

    kpv_row = _get_row(db, u.id, date(2026, 8, 20), "KPV")
    kpv_row.taken_at = datetime(2026, 8, 20, 7, 5, 0)
    db.session.commit()
    kpv_id = kpv_row.id

    # New CSV drops BOTH today rows for 2026-08-20, keeps the unrelated future row.
    _write_csv(csv_path, [
        _row("2026-08-25", "07:00", "Oral", "Enclomiphene", "6.25", "-", "-", "unrelated future row"),
    ])
    r2 = _post_import(client, u.email, csv_path=csv_path)
    assert r2.status_code == 200, r2.get_data(as_text=True)
    body2 = r2.get_json()
    assert body2["deleted"] == 1  # only the unchecked BPC-157 row
    assert body2["updated"] == 1  # the checked KPV row gets its notes annotated

    kpv_skips = [s for s in body2["skipped"] if s["compound"] == "KPV" and s["date"] == "2026-08-20"]
    assert len(kpv_skips) == 1  # the annotate-instead-of-delete divergence is reported
    assert kpv_skips[0]["db_value"] is None
    assert kpv_skips[0]["csv_value"] is None
    assert kpv_skips[0]["reason"]

    from models import PeptideDose
    bpc = _get_row(db, u.id, date(2026, 8, 20), "BPC-157")
    assert bpc is None  # gone

    db.session.expire_all()
    kpv = _get_row(db, u.id, date(2026, 8, 20), "KPV")
    assert kpv is not None
    assert kpv.id == kpv_id
    assert kpv.taken_at is not None
    assert "[removed from protocol]" in kpv.notes


# ── (g) past-date rows are immutable unless force_past=true ────────────────

def test_past_rows_immutable_unless_force_past(app_ctx, monkeypatch, tmp_path):
    app_, db = app_ctx
    u = _fresh_user(app_, db, "import-pastlock@test.com")
    client = _client(app_, monkeypatch)

    csv_path = str(tmp_path / "protocol.csv")

    # Day 1: import while 2026-08-19 is still "today or future" — the row lands.
    _set_today(monkeypatch, date(2026, 8, 19))
    _write_csv(csv_path, [_row("2026-08-19", "07:00", "Injection", "BPC-157", "0.25", "10u", "Thigh", "n")])
    r1 = _post_import(client, u.email, csv_path=csv_path)
    assert r1.status_code == 200, r1.get_data(as_text=True)
    assert r1.get_json()["imported"] == 1

    # Time passes: "today" is now 2026-08-20, so 2026-08-19 is in the past.
    _set_today(monkeypatch, date(2026, 8, 20))

    # v2: existing past row's dose_mg diverges, AND a brand-new past-dated row appears.
    _write_csv(csv_path, [
        _row("2026-08-19", "07:00", "Injection", "BPC-157", "0.5", "10u", "Thigh", "n"),
        _row("2026-08-18", "07:00", "Injection", "TB-500", "2.5", "25u", "Thigh (opposite)", "n"),
    ])

    r2 = _post_import(client, u.email, csv_path=csv_path)
    assert r2.status_code == 200, r2.get_data(as_text=True)
    body2 = r2.get_json()
    assert body2["imported"] == 0
    assert body2["updated"] == 0
    assert body2["deleted"] == 0
    fields_reported = {(s["date"], s["compound"], s["field"]) for s in body2["skipped"]}
    assert ("2026-08-19", "BPC-157", "dose_mg") in fields_reported
    assert ("2026-08-18", "TB-500", "row") in fields_reported

    from models import PeptideDose
    assert PeptideDose.query.filter_by(user_id=u.id).count() == 1  # unchanged
    unchanged = _get_row(db, u.id, date(2026, 8, 19), "BPC-157")
    assert unchanged.dose_mg == 0.25  # NOT overwritten
    assert _get_row(db, u.id, date(2026, 8, 18), "TB-500") is None  # NOT inserted

    # force_past=true: the SAME CSV now applies both changes.
    r3 = _post_import(client, u.email, csv_path=csv_path, force_past=True)
    assert r3.status_code == 200, r3.get_data(as_text=True)
    body3 = r3.get_json()
    assert body3["updated"] == 1  # the dose_mg correction on 08-19
    assert body3["imported"] == 1  # the new 08-18 row

    # force_past still LOGS what it changed in `skipped`, with real values
    # (not free text) plus a human-readable `reason`.
    by_key = {(s["date"], s["compound"], s["field"]): s for s in body3["skipped"]}
    dose_entry = by_key[("2026-08-19", "BPC-157", "dose_mg")]
    assert dose_entry["db_value"] == 0.25
    assert dose_entry["csv_value"] == 0.5
    assert dose_entry["reason"]
    row_entry = by_key[("2026-08-18", "TB-500", "row")]
    assert row_entry["db_value"] is None
    assert row_entry["csv_value"] is None
    assert row_entry["reason"]

    db.session.expire_all()
    corrected = _get_row(db, u.id, date(2026, 8, 19), "BPC-157")
    assert corrected.dose_mg == 0.5
    inserted = _get_row(db, u.id, date(2026, 8, 18), "TB-500")
    assert inserted is not None
    assert inserted.dose_mg == 2.5


# ── (h) duplicate (date, compound) in the CSV → 400, nothing written ───────

def test_duplicate_date_compound_rejects_whole_file(app_ctx, monkeypatch, tmp_path):
    app_, db = app_ctx
    u = _fresh_user(app_, db, "import-dup@test.com")
    _set_today(monkeypatch, date(2026, 8, 20))
    client = _client(app_, monkeypatch)

    csv_path = str(tmp_path / "protocol.csv")
    _write_csv(csv_path, [
        _row("2026-08-20", "07:00", "Injection", "BPC-157", "0.25", "10u", "Thigh", "first"),
        _row("2026-08-20", "19:00", "Injection", "BPC-157", "0.25", "10u", "Thigh", "duplicate"),
    ])
    r = _post_import(client, u.email, csv_path=csv_path)
    assert r.status_code == 400, r.get_data(as_text=True)

    from models import PeptideDose
    assert PeptideDose.query.filter_by(user_id=u.id).count() == 0  # nothing written


# ── (i) property: no import ever deletes a taken row ────────────────────────

def test_taken_row_never_deleted_across_metadata_dose_and_removal_attempts(app_ctx, monkeypatch, tmp_path):
    app_, db = app_ctx
    u = _fresh_user(app_, db, "import-nvrdelete@test.com")
    _set_today(monkeypatch, date(2026, 8, 20))
    client = _client(app_, monkeypatch)

    csv_path = str(tmp_path / "protocol.csv")
    _write_csv(csv_path, [_row("2026-08-20", "07:00", "Injection", "BPC-157", "0.25", "10u", "Thigh", "n")])
    r1 = _post_import(client, u.email, csv_path=csv_path)
    assert r1.status_code == 200

    row = _get_row(db, u.id, date(2026, 8, 20), "BPC-157")
    row.taken_at = datetime(2026, 8, 20, 7, 5, 0)
    db.session.commit()
    row_id = row.id

    # 1) metadata-only change — survives.
    _write_csv(csv_path, [_row("2026-08-20", "09:00", "Injection", "BPC-157", "0.25", "10u", "Chest", "moved")])
    _post_import(client, u.email, csv_path=csv_path)
    db.session.expire_all()
    assert _get_row(db, u.id, date(2026, 8, 20), "BPC-157").id == row_id

    # 2) dose_mg conflict — skipped, still survives.
    _write_csv(csv_path, [_row("2026-08-20", "09:00", "Injection", "BPC-157", "9.99", "10u", "Chest", "moved")])
    _post_import(client, u.email, csv_path=csv_path)
    db.session.expire_all()
    assert _get_row(db, u.id, date(2026, 8, 20), "BPC-157").id == row_id

    # 3) dropped from the CSV entirely — kept + annotated, still survives.
    _write_csv(csv_path, [_row("2026-08-25", "07:00", "Oral", "Enclomiphene", "6.25", "-", "-", "unrelated")])
    r4 = _post_import(client, u.email, csv_path=csv_path)
    assert r4.get_json()["deleted"] == 0
    db.session.expire_all()
    survivor = _get_row(db, u.id, date(2026, 8, 20), "BPC-157")
    assert survivor is not None
    assert survivor.id == row_id
    assert survivor.taken_at is not None


# ── FIX ROUND 1: future-dated taken row is never deleted (CRITICAL) ────────
# The original delete pass only guarded the `date == today` branch against
# taken_at; a `date > today` row with taken_at set was deleted outright.
# This is a direct regression test for that bug.

def test_future_taken_row_never_deleted_kept_annotated_and_reported(app_ctx, monkeypatch, tmp_path):
    app_, db = app_ctx
    u = _fresh_user(app_, db, "import-futuretaken@test.com")
    _set_today(monkeypatch, date(2026, 8, 20))
    client = _client(app_, monkeypatch)

    csv_path = str(tmp_path / "protocol.csv")
    _write_csv(csv_path, [
        _row("2026-08-24", "07:00", "Injection", "Retatrutide", "3", "30u", "Abdomen", "future, escalation dose"),
    ])
    r1 = _post_import(client, u.email, csv_path=csv_path)
    assert r1.status_code == 200, r1.get_data(as_text=True)
    assert r1.get_json()["imported"] == 1

    future_row = _get_row(db, u.id, date(2026, 8, 24), "Retatrutide")
    # A future-dated dose can legitimately already be marked taken (e.g. an
    # early/ahead-of-schedule injection logged by the user).
    future_row.taken_at = datetime(2026, 8, 24, 6, 0, 0)
    db.session.commit()
    future_id = future_row.id

    # New CSV drops the future row entirely.
    _write_csv(csv_path, [
        _row("2026-08-25", "07:00", "Oral", "Enclomiphene", "6.25", "-", "-", "unrelated"),
    ])
    r2 = _post_import(client, u.email, csv_path=csv_path)
    assert r2.status_code == 200, r2.get_data(as_text=True)
    body2 = r2.get_json()
    assert body2["deleted"] == 0  # the taken future row must NOT be deleted
    assert body2["updated"] == 1  # it gets annotated instead

    reta_skips = [s for s in body2["skipped"] if s["compound"] == "Retatrutide" and s["date"] == "2026-08-24"]
    assert len(reta_skips) == 1
    assert reta_skips[0]["db_value"] is None
    assert reta_skips[0]["csv_value"] is None
    assert reta_skips[0]["reason"]

    db.session.expire_all()
    survivor = _get_row(db, u.id, date(2026, 8, 24), "Retatrutide")
    assert survivor is not None
    assert survivor.id == future_id
    assert survivor.taken_at is not None
    assert "[removed from protocol]" in survivor.notes


# ── FIX ROUND 1: force_past vs. deletion of past, untaken, CSV-absent rows ──
# Ruling: force_past=true ALSO unlocks deletion of past-dated UNTAKEN rows
# absent from the CSV (logged in skipped); without force_past, such a row is
# left untouched but now REPORTED in skipped (previously a silent no-op).

def test_past_untaken_row_absent_from_csv_reported_then_deleted_with_force_past(app_ctx, monkeypatch, tmp_path):
    app_, db = app_ctx
    u = _fresh_user(app_, db, "import-pastabsent@test.com")
    client = _client(app_, monkeypatch)

    csv_path = str(tmp_path / "protocol.csv")

    # Day 1: import a row while it's still today-or-future — it lands, untaken.
    _set_today(monkeypatch, date(2026, 8, 19))
    _write_csv(csv_path, [_row("2026-08-19", "07:00", "Injection", "KPV", "1", "10u", "Love handle", "n")])
    r1 = _post_import(client, u.email, csv_path=csv_path)
    assert r1.status_code == 200, r1.get_data(as_text=True)
    assert r1.get_json()["imported"] == 1

    # Time passes: "today" is now 2026-08-20 — the row is now in the past.
    _set_today(monkeypatch, date(2026, 8, 20))

    # v2: the doctor's CSV no longer lists 2026-08-19 KPV at all.
    _write_csv(csv_path, [_row("2026-08-25", "07:00", "Oral", "Enclomiphene", "6.25", "-", "-", "unrelated")])

    # Without force_past: left untouched, but now reported.
    r2 = _post_import(client, u.email, csv_path=csv_path)
    assert r2.status_code == 200, r2.get_data(as_text=True)
    body2 = r2.get_json()
    assert body2["deleted"] == 0
    kpv_skips = [s for s in body2["skipped"] if s["compound"] == "KPV" and s["date"] == "2026-08-19"]
    assert len(kpv_skips) == 1
    assert kpv_skips[0]["db_value"] is None
    assert kpv_skips[0]["csv_value"] is None
    assert kpv_skips[0]["reason"]

    from models import PeptideDose
    # 2026-08-19 KPV (untouched) + the unrelated 2026-08-25 row just imported.
    assert PeptideDose.query.filter_by(user_id=u.id).count() == 2
    assert PeptideDose.query.filter_by(user_id=u.id, date=date(2026, 8, 19), compound="KPV").first() is not None

    # With force_past=true: actually deleted, and logged.
    r3 = _post_import(client, u.email, csv_path=csv_path, force_past=True)
    assert r3.status_code == 200, r3.get_data(as_text=True)
    body3 = r3.get_json()
    assert body3["deleted"] == 1
    kpv_skips3 = [s for s in body3["skipped"] if s["compound"] == "KPV" and s["date"] == "2026-08-19"]
    assert len(kpv_skips3) == 1
    assert kpv_skips3[0]["reason"]

    assert PeptideDose.query.filter_by(user_id=u.id, date=date(2026, 8, 19), compound="KPV").first() is None


# ── (j) whole-file integrity, documentation test ────────────────────────────
# The genuine mismatch/partial-import path is impossible to construct from
# outside the endpoint (it's an internal safety net around the write logic
# itself); per the brief this is exercised indirectly via the duplicate-CSV
# 400 path (nothing written) plus the exact row_count on a fresh import.

def test_row_count_matches_csv_and_duplicate_path_writes_nothing(app_ctx, monkeypatch, tmp_path):
    app_, db = app_ctx
    u = _fresh_user(app_, db, "import-integrity@test.com")
    _set_today(monkeypatch, date(2026, 8, 10))
    client = _client(app_, monkeypatch)

    r = _post_import(client, u.email, csv_path=REAL_CSV_PATH)
    assert r.status_code == 200
    assert r.get_json()["row_count"] == 381

    u2 = _fresh_user(app_, db, "import-integrity-dup@test.com")
    _set_today(monkeypatch, date(2026, 8, 20))
    csv_path = str(tmp_path / "dup.csv")
    _write_csv(csv_path, [
        _row("2026-08-20", "07:00", "Injection", "BPC-157", "0.25", "10u", "Thigh", "a"),
        _row("2026-08-20", "08:00", "Injection", "BPC-157", "0.25", "10u", "Thigh", "b"),
    ])
    r2 = _post_import(client, u2.email, csv_path=csv_path)
    assert r2.status_code == 400
    from models import PeptideDose
    assert PeptideDose.query.filter_by(user_id=u2.id).count() == 0


# ── auth: X-Admin-Key required (mirrors tests/test_security_auth.py) ───────

def test_import_requires_admin_key(app_ctx, monkeypatch):
    app_, db = app_ctx
    u = _fresh_user(app_, db, "import-noauth@test.com")
    monkeypatch.setenv("ADMIN_API_KEY", "sekrit-test-key-long-enough-to-pass-0123")
    client = app_.test_client()
    r = client.post(f"/api/admin/import-protocol?email={u.email}", json={"csv_path": REAL_CSV_PATH})
    assert r.status_code in (401, 403)


# ── (S012) csv_text body + dry_run diff ─────────────────────────────────────

def test_csv_text_body_and_dry_run_diff(app_ctx, monkeypatch):
    """The locally edited CSV can be POSTed as text (no deploy); dry_run
    returns the identical per-row change list and writes nothing."""
    from models import PeptideDose
    app_, db = app_ctx
    u = _fresh_user(app_, db, "import-csvtext@test.com")
    _set_today(monkeypatch, date(2026, 8, 10))
    client = _client(app_, monkeypatch)
    with open(REAL_CSV_PATH) as f:
        text = f.read()
    r = _post_import(client, u.email, csv_text=text)
    assert r.status_code == 200 and r.get_json()["imported"] == 381

    # edit one future row in the text: Tesamorelin 2026-09-01 1 mg → 1.5 mg
    edited = text.replace("2026-09-01,22:00,Injection,Tesamorelin,1,10u", "2026-09-01,22:00,Injection,Tesamorelin,1.5,15u", 1)
    assert edited != text
    r = _post_import(client, u.email, csv_text=edited, dry_run=True)
    body = r.get_json()
    assert body["dry_run"] is True and body["updated"] == 1
    ops = [(c["op"], c["date"], c["compound"], c["field"]) for c in body["changes"]]
    assert ("update", "2026-09-01", "Tesamorelin", "dose_mg") in ops
    db.session.expire_all()
    row = PeptideDose.query.filter_by(user_id=u.id, date=date(2026, 9, 1), compound="Tesamorelin").first()
    assert row.dose_mg == 1.0  # dry run wrote nothing

    r = _post_import(client, u.email, csv_text=edited)
    assert r.get_json()["updated"] == 1
    db.session.expire_all()
    assert PeptideDose.query.filter_by(user_id=u.id, date=date(2026, 9, 1), compound="Tesamorelin").first().dose_mg == 1.5
