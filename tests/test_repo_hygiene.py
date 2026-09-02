"""S091: no tracked file may carry a live Anthropic key or a cookie jar."""
import re
import subprocess


def test_no_tracked_secret_material():
    files = subprocess.run(["git", "ls-files"], capture_output=True, text=True).stdout.split("\n")
    assert "cookies.txt" not in files
    key = re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")
    hits = []
    for f in files:
        if not f or f.endswith((".png", ".jpg", ".dump", ".ico", ".woff", ".woff2")):
            continue
        try:
            txt = open(f, encoding="utf-8", errors="ignore").read()
        except (IsADirectoryError, FileNotFoundError):
            continue
        for m in key.finditer(txt):
            hits.append((f, m.group(0)[:12] + "…"))
    assert not hits, hits
