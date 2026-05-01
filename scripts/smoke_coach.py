"""Smoke test the new coach pipeline against a real LLM.

Run from project root with ANTHROPIC_API_KEY set:
    ANTHROPIC_API_KEY=sk-ant-... ./venv/bin/python scripts/smoke_coach.py

Or if you have it in a .env file:
    set -a; source .env; set +a; ./venv/bin/python scripts/smoke_coach.py

Hits the new validated pipeline (compute_coach_rules → assemble_prompt → real
LLM → validate_response → render). Three test messages exercise the full
contract: a normal question, a refusal trigger, and a soft-skip.
"""
import os
import sys

# Make project root importable when running from scripts/ subdir
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


TEST_MESSAGES = [
    ("normal-directive", "what should I do right now"),
    ("explicit-refusal", "thinking about resting tomorrow"),
    ("soft-skip", "I don't think I can lift today, too sore"),
]


def main(email: str = "erik@placemetry.com"):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set in environment.")
        sys.exit(1)

    from app import app
    from models import User
    from coach_assembler import coach_respond
    from flask_login import login_user

    with app.app_context():
        from app import db
        user = User.query.filter_by(email=email).first()
        if user is None:
            print(f"NOTE: user {email!r} not in local DB. Creating ephemeral test user.")
            from models import UserEquipment, PhysicalAssessment, AppState
            from datetime import date, timedelta
            user = User(email=email, password_hash="x")
            db.session.add(user); db.session.commit()
            db.session.add(UserEquipment(user_id=user.id, available_equipment=[
                "barbell", "dumbbells", "lat_pulldown", "cable_machine",
                "leg_press", "leg_curl_ext", "flat_bench", "incline_bench",
                "decline_bench", "ez_bar", "kettlebells", "pull_up_bar",
                "dip_station", "ab_machine", "smith_machine",
            ]))
            db.session.add(PhysicalAssessment(user_id=user.id, has_gym=True))
            # Pretend Erik is in week 5 of his program (Phase 2)
            db.session.add(AppState(
                user_id=user.id,
                start_date=date.today() - timedelta(days=4 * 7),
                current_week=5,
            ))
            db.session.commit()

        print(f"# Smoke test — user={email} (id={user.id})")
        print("=" * 70)

        for label, msg in TEST_MESSAGES:
            print()
            print(f"## [{label}] user message: {msg!r}")
            print("-" * 70)
            with app.test_request_context():
                login_user(user, force=True)
                try:
                    reply = coach_respond(
                        user_id=user.id,
                        agent_name="conversation",
                        user_message=msg,
                    )
                except Exception as e:
                    print(f"ERROR: {type(e).__name__}: {e}")
                    continue
            print(reply)
            print("-" * 70)
            _diagnose(reply)
        print()
        print("=" * 70)
        print("# Done.")


def _diagnose(reply: str):
    """Quick post-hoc checks against the validator's contract."""
    issues = []
    if "?" in reply:
        issues.append("- contains a question mark (validator should have caught this)")
    BANNED = [
        "your call", "if you feel up to it", "great job", "would you like",
        "let's see how", "if that works",
    ]
    for phrase in BANNED:
        if phrase in reply.lower():
            issues.append(f"- contains banned phrase: {phrase!r}")
    if not issues:
        print("[diagnose] clean — no questions, no banned phrases")
    else:
        print("[diagnose] ISSUES:")
        for i in issues:
            print(f"  {i}")


if __name__ == "__main__":
    email = sys.argv[1] if len(sys.argv) > 1 else "erik@placemetry.com"
    main(email)
