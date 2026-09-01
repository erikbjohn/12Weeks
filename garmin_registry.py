"""Per-user Garmin client registry (S070). Lived in app.py, which forced
coach_assembler to `from app import _get_garmin` inside a section builder —
an app ↔ coach_assembler import cycle that only worked because the import
was deferred. No Flask app import here; the registry is process-global.
"""
from __future__ import annotations

import threading

from garmin_client import GarminClient

_garmin_clients: dict = {}
# Per-user push locks: serializes concurrent push_week calls (marker thread vs
# generation hook) so a single user never has two simultaneous pushes racing.
_garmin_push_locks: dict = {}
_garmin_push_locks_guard = threading.Lock()


def get_garmin(user_id=None):
    """Get or create the Garmin client for a user (None → an unbound client)."""
    if not user_id:
        try:
            from flask_login import current_user
            user_id = current_user.id if current_user and current_user.is_authenticated else None
        except Exception:
            user_id = None
    if not user_id:
        return GarminClient()
    if user_id not in _garmin_clients:
        _garmin_clients[user_id] = GarminClient(user_id=user_id)
    return _garmin_clients[user_id]


def drop_garmin(user_id):
    _garmin_clients.pop(user_id, None)


def push_lock(user_id):
    with _garmin_push_locks_guard:
        return _garmin_push_locks.setdefault(user_id, threading.Lock())
