"""S053: falsy-zero lint. `target_weight=0` is the BODYWEIGHT sentinel; a
truthy check drops it (memory: feedback_falsy_zero_bugs). Every `if …
target_weight/target_reps/dose_mg` that lacks an explicit None/zero
comparison must be listed here with a justification, or fixed."""
import pathlib
import re

FILES = ["app.py", "coach_assembler.py", "coach_planning_program.py", "plan_overlay.py",
         "workout_status.py", "coach_tools.py", "protocol.py", "static/app.js"]
PATTERN = re.compile(r"\bif\b[^\n]*\b(target_weight|target_reps|dose_mg)\b")
SAFE = re.compile(r"is not None|is None|!= null|== null|=== 0|!== 0|> 0|<= 0|>= 0|< 0|== 0|!= 0|"
                  r"in data|\"target_weight\" in|'target_weight' in|_twv|target_weight_val|typeof|"
                  r"target_weight >=|target_weight <|target_weight >|dose_mg !=|dose_mg <=|dose_mg >")

# (file, exact stripped line) → why a truthy check is correct HERE
ALLOWLIST = {
    ("coach_planning_program.py", 'w = f"{r.target_weight:g} lb" if r.target_weight else "BW"'):
        "0 renders as 'BW' by design",
    ("app.py", "if goal and goal.target_weight and bw:"): "goal body-weight target, never 0",
    ("app.py", "elif existing_goal and existing_goal.target_weight:"): "goal body-weight target, never 0",
    ("app.py", "current_weight = bw.weight_lbs if bw else (goal.target_weight + 10)"): "not a conditional on the sentinel",
    ("static/app.js", "} else if (prev && prev.weight && ex.target_weight) {"): "progression-why prose; BW lifts take the BW branch",
    ("static/app.js", "} else if (ex.target_weight && (!prev || !prev.weight)) {"): "progression-why prose; BW lifts take the BW branch",
    ("static/app.js", "if (weightMatch) payload.target_weight = parseInt(weightMatch[1]);"): "assignment, not a check",
    ("static/app.js", "} else if (_ex.target_weight) {"): "coach-card why line; BW handled above",
    ("static/app.js", "} else if (_prev && _prev.weight && _ex.target_weight) {"): "coach-card why line; BW handled above",
    ("static/app.js", "// A compound \"varies\" if it has more than one distinct positive dose_mg"): "comment",
    ("static/app.js", "if (targets.target_weight) {"): "goal body-weight target, never 0",
}


def test_every_truthy_sentinel_check_is_justified():
    unexplained = []
    for f in FILES:
        for line in pathlib.Path(f).read_text().splitlines():
            if not PATTERN.search(line) or SAFE.search(line):
                continue
            key = (f, line.strip())
            if key not in ALLOWLIST:
                unexplained.append(key)
    assert not unexplained, "truthy check on a falsy-zero field — fix it or justify it in ALLOWLIST:\n" + \
        "\n".join(f"  {f}: {l}" for f, l in unexplained)
