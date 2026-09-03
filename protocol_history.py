"""Change log for the peptide protocol (2026-09-03).

Every write to peptide_dose — CSV import, the athlete's taken/untaken tap, a
late take, raw admin SQL — lands in peptide_dose_history automatically:

* ORM writes: a `before_flush` listener on the session diffs each dirty
  PeptideDose's attribute history and writes one row per changed field;
  inserts and deletes write a single field='row' entry carrying the whole
  row as JSON.
* Raw SQL (admin debug/exec): the route calls snapshot() before and
  diff_snapshots() after, which produces the same rows.

The SOURCE of a change is request-scoped: a route calls set_source() and
the listener reads it; outside a request (scripts) the default is used.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone

from models import db, PeptideDose, PeptideDoseHistory

TRACKED = ("time", "event_type", "dose_mg", "syringe_units", "site", "notes", "taken_at")
DEFAULT_SOURCE = "orm"


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _fmt(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat(timespec="seconds")
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v)


def _row_json(r):
    return json.dumps({"time": r.time, "event_type": r.event_type, "dose_mg": r.dose_mg,
                       "syringe_units": r.syringe_units, "site": r.site, "notes": r.notes,
                       "taken_at": _fmt(r.taken_at)}, sort_keys=True)


def set_source(source: str, reason: str | None = None):
    """Tag every peptide_dose write in this request with a source + reason."""
    try:
        from flask import g, has_request_context
        if has_request_context():
            g._protocol_change_source = source
            g._protocol_change_reason = reason
            return
    except Exception:
        pass
    global _script_source, _script_reason
    _script_source, _script_reason = source, reason


_script_source, _script_reason = None, None


def current_source():
    try:
        from flask import g, has_request_context, request
        if has_request_context():
            src = getattr(g, "_protocol_change_source", None)
            if src:
                return src, getattr(g, "_protocol_change_reason", None)
            return DEFAULT_SOURCE, (request.path if request else None)
    except Exception:
        pass
    return (_script_source or DEFAULT_SOURCE), _script_reason


def _entry(r, field, old, new, source, reason, changed_at=None, dose_id=None):
    return PeptideDoseHistory(user_id=r.user_id, dose_id=dose_id if dose_id is not None else getattr(r, "id", None),
                              date=r.date, compound=r.compound, field=field,
                              old_value=_fmt(old), new_value=_fmt(new),
                              changed_at=changed_at or _now(), source=source, reason=reason)


def _before_flush(session, flush_context, instances):
    from sqlalchemy import inspect
    source, reason = current_source()
    now = _now()
    new_entries = []
    for obj in list(session.new):
        if isinstance(obj, PeptideDose):
            new_entries.append(_entry(obj, "row", None, _row_json(obj), source, reason, now))
    for obj in list(session.deleted):
        if isinstance(obj, PeptideDose):
            new_entries.append(_entry(obj, "row", _row_json(obj), None, source, reason, now))
    dirty = [o for o in session.dirty if isinstance(o, PeptideDose) and session.is_modified(o) and getattr(o, "id", None)]
    if dirty:
        # Old values come from the DATABASE row, not attribute history:
        # after a commit the instance is expired, and setting an expired
        # attribute leaves no 'deleted' value in its history.
        from sqlalchemy import text as _text
        cols = ", ".join(TRACKED)
        for obj in dirty:
            with session.no_autoflush:
                row = session.execute(_text(f"SELECT {cols} FROM peptide_dose WHERE id = :id"), {"id": obj.id}).first()
            if row is None:
                continue
            for i, f in enumerate(TRACKED):
                old, new = row[i], getattr(obj, f)
                if f == "taken_at" and isinstance(old, str):
                    try:
                        old = datetime.fromisoformat(old)
                    except Exception:
                        pass
                if _fmt(old) == _fmt(new):
                    continue
                new_entries.append(_entry(obj, f, old, new, source, reason, now))
    for e in new_entries:
        session.add(e)


_installed = False


def install():
    """Attach the flush listener once (called at app import)."""
    global _installed
    if _installed:
        return
    from sqlalchemy import event
    from sqlalchemy.orm import Session
    event.listen(Session, "before_flush", _before_flush)
    _installed = True


def snapshot(user_id=None):
    """{(user_id, date, compound): {id, fields...}} for raw-SQL diffing."""
    q = PeptideDose.query
    if user_id is not None:
        q = q.filter_by(user_id=user_id)
    out = {}
    for r in q.all():
        out[(r.user_id, r.date, r.compound)] = {"id": r.id, **{f: getattr(r, f) for f in TRACKED}}
    return out


def diff_snapshots(before, after, source, reason, changed_at=None):
    """Write history rows for every difference between two snapshots. Returns count."""
    from types import SimpleNamespace as NS
    n = 0
    now = changed_at or _now()
    for key in sorted(set(before) | set(after), key=lambda k: (k[0], k[1].isoformat(), k[2])):
        uid, d, comp = key
        b, a = before.get(key), after.get(key)
        stub = NS(user_id=uid, date=d, compound=comp, id=(a or b)["id"])
        if b is None:
            db.session.add(_entry(stub, "row", None, json.dumps({f: _fmt(a[f]) for f in TRACKED}, sort_keys=True), source, reason, now)); n += 1
        elif a is None:
            db.session.add(_entry(stub, "row", json.dumps({f: _fmt(b[f]) for f in TRACKED}, sort_keys=True), None, source, reason, now)); n += 1
        else:
            for f in TRACKED:
                if _fmt(b[f]) != _fmt(a[f]):
                    db.session.add(_entry(stub, f, b[f], a[f], source, reason, now)); n += 1
    return n


def grouped_history(user_id, limit=200):
    """Collapse per-row entries into human-readable change groups: the same
    (minute, source, reason, compound, field, old, new) across a date range
    becomes one line with a row count."""
    rows = (PeptideDoseHistory.query.filter_by(user_id=user_id)
            .order_by(PeptideDoseHistory.changed_at.desc(), PeptideDoseHistory.id.desc()).limit(5000).all())
    groups = {}
    order = []
    for r in rows:
        minute = r.changed_at.replace(second=0, microsecond=0)
        k = (minute, r.source, r.reason or "", r.compound, r.field, r.old_value or "", r.new_value or "")
        g = groups.get(k)
        if g is None:
            g = {"changed_at": r.changed_at.isoformat(timespec="seconds"), "source": r.source, "reason": r.reason,
                 "compound": r.compound, "field": r.field, "old": r.old_value, "new": r.new_value,
                 "from_date": r.date.isoformat(), "to_date": r.date.isoformat(), "rows": 0}
            groups[k] = g; order.append(k)
        g["rows"] += 1
        g["from_date"] = min(g["from_date"], r.date.isoformat())
        g["to_date"] = max(g["to_date"], r.date.isoformat())
    out = [groups[k] for k in order]
    return out[:limit]
