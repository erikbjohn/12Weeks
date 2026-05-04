"""Audit-specific pytest fixtures."""
from __future__ import annotations
import pytest
from datetime import datetime, timezone


def pytest_addoption(parser):
    parser.addoption(
        "--audit-mode",
        action="store",
        default="synthetic",
        choices=["synthetic", "full"],
        help="synthetic = synthetic users only (CI safe). full = include real-Erik fixture.",
    )


@pytest.fixture(scope="session")
def run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


@pytest.fixture(scope="session")
def audit_mode(request) -> str:
    return request.config.getoption("--audit-mode")


@pytest.fixture(scope="function")
def app_ctx():
    from app import app, db
    with app.app_context():
        db.create_all()
        yield app, db
        db.session.rollback()


@pytest.fixture(scope="function")
def phase_2_mid_program(app_ctx):
    from tests.coach_audit.users import make_phase_2_mid_program
    return make_phase_2_mid_program()


@pytest.fixture(scope="function")
def phase_1_newbie(app_ctx):
    from tests.coach_audit.users import make_phase_1_newbie
    return make_phase_1_newbie()


@pytest.fixture(scope="function")
def phase_3_cut(app_ctx):
    from tests.coach_audit.users import make_phase_3_cut
    return make_phase_3_cut()


@pytest.fixture(scope="function")
def no_gym_bw(app_ctx):
    from tests.coach_audit.users import make_no_gym_bw
    return make_no_gym_bw()
