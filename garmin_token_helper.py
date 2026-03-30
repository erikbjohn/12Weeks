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
import sys

APP_URL = "https://one2weeks-9ewf.onrender.com"


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

        # Save locally as backup
        with open("/tmp/garmin_tokens.txt", "w") as f:
            f.write(tokens)
        print("Tokens saved to /tmp/garmin_tokens.txt")

        # Upload to app
        print(f"\nUploading tokens to {APP_URL}...")
        print("You need to be logged into the app first.")
        print()
        print("Option 1: Copy this curl command and run it while logged in:")
        print(f'  curl -X POST {APP_URL}/api/garmin/save-tokens \\')
        print(f'    -H "Content-Type: application/json" \\')
        print(f'    -b your_session_cookie \\')
        print(f'    -d \'{{"tokens": "<paste from /tmp/garmin_tokens.txt>"}}\' ')
        print()
        print("Option 2: Open the app in your browser, open console (F12), and run:")
        print(f"""  fetch('/api/garmin/save-tokens', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{tokens: `{tokens[:50]}...`}})}}).then(r=>r.json()).then(d=>console.log(d))""")
        print()
        print("(The full token is saved in /tmp/garmin_tokens.txt)")

    except Exception as e:
        print(f"\nError: {e}")
        if "429" in str(e) or "rate" in str(e).lower():
            print("\nGarmin is rate limiting. Wait 15 minutes and try again.")
            print("This is a Garmin-side limit, not our app.")
        sys.exit(1)


if __name__ == "__main__":
    main()
