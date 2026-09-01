"""S044/S015: no destructive DDL at boot; no dead destructive GET routes;
cross-site state changes refused."""
import pathlib
import re
import pytest

SRC = pathlib.Path(__file__).resolve().parent.parent / "app.py"


def test_no_drop_table_or_column_outside_fix_indexes():
    src = SRC.read_text()
    for m in re.finditer(r"DROP (TABLE|COLUMN)", src):
        # locate the enclosing def
        head = src[:m.start()]
        fn = re.findall(r"\ndef (\w+)\(", head)
        assert fn and fn[-1] in ("api_admin_fix_indexes",), \
            f"destructive DDL outside the admin fix-indexes route: in {fn[-1] if fn else 'module scope'}"


def test_dead_destructive_get_routes_are_gone():
    src = SRC.read_text()
    for route in ("/reset-onboarding", "/restart-plan", "/redo-measurements", "/redo-equipment"):
        assert f'@app.route("{route}")' not in src, route


@pytest.fixture(scope="module")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db


def test_cross_site_post_to_api_is_refused(app_ctx):
    app_, _ = app_ctx
    c = app_.test_client()
    r = c.post("/api/run-log", json={"week": 1}, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    r = c.post("/api/run-log", json={"week": 1}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    # same-origin / header-less callers pass the guard (and hit normal auth)
    r = c.post("/api/run-log", json={"week": 1}, headers={"Sec-Fetch-Site": "same-origin"})
    assert r.status_code != 403
    r = c.post("/api/run-log", json={"week": 1})
    assert r.status_code != 403


def test_coach_assembler_never_imports_app():
    """S070: the app ↔ coach_assembler cycle is broken; keep it that way."""
    src = pathlib.Path("coach_assembler.py").read_text()
    assert "from app import" not in src and "import app\n" not in src
