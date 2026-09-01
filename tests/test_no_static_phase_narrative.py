"""S042/S031: the block-1 template narrative must never reach the coach or
the hero card as ground truth."""
import pathlib
import re


def test_coach_assembler_has_no_phase_template_injection():
    src = pathlib.Path("coach_assembler.py").read_text()
    assert "Do not invent phase details beyond this" not in src
    assert "rest day (streak mile only)" not in src


def test_hero_card_does_not_hardcode_the_sunday_run():
    src = pathlib.Path("static/app.js").read_text()
    assert "Streak mile only &middot; Recovery" not in src
    # the rest-day hero renders the served run pill instead
    m = re.search(r"if \(d\.isRest\) \{.*?return;\s*\}", src, re.S)
    assert m and "runPillHtml(d)" in m.group(0)
