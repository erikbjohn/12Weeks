#!/usr/bin/env python3
"""Upload already-saved Garmin tokens (/tmp/garmin_tokens.txt) to prod.

Retry half of garmin_token_helper.py — no Garmin login/MFA needed. The admin
key is read via getpass so it never lands in shell history or the terminal.
"""
import getpass
import json
import os
import sys
import urllib.request

APP_URL = os.environ.get("APP_URL", "https://one2weeks-9ewf.onrender.com")
TOKEN_PATH = "/tmp/garmin_tokens.txt"
APP_EMAIL = "erik@placemetry.com"

if not os.path.exists(TOKEN_PATH):
    sys.exit(f"No tokens at {TOKEN_PATH} — run garmin_token_helper.py first.")

tokens = open(TOKEN_PATH).read().strip()
print(f"Tokens loaded ({len(tokens)} bytes). Uploading as {APP_EMAIL}.")

admin_key = os.environ.get("ADMIN_API_KEY") or getpass.getpass("App admin key: ").strip()
if not admin_key:
    sys.exit("No key entered — aborting.")

req = urllib.request.Request(
    f"{APP_URL}/api/admin/garmin/save-tokens",
    data=json.dumps({"email": APP_EMAIL, "tokens": tokens}).encode(),
    headers={"Content-Type": "application/json", "X-Admin-Key": admin_key},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=60) as resp:
        print("Upload response:", resp.read().decode())
    print("Done — tokens are on prod.")
except Exception as e:
    body = getattr(e, "read", lambda: b"")()
    print(f"Upload failed: {e} {body.decode(errors='replace') if body else ''}")
    sys.exit(1)
