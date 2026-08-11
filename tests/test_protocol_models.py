"""PeptideDose / PeptideVial / LabReminder model contracts."""
from datetime import date, datetime, timezone
import pytest

@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db

def _user(db, email="protomodels@test.com"):
    from models import User
    u = User.query.filter_by(email=email).first()
    if not u:
        u = User(email=email)
        db.session.add(u); db.session.commit()
    return u

def test_peptide_dose_upsert_key_is_user_date_compound(app_ctx):
    app_, db = app_ctx
    from models import PeptideDose
    u = _user(db)
    PeptideDose.query.filter_by(user_id=u.id).delete(); db.session.commit()
    d = PeptideDose(user_id=u.id, date=date(2026, 8, 10), time="07:00",
                    event_type="Injection", compound="Retatrutide",
                    dose_mg=2.0, syringe_units="20u", site="Abdomen",
                    notes="Inject slowly 5-10sec")
    db.session.add(d); db.session.commit()
    assert d.taken_at is None
    # same (user, date, compound) again must violate the unique constraint
    dup = PeptideDose(user_id=u.id, date=date(2026, 8, 10), time="08:00",
                      event_type="Injection", compound="Retatrutide", dose_mg=2.0)
    db.session.add(dup)
    with pytest.raises(Exception):
        db.session.commit()
    db.session.rollback()

def test_peptide_vial_is_mg_based(app_ctx):
    app_, db = app_ctx
    from models import PeptideVial
    u = _user(db)
    v = PeptideVial(user_id=u.id, compound="Retatrutide", total_mg=20.0,
                    reconstituted_on=date(2026, 8, 10), expiry_days=28)
    db.session.add(v); db.session.commit()
    assert not hasattr(v, "total_doses")  # dose-count columns must NOT exist
    assert not hasattr(v, "doses_used")

def test_lab_reminder_fields(app_ctx):
    app_, db = app_ctx
    from models import LabReminder
    u = _user(db)
    r = LabReminder(user_id=u.id, label="Week-8 labs: T/E2, IGF-1, fasting glucose/A1c, lipids",
                    due_date=date(2026, 9, 28))
    db.session.add(r); db.session.commit()
    assert r.completed_at is None
