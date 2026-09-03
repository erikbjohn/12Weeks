#!/usr/bin/env python3
"""Reconstruct peptide_dose_history from what exists (2026-09-03):

  1. every git version of peptide_protocol.csv — consecutive versions are
     diffed by (Date, Compound); each difference becomes a history row dated
     at the commit, source csv_import, reason = the commit subject;
  2. the one known direct-on-prod edit the CSV never carried until the
     2026-09-03 sync (GHK-Cu 1 -> 2 mg from 2026-08-27, per the row note) is
     re-dated to 2026-08-27 and tagged admin_exec;
  3. every taken_at on prod becomes an athlete_toggle row at that time.

All rows are POSTed to /api/admin/protocol-history/backfill, which tags them
backfill:<source> and is idempotent. Dry run by default; --apply to write.

Usage: venv/bin/python scripts/protocol_history_backfill.py [--apply]
"""
import csv, io, json, os, subprocess, sys, urllib.request
from datetime import datetime, timezone

BASE = "https://one2weeks-9ewf.onrender.com"
EMAIL = "erik@placemetry.com"
FIELDS = {"Time": "time", "Event_Type": "event_type", "Dose_mg": "dose_mg", "Syringe_Units": "syringe_units",
          "Site": "site", "Notes": "notes"}
SYNC_COMMIT_PREFIX = "protocol: Tesamorelin moves to 07:00 mornings"   # e66bbb0: CSV caught up to prod


def _git(*args):
    return subprocess.check_output(["git", *args], cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))).decode("utf-8", "replace")


def _norm(v):
    v = (v or "").strip()
    try:
        f = float(v)
        return str(int(f)) if f == int(f) else str(f)
    except ValueError:
        return v


def _parse(text):
    rows = {}
    for r in csv.DictReader(io.StringIO(text)):
        if not r.get("Date"):
            continue
        rows[(r["Date"].strip(), r["Compound"].strip())] = {k: _norm(r.get(k)) for k in FIELDS}
    return rows


def _row_json(r):
    return json.dumps({FIELDS[k]: (r[k] or None) for k in FIELDS} | {"taken_at": None}, sort_keys=True)


def from_git():
    out = []
    log = [l for l in _git("log", "--format=%H|%cI|%s", "--reverse", "--", "peptide_protocol.csv").splitlines() if l]
    prev = {}
    for line in log:
        sha, when, subject = line.split("|", 2)
        cur = _parse(_git("show", f"{sha}:peptide_protocol.csv"))
        when_utc = datetime.fromisoformat(when).astimezone(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
        is_sync = subject.startswith(SYNC_COMMIT_PREFIX)
        for key in sorted(set(prev) | set(cur)):
            d, comp = key
            b, a = prev.get(key), cur.get(key)
            base = {"date": d, "compound": comp, "source": "csv_import", "reason": f"{sha[:7]} {subject}", "changed_at": when_utc}
            if b is None:
                out.append(base | {"field": "row", "old_value": None, "new_value": _row_json(a)})
            elif a is None:
                out.append(base | {"field": "row", "old_value": _row_json(b), "new_value": None})
            else:
                for k, f in FIELDS.items():
                    if b[k] != a[k]:
                        row = base | {"field": f, "old_value": b[k] or None, "new_value": a[k] or None}
                        if is_sync and comp == "GHK-Cu":
                            # the CSV was catching up to a prod edit made on 08-27
                            row |= {"source": "admin_exec", "changed_at": "2026-08-27T19:00:00",
                                    "reason": "set directly on prod 2026-08-27 (debug/exec) — the CSV only caught up on 2026-09-03 (e66bbb0)"}
                        out.append(row)
        prev = cur
    return out


def from_prod_taken(read_key):
    req = urllib.request.Request(BASE + "/api/admin/debug/sql",
        data=json.dumps({"sql": "SELECT id,date,compound,taken_at FROM peptide_dose WHERE user_id=1 AND taken_at IS NOT NULL"}).encode(),
        headers={"X-Admin-Key": read_key, "Content-Type": "application/json"}, method="POST")
    rows = json.load(urllib.request.urlopen(req, timeout=60))["rows"]
    out = []
    for r in rows:
        d = datetime.strptime(r["date"], "%a, %d %b %Y %H:%M:%S %Z").date().isoformat()
        ta = datetime.strptime(r["taken_at"], "%a, %d %b %Y %H:%M:%S %Z").isoformat(timespec="seconds")
        out.append({"date": d, "compound": r["compound"], "dose_id": r["id"], "field": "taken_at", "old_value": None,
                    "new_value": ta, "changed_at": ta, "source": "athlete_toggle", "reason": None})
    return out


def main(argv):
    apply = "--apply" in argv
    read_key = open(os.path.expanduser("~/.12weeks_admin_read_key")).read().strip()
    write_key = open(os.path.expanduser("~/.12weeks_admin_key")).read().strip()
    rows = from_git() + from_prod_taken(read_key)
    by = {}
    for r in rows:
        by[(r["source"], r["field"])] = by.get((r["source"], r["field"]), 0) + 1
    print(f"{len(rows)} history rows reconstructed:", json.dumps({f"{k[0]}/{k[1]}": v for k, v in sorted(by.items())}, indent=1))
    req = urllib.request.Request(BASE + "/api/admin/protocol-history/backfill",
        data=json.dumps({"email": EMAIL, "rows": rows, "dry_run": not apply}).encode(),
        headers={"X-Admin-Key": write_key, "Content-Type": "application/json"}, method="POST")
    print(json.load(urllib.request.urlopen(req, timeout=300)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
