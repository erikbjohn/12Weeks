#!/usr/bin/env python3
"""Non-interactive Garmin token refresher — the laptop half of keeping prod's
Garmin sync alive.

Why this exists (2026-08-12 outage): Garmin's OAuth2 access token lives ~19h
and can only be refreshed via the OAuth exchange endpoint, which Garmin
rate-blocks for server/datacenter IPs (Render). Every laptop-minted token
therefore dies within a day and prod's sync goes dark until a human re-runs
garmin_token_helper.py. This script closes the loop: run it on a schedule
from the laptop (launchd — see scripts/com.12weeks.garmin-refresh.plist);
when the stored OAuth2 has less than REFRESH_THRESHOLD_H of life left it
re-exchanges from the laptop's IP (no login, no MFA — the long-lived OAuth1
token does the work) and uploads the fresh dump to prod, where
/api/admin/garmin/save-tokens restores the live session and syncs
immediately.

Inputs:
- ~/.garmin_tokens.json  (garth dump; falls back to /tmp/garmin_tokens.txt,
  which macOS clears on reboot — the home path is the durable copy)
- Admin key: $ADMIN_API_KEY or ~/.12weeks_admin_key (0600)

Safe to run as often as you like: it exits without touching Garmin while the
token still has plenty of life.
"""
import json
import os
import sys
import time
import urllib.request

APP_URL = os.environ.get("APP_URL", "https://one2weeks-9ewf.onrender.com")
APP_EMAIL = os.environ.get("APP_EMAIL", "erik@placemetry.com")
TOKEN_PATHS = [os.path.expanduser("~/.garmin_tokens.json"), "/tmp/garmin_tokens.txt"]
# Copy of the last dump that PROD confirmed. Uploads are keyed on this, not on
# local freshness: a refresh whose upload failed (network blip, mid-deploy 502)
# must be retried on the next run even though the local token looks fresh —
# otherwise prod quietly keeps the dying pre-refresh token.
UPLOADED_MARKER = os.path.expanduser("~/.garmin_tokens.uploaded")
REFRESH_THRESHOLD_H = float(os.environ.get("GARMIN_REFRESH_THRESHOLD_H", "12"))
UPLOAD_ATTEMPTS = 3
UPLOAD_RETRY_WAIT_S = 30


def _log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def _admin_key():
    key = os.environ.get("ADMIN_API_KEY")
    if key:
        return key.strip()
    path = os.path.expanduser("~/.12weeks_admin_key")
    if os.path.exists(path):
        return open(path).read().strip()
    sys.exit("No admin key: set ADMIN_API_KEY or create ~/.12weeks_admin_key")


def _upload(dump):
    """POST the dump to prod's save-tokens; retried — the server restores the
    session AND syncs immediately, so this call can take a little while."""
    req = urllib.request.Request(
        f"{APP_URL}/api/admin/garmin/save-tokens",
        data=json.dumps({"email": APP_EMAIL, "tokens": dump}).encode(),
        headers={"Content-Type": "application/json", "X-Admin-Key": _admin_key()},
        method="POST")
    last_err = None
    for attempt in range(1, UPLOAD_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(req, timeout=240) as resp:
                body = json.loads(resp.read().decode())
            if body.get("connected"):
                return body
            last_err = f"response not live: {body}"
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
        _log(f"upload attempt {attempt}/{UPLOAD_ATTEMPTS} failed: {last_err}")
        if attempt < UPLOAD_ATTEMPTS:
            time.sleep(UPLOAD_RETRY_WAIT_S)
    return None


def main():
    token_path = next((p for p in TOKEN_PATHS if os.path.exists(p)), None)
    if not token_path:
        sys.exit(f"No token file at {' or '.join(TOKEN_PATHS)} — "
                 "run garmin_token_helper.py once to mint tokens.")

    import garth
    garth.client.loads(open(token_path).read())
    o2 = garth.client.oauth2_token
    exp = getattr(o2, "expires_at", 0) or 0
    left_h = (exp - time.time()) / 3600.0
    _log(f"stored OAuth2 has {left_h:.1f}h left (from {token_path})")

    if left_h <= REFRESH_THRESHOLD_H:
        # One OAuth2 exchange from THIS machine's IP — the door Garmin keeps
        # open. If this raises with an auth error (OAuth1 dead, ~1yr), re-mint
        # with garmin_token_helper.py.
        garth.client.refresh_oauth2()
        new_exp = getattr(garth.client.oauth2_token, "expires_at", 0) or 0
        if new_exp <= time.time() + 3600:
            sys.exit("refresh_oauth2 did not yield a fresh token — aborting")
        _log(f"refreshed OAuth2, now valid until "
             f"{time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(new_exp))}")
        for p in TOKEN_PATHS:
            fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(garth.client.dumps())
            os.chmod(p, 0o600)

    # Upload whenever prod hasn't confirmed THIS dump — covers both a fresh
    # refresh and a previous run whose upload failed.
    dump = garth.client.dumps()
    already = os.path.exists(UPLOADED_MARKER) and open(UPLOADED_MARKER).read() == dump
    if already:
        _log("prod already has this token — nothing to upload")
        return
    body = _upload(dump)
    if body is None:
        sys.exit("upload failed after retries — will retry on the next scheduled run")
    fd = os.open(UPLOADED_MARKER, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(dump)
    _log(f"uploaded to prod — connected, synced days: {body.get('days_filled')}")


if __name__ == "__main__":
    main()
