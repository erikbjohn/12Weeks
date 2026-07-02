#!/usr/bin/env python3
"""
Garmin Token Helper — login locally, upload tokens to the app.
This bypasses the web login and avoids rate limits.

Usage:
    python garmin_token_helper.py

It will:
1. Ask for your Garmin credentials (local only, not sent to our servers)
2. Login to Garmin Connect
3. Handle MFA if needed
4. Save tokens locally
5. Upload tokens to the app via API
"""

import getpass
import json
import os
import sys

APP_URL = os.environ.get("APP_URL", "https://one2weeks-9ewf.onrender.com")


def main():
    print("=" * 50)
    print("Garmin Token Helper")
    print("=" * 50)
    print()
    print("This logs into Garmin Connect locally and uploads")
    print("your auth tokens to the app. Your password is NOT")
    print("sent to our servers — only the auth tokens.")
    print()

    email = input("Garmin email: ").strip()
    password = getpass.getpass("Garmin password: ")

    print("\nConnecting to Garmin...")

    try:
        from garminconnect import Garmin

        api = Garmin(email, password, is_cn=False, return_on_mfa=True)
        result = api.login()

        # Handle MFA
        if isinstance(result, tuple) and len(result) == 2 and result[0] == "needs_mfa":
            print("\nMFA required.")
            mfa_code = input("Enter your verification code: ").strip()
            api.resume_login(result[1], mfa_code)

        print("Login successful!")

        # Save tokens
        tokens = api.garth.dumps()
        print(f"Tokens obtained ({len(tokens)} bytes)")

        # Save locally as backup — owner-only perms (0600): these are bearer
        # tokens granting full Garmin account access; a world-readable /tmp
        # file hands them to any local user/process.
        token_path = "/tmp/garmin_tokens.txt"
        fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(tokens)
        os.chmod(token_path, 0o600)  # tighten even if the file pre-existed
        print(f"Tokens saved to {token_path} (owner-only permissions)")

        # Upload to app via the admin endpoint (one shot, no browser needed)
        admin_key = os.environ.get("ADMIN_API_KEY") or getpass.getpass(
            "App admin key (blank to skip auto-upload): ")
        if admin_key:
            app_email = input("App account email [erik@placemetry.com]: ").strip() \
                or "erik@placemetry.com"
            print(f"\nUploading tokens to {APP_URL}...")
            import urllib.request
            req = urllib.request.Request(
                f"{APP_URL}/api/admin/garmin/save-tokens",
                data=json.dumps({"email": app_email, "tokens": tokens}).encode(),
                headers={"Content-Type": "application/json", "X-Admin-Key": admin_key},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    print("Upload response:", resp.read().decode())
                print("\nDone — open the app's Garmin Sync panel; it should show Connected.")
            except Exception as e:
                body = getattr(e, "read", lambda: b"")()
                print(f"Upload failed: {e} {body.decode(errors='replace') if body else ''}")
                print("Tokens are still saved at /tmp/garmin_tokens.txt — re-run to retry.")
        else:
            print("\nSkipped auto-upload. Manual option: while logged into the app,")
            print(f'  curl -X POST {APP_URL}/api/garmin/save-tokens \\')
            print(f'    -H "Content-Type: application/json" \\')
            print(f'    -b your_session_cookie \\')
            print(f'    -d \'{{"tokens": "<paste from /tmp/garmin_tokens.txt>"}}\' ')

    except Exception as e:
        print(f"\nError: {e}")
        if "429" in str(e) or "rate" in str(e).lower():
            print("\nGarmin is rate limiting. Wait 15 minutes and try again.")
            print("This is a Garmin-side limit, not our app.")
        sys.exit(1)


if __name__ == "__main__":
    main()
