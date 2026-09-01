"""S130: every non-admin /api/ route must have a caller in the client, tests
or scripts — dead routes are attack surface and rot (one still read the
dead ExerciseLog table). Admin/debug routes are curl-only by design."""
import pathlib
import re


def test_every_user_facing_api_route_has_a_caller():
    from app import app
    files = ["static/app.js", "static/sw.js"] + [str(p) for p in pathlib.Path("templates").glob("*.html")] \
        + [str(p) for p in pathlib.Path("tests").rglob("*.py")] + [str(p) for p in pathlib.Path("scripts").glob("*.py")]
    hay = "\n".join(pathlib.Path(f).read_text() for f in files)
    src = pathlib.Path("app.py").read_text()
    unreferenced = []
    for r in app.url_map.iter_rules():
        p = r.rule
        if not p.startswith("/api/") or p.startswith(("/api/admin/", "/api/debug/", "/api/test/")):
            continue
        base = re.sub(r"/<[^>]+>.*$", "", p).rstrip("/")
        if base in hay or f"url_for('{r.endpoint}'" in src or f'url_for("{r.endpoint}"' in src:
            continue
        unreferenced.append(p)
    # Known curl-only user routes (documented in memory/scripts):
    allow = {"/api/garmin/save-tokens", "/api/chat/history"}
    unreferenced = [p for p in unreferenced if p not in allow]
    assert not unreferenced, "routes with no caller (delete them or add to allow):\n  " + "\n  ".join(sorted(unreferenced))
