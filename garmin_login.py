import subprocess, sys, os

venv_path = os.path.join(os.path.dirname(__file__), "venv")
python = os.path.join(venv_path, "bin", "python3")

if not os.path.exists(python):
    print("Creating venv...")
    subprocess.check_call([sys.executable, "-m", "venv", venv_path])
    subprocess.check_call([python, "-m", "pip", "install", "garminconnect", "-q"])

os.execv(python, [python, "-c", """
from garminconnect import Garmin
email = "erikbjohn@gmail.com"
pw = input("Password: ")
api = Garmin(email, pw, prompt_mfa=lambda: input("MFA Code: "))
api.login()
tokens = api.garth.dumps()
with open("/tmp/gt.txt", "w") as f:
    f.write(tokens)
print("DONE - tokens saved")
"""])
