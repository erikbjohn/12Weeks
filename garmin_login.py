import subprocess, sys, os

venv_path = os.path.join(os.path.dirname(__file__), "venv")
python = os.path.join(venv_path, "bin", "python3")

if not os.path.exists(python):
    print("Creating venv...")
    subprocess.check_call([sys.executable, "-m", "venv", venv_path])
    subprocess.check_call([python, "-m", "pip", "install", "garminconnect", "-q"])

os.execv(python, [python, "-c", """
import os
from garminconnect import Garmin
email = "erikbjohn@gmail.com"
pw = input("Password: ")
api = Garmin(email, pw, prompt_mfa=lambda: input("MFA Code: "))
api.login()
tokens = api.garth.dumps()
# Owner-only perms: bearer tokens must never be world-readable in /tmp.
fd = os.open("/tmp/gt.txt", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f:
    f.write(tokens)
os.chmod("/tmp/gt.txt", 0o600)
print("DONE - tokens saved (owner-only permissions)")
"""])
