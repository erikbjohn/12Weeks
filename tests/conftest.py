"""Test config: point the app at a fresh sqlite DB before app import.

The app module reads DATABASE_URL at import time, so this must run before any
`from app import ...` statement. pytest loads conftest.py first.
"""
import os
import sys
import tempfile

# Use a per-process temp DB path before app.py imports.
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ.setdefault("FLASK_SECRET_KEY", "test-secret")

# Make project root importable so `from app import app, db, ...` works.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
