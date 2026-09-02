#!/usr/bin/env python3
"""Lightweight DATA audit (2026-09-01): read the nightly export JSON and flag
values that cannot be real. A code audit finds mechanisms; this finds the
outputs — the check that would have caught 13 days of soreness=5 and a
145 lb KB-swing target in minutes. No LLM, no prod load.

Usage:  venv/bin/python scripts/data_audit.py [~/12weeks-backups/YYYY-MM-DD.json] [--user-id N]
Exit 1 when any HIGH finding exists (so a cron/launchd log shows red).
"""
from __future__ import annotations
import json, os, sys, glob, statistics
from collections import defaultdict, Counter
from datetime import date, datetime, timedelta

CHECKIN_FIELDS = ("sleep_quality", "stress_level", "soreness", "mood", "motivation", "anxiety")


def _d(s):
    return date.fromisoformat(str(s)[:10]) if s else None


def audit(tables: dict, user_id: int | None = None, today: date | None = None) -> list[dict]:
    """Return findings: {sev: HIGH|MED|LOW, table, check, detail}. Pure."""
    today = today or date.today()
    F = []
    def hit(sev, table, check, detail): F.append({"sev": sev, "table": table, "check": check, "detail": detail})
    def rows(t):
        r = tables.get(t) or []
        return [x for x in r if user_id is None or x.get("user_id") == user_id]

    # ── morning_checkin: fabricated / constant self-report ──
    ci = sorted(rows("morning_checkin"), key=lambda r: str(r.get("log_date")))
    for f in CHECKIN_FIELDS:
        vals = [r.get(f) for r in ci if r.get(f) is not None]
        for r in ci:
            v = r.get(f)
            if v is not None and not (1 <= v <= 10):
                hit("HIGH", "morning_checkin", "score_out_of_range", f"{r.get('log_date')} {f}={v}")
        run = 0; prev = None; start = None
        for r in ci:
            v = r.get(f)
            if v is not None and v == prev:
                run += 1
                if run >= 5:
                    hit("HIGH", "morning_checkin", "constant_score",
                        f"{f}={v} for {run+1} consecutive rows ending {r.get('log_date')} (a placeholder, not a person)")
                    run = -99
            else:
                run = 0
            prev = v
    for r in ci:
        filled = [f for f in CHECKIN_FIELDS if r.get(f) is not None]
        notes = (r.get("notes") or "")
        if len(filled) == 6 and ("[Coach conversation" in notes or "AI-extracted" in notes or "Auto-completed" in notes):
            hit("HIGH", "morning_checkin", "all_six_scores_from_chat",
                f"{r.get('log_date')}: six numeric scores on a chat/auto row — self-report cannot be that complete")
        if "[MISSED]" in notes and filled:
            hit("HIGH", "morning_checkin", "missed_row_has_scores", f"{r.get('log_date')}: {filled}")

    # ── set_log: phantom targets, typos, impossible loads ──
    sl = rows("set_log")
    best = defaultdict(float)
    for s in sl:
        if s.get("done") and (s.get("weight") or 0) > 0:
            best[s["exercise_name"]] = max(best[s["exercise_name"]], s["weight"])
    for s in sl:
        w, t = s.get("weight") or 0, s.get("target_weight")
        if t is not None and w > 0 and t > w * 1.5:
            hit("HIGH", "set_log", "target_far_above_logged",
                f"{s.get('logged_date')} {s['exercise_name']} set {s.get('set_number')}: target {t} vs logged {w}")
        if t is not None and w == 0 and t >= 90 and (s.get("reps") or 0) > 0:
            hit("MED", "set_log", "target_on_bodyweight_set", f"{s.get('logged_date')} {s['exercise_name']}: target {t} on a 0-lb set")
        if w > 0 and w > 2.0 * max(best[s["exercise_name"]] * 0 + 1, statistics.median([x["weight"] for x in sl if x["exercise_name"] == s["exercise_name"] and (x.get("weight") or 0) > 0] or [w])) and w >= 45:
            hit("MED", "set_log", "weight_typo_suspect", f"{s.get('logged_date')} {s['exercise_name']}: {w} lb vs median for that lift")
        if (s.get("reps") or 0) > 50 and w > 0:
            hit("MED", "set_log", "reps_typo_suspect", f"{s.get('logged_date')} {s['exercise_name']}: {s['reps']} reps @ {w}")
        if w > 700:
            hit("HIGH", "set_log", "impossible_load", f"{s.get('logged_date')} {s['exercise_name']}: {w} lb")

    # ── weekly_prescription: targets vs the athlete's real numbers; rails ──
    wp = rows("weekly_prescription")
    state = (rows("app_state") or [{}])[0]
    start = _d(state.get("start_date"))
    cur_week = None
    if start:
        cur_week = max(1, min(12, (today - start).days // 7 + 1))
    for r in wp:
        if r.get("source") != "coach":
            continue
        ex, tw = r["exercise_name"], r.get("target_weight")
        if tw and best.get(ex) and tw > best[ex] * 1.5 and best[ex] >= 20:
            hit("HIGH", "weekly_prescription", "target_far_above_best",
                f"wk{r['week']} d{r['day_idx']} {ex}: prescribed {tw} vs best logged {best[ex]}")
        if (r.get("sets") or 0) < 3 and r.get("week") and cur_week and cur_week <= r["week"] <= 12:
            hit("MED", "weekly_prescription", "below_min_sets", f"wk{r['week']} d{r['day_idx']} {ex}: {r.get('sets')} sets")
    # a day with coach lifts but no schedule row / a planned week missing a run day
    wds = rows("weekly_day_schedule"); wrp = rows("weekly_run_plan")
    sched = {(r["week"], r["day_idx"]) for r in wds}
    runs_by_week = defaultdict(set)
    for r in wrp: runs_by_week[r["week"]].add(r["day_idx"])
    coach_weeks = {r["week"] for r in wp if r.get("source") == "coach" and cur_week and r["week"] <= 12}
    for (w, d) in {(r["week"], r["day_idx"]) for r in wp if r.get("source") == "coach"}:
        if (w, d) not in sched and cur_week and w <= 12:
            hit("MED", "weekly_day_schedule", "missing_schedule_row", f"wk{w} d{d} has coach lifts but no schedule row")
    for w in coach_weeks:
        missing = sorted(set(range(7)) - runs_by_week.get(w, set()))
        if missing and (cur_week is None or w <= cur_week):
            hit("MED", "weekly_run_plan", "runless_day_in_planned_week", f"wk{w}: no run row for days {missing} (Erik runs 7/7)")

    # ── run_log: blanks, zero-distance ghosts, Garmin rows overwritten ──
    rl = rows("run_log"); ga = rows("garmin_activity")
    g_by_date = defaultdict(list)
    for a in ga: g_by_date[str(a.get("activity_date"))[:10]].append(a)
    seen = Counter((r.get("log_date"), r.get("week"), r.get("day_idx")) for r in rl)
    for k, n in seen.items():
        if n > 1: hit("MED", "run_log", "duplicate_slot", f"{k} x{n}")
    for r in rl:
        d = str(r.get("log_date"))[:10]
        if (r.get("distance_miles") or 0) == 0 and (r.get("duration_min") or 0) == 0 and not r.get("notes"):
            hit("MED", "run_log", "ghost_zero_run", f"{d}: 0 mi / 0 min row")
        if (r.get("source") in (None, "manual")) and g_by_date.get(d):
            blanks = [k for k in ("distance_miles", "duration_min", "avg_hr") if r.get(k) in (None, 0)]
            if blanks:
                hit("HIGH", "run_log", "manual_row_blocking_garmin", f"{d}: manual row with blank {blanks} while a Garmin activity exists")
        if r.get("distance_miles") and r.get("duration_min"):
            pace = r["duration_min"] / r["distance_miles"]
            if pace < 4.5 or pace > 25:
                hit("MED", "run_log", "implausible_pace", f"{d}: {pace:.1f} min/mi")

    # ── body_weight: duplicates, spikes, gaps, stale ──
    bw = sorted(rows("body_weight"), key=lambda r: str(r.get("log_date")))
    by_date = Counter(str(r.get("log_date"))[:10] for r in bw)
    for d, n in by_date.items():
        if n > 1: hit("MED", "body_weight", "duplicate_date", f"{d} x{n}")
    for a, b in zip(bw, bw[1:]):
        da, db_ = _d(a["log_date"]), _d(b["log_date"])
        if da and db_ and a.get("weight_lbs") and b.get("weight_lbs"):
            jump = b["weight_lbs"] - a["weight_lbs"]
            if abs(jump) > 8 and (db_ - da).days <= 2 and not b.get("event"):
                hit("MED", "body_weight", "unexplained_jump", f"{da}->{db_}: {jump:+.1f} lb with no scale event")
            if (db_ - da).days > 3 and db_ >= today - timedelta(days=30):
                hit("LOW", "body_weight", "gap", f"{da}->{db_}: {(db_-da).days} days without a weigh-in")
        if (b.get("weight_lbs") or 0) < 100 or (b.get("weight_lbs") or 0) > 400:
            hit("HIGH", "body_weight", "impossible_weight", f"{b.get('log_date')}: {b.get('weight_lbs')}")

    # ── garmin_wellness: empty rows stamped as synced ──
    for r in rows("garmin_wellness"):
        metrics = [r.get(k) for k in ("sleep_score", "sleep_seconds", "resting_hr", "hrv_last_night", "body_battery", "stress_overall")]
        if all(m is None for m in metrics) and r.get("pulled_at"):
            hit("MED", "garmin_wellness", "empty_row_marked_synced", f"{r.get('date')}")
        if r.get("resting_hr") and not (30 <= r["resting_hr"] <= 110):
            hit("MED", "garmin_wellness", "implausible_rhr", f"{r.get('date')}: {r['resting_hr']}")

    # ── peptide_dose: future taken_at, duplicate slots ──
    pd = rows("peptide_dose")
    slots = Counter((r.get("date"), r.get("time"), r.get("compound")) for r in pd if r.get("event_type") in (None, "dose"))
    for k, n in slots.items():
        if n > 1: hit("MED", "peptide_dose", "duplicate_dose_slot", f"{k} x{n}")
    for r in pd:
        ta = r.get("taken_at")
        if ta and _d(ta) and _d(ta) > today + timedelta(days=1):
            hit("HIGH", "peptide_dose", "taken_in_future", f"{r.get('date')} {r.get('compound')} taken_at={ta}")

    # ── day_completion: done with nothing behind it ──
    sets_by_slot = defaultdict(int)
    for s in sl:
        if s.get("done"): sets_by_slot[(s.get("week"), s.get("day_idx"))] += 1
    for r in rows("day_completion"):
        if r.get("done") and r.get("source") == "auto" and sets_by_slot[(r.get("week"), r.get("day_idx"))] == 0:
            hit("MED", "day_completion", "auto_done_without_sets", f"wk{r.get('week')} d{r.get('day_idx')}")

    # ── weekly_day_schedule: template titles on coach weeks ──
    for r in wds:
        if r.get("source") == "coach" and (r.get("lift_name") or "") in ("Upper A", "Upper B", "Lower A", "Lower B"):
            hit("LOW", "weekly_day_schedule", "template_title_on_coach_week", f"wk{r['week']} d{r['day_idx']}: {r['lift_name']}")

    # ── chat_message: the coach citing a number the data cannot support (cheap version) ──
    for m in rows("chat_message"):
        if m.get("role") != "assistant": continue
        c = m.get("content") or ""
        if "your anxiety" in c.lower() and not any(r.get("anxiety") is not None for r in ci):
            hit("HIGH", "chat_message", "coach_cites_absent_self_report", f"{m.get('created_at')}: coach references anxiety with no anxiety self-report on file")
    return F


def main(argv):
    path = None; uid = None
    args = list(argv)
    if "--user-id" in args:
        i = args.index("--user-id"); uid = int(args[i + 1]); del args[i:i + 2]
    if args:
        path = os.path.expanduser(args[0])
    else:
        cands = sorted(glob.glob(os.path.expanduser("~/12weeks-backups/*.json")))
        if not cands:
            print("no backup JSON found"); return 2
        path = cands[-1]
    d = json.load(open(path))
    tables = d.get("tables", d)
    exported = d.get("exported_at")
    today = _d(exported) if exported else date.today()
    F = audit(tables, uid, today)
    order = {"HIGH": 0, "MED": 1, "LOW": 2}
    F.sort(key=lambda f: (order[f["sev"]], f["table"], f["check"]))
    print(f"DATA AUDIT {os.path.basename(path)} (exported {exported}) — {len(F)} findings")
    for f in F:
        print(f"  [{f['sev']}] {f['table']}.{f['check']}: {f['detail']}")
    high = sum(1 for f in F if f["sev"] == "HIGH")
    print(f"HIGH={high} MED={sum(1 for f in F if f['sev']=='MED')} LOW={sum(1 for f in F if f['sev']=='LOW')}")
    return 1 if high else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
