#!/usr/bin/env python3
"""Laptop-side daily backup of the prod Postgres (S001, 2026-09-01).

Erik's training history — SetLog, BodyWeight, PeptideDose.taken_at, chat —
had exactly one copy on Render until this existed. This dumps it off-platform.

  pg_dump --format=custom  →  ~/12weeks-backups/<YYYY-MM-DD>.dump   (keep 30)
  GET /api/admin/export-full  →  ~/12weeks-backups/<YYYY-MM-DD>.json (sidecar)

Inputs (both 0600):
  ~/.12weeks_db_url     Render EXTERNAL connection string
  ~/.12weeks_admin_key  admin key for the JSON sidecar (optional)

Restore: pg_restore --no-owner --clean --if-exists -d <url> <file>.dump
Runs from launchd (scripts/com.12weeks.db-backup.plist); logs to
~/Library/Logs/12weeks-backup.log.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
import urllib.request

HOME = pathlib.Path.home()
BACKUP_DIR = HOME / "12weeks-backups"
KEEP = 30
PROD = "https://one2weeks-9ewf.onrender.com"
ERIK = "erik@placemetry.com"
# The server is Postgres 18: pg_dump refuses servers newer than itself, so
# the matching client is pinned explicitly rather than trusting PATH.
PG_DUMP_CANDIDATES = [
    "/opt/homebrew/opt/postgresql@18/bin/pg_dump",
    "/opt/homebrew/bin/pg_dump",
    "pg_dump",
]


def log(msg: str) -> None:
    print(f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def _read_secret(name: str) -> str | None:
    p = HOME / name
    try:
        return p.read_text().strip() or None
    except FileNotFoundError:
        return None


def _pg_dump_bin() -> str:
    for c in PG_DUMP_CANDIDATES:
        if os.path.isabs(c) and os.path.exists(c):
            return c
    return "pg_dump"


def dump_postgres(url: str, out: pathlib.Path) -> bool:
    tmp = out.with_suffix(".dump.partial")
    cmd = [_pg_dump_bin(), "--no-owner", "--no-privileges", "--format=custom",
           f"--file={tmp}", url]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        log(f"pg_dump FAILED rc={r.returncode}: {r.stderr.strip()[:400]}")
        tmp.unlink(missing_ok=True)
        return False
    tmp.rename(out)
    log(f"pg_dump ok → {out.name} ({out.stat().st_size:,} bytes)")
    return True


def export_json(admin_key: str, out: pathlib.Path) -> bool:
    req = urllib.request.Request(
        f"{PROD}/api/admin/export-full?email={ERIK}",
        headers={"X-Admin-Key": admin_key})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.load(resp)
    except Exception as e:  # network / auth / 5xx — the dump is the primary
        log(f"export-full FAILED: {e}")
        return False
    out.write_text(json.dumps(data, separators=(",", ":")))
    tables = data.get("tables") or {}
    log(f"export-full ok → {out.name} ({len(tables)} tables, "
        f"{sum(len(v) for v in tables.values()):,} rows)")
    return True


def prune(keep: int = KEEP) -> None:
    for pattern in ("*.dump", "*.json"):
        files = sorted(BACKUP_DIR.glob(pattern))
        for old in files[:-keep]:
            old.unlink()
            log(f"pruned {old.name}")


def main() -> int:
    BACKUP_DIR.mkdir(exist_ok=True)
    today = dt.date.today().isoformat()
    url = _read_secret(".12weeks_db_url")
    if not url:
        log("no ~/.12weeks_db_url — cannot dump")
        return 2
    ok = dump_postgres(url, BACKUP_DIR / f"{today}.dump")
    key = _read_secret(".12weeks_admin_key")
    if key:
        export_json(key, BACKUP_DIR / f"{today}.json")
    else:
        log("no ~/.12weeks_admin_key — skipping JSON sidecar")
    prune()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
