"""Audit-specific pytest fixtures."""
from __future__ import annotations
import pytest
from datetime import datetime


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
    return datetime.utcnow().strftime("%Y%m%d-%H%M%S")


@pytest.fixture(scope="session")
def audit_mode(request) -> str:
    return request.config.getoption("--audit-mode")
