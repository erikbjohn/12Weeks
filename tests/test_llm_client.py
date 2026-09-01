"""S071: one model table, one fence parser."""
import pathlib, re
from llm_client import parse_json_reply, strip_fence, OPUS, SONNET


def test_fence_parser_handles_every_shape():
    assert parse_json_reply('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_reply('```\n[1, 2]\n```') == [1, 2]
    assert parse_json_reply('Here you go:\n{"a": {"b": 2}}\nThanks.') == {"a": {"b": 2}}
    assert strip_fence('```json{"x":1}```') == '{"x":1}'


def test_no_stale_model_ids_in_source():
    stale = re.compile(r"claude-(opus|sonnet)-4-2025\d{4}|claude-opus-4-7\b")
    hits = []
    for f in pathlib.Path(".").glob("*.py"):
        if f.name == "llm_client.py":
            continue
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if stale.search(line) and not line.strip().startswith("#"):
                hits.append(f"{f}:{i}")
    assert not hits, hits
    assert OPUS.startswith("claude-opus") and SONNET.startswith("claude-sonnet")
