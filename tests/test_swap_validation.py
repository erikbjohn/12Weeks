"""Tests for exercise swap validation.

The bug that motivated this: Lying Leg Curl was appearing as a swap target on a
Hammer Curl card. Three vectors allowed the bad row to be written and survive:
coach-LLM markers with no validation, blind cross-week carry-forward across phase
boundaries, and a read endpoint that trusted whatever was in the table.
"""
import pytest

from equipment_swaps import is_valid_swap, find_swap_entry


# ─── Pure unit tests: no DB ─────────────────────────────────────────────────

class TestIsValidSwap:
    def test_rejects_cross_muscle_group(self):
        # The exact bug from the screenshot.
        assert is_valid_swap("Hammer Curl", "Lying Leg Curl") is False

    def test_accepts_listed_alternative(self):
        assert is_valid_swap("Hammer Curl", "Dumbbell Curl") is True
        assert is_valid_swap("Hammer Curl", "EZ-Bar Curl") is True
        assert is_valid_swap("Hammer Curl", "Band Curl") is True

    def test_accepts_identity(self):
        # Identity is the "revert" case; UI lets users click the original.
        assert is_valid_swap("Hammer Curl", "Hammer Curl") is True

    def test_rejects_reverse_direction(self):
        # Hamstring → bicep is just as wrong as bicep → hamstring.
        assert is_valid_swap("Lying Leg Curl", "Hammer Curl") is False

    def test_accepts_lying_leg_curl_alternatives(self):
        assert is_valid_swap("Lying Leg Curl", "Nordic Hamstring Curl") is True
        assert is_valid_swap("Lying Leg Curl", "Romanian Deadlift") is True

    def test_fail_open_for_unknown_original(self):
        # Novel/typo'd original — we don't know the alternatives, so we can't
        # block. Better than rejecting legitimate UX for any unrecognised name.
        assert is_valid_swap("Made Up Exercise", "Anything") is True

    def test_constrains_when_original_is_alternative_only(self):
        # auto_swap_workout can substitute the original with an alternative-name
        # exercise like "Glute Bridge (weighted)" that isn't a top-level catalog
        # key. Earlier behaviour fail-opened any swap from such a name. Now we
        # locate the parent entry (Barbell Hip Thrust) and constrain valid swaps
        # to that entry's family — same muscle group, no cross-group leakage.
        # The exact bug from the screenshot: Bent-Over Row appearing as a swap
        # for a Hip Thrust slot.
        assert is_valid_swap("Glute Bridge (weighted)", "Barbell Bent-Over Row") is False
        # Same family is still allowed.
        assert is_valid_swap("Glute Bridge (weighted)", "Barbell Hip Thrust") is True
        assert is_valid_swap("Glute Bridge (weighted)", "Single Leg Glute Bridge") is True

    def test_rejects_empty_inputs(self):
        assert is_valid_swap("", "Hammer Curl") is False
        assert is_valid_swap("Hammer Curl", "") is False
        assert is_valid_swap(None, "Hammer Curl") is False
        assert is_valid_swap("Hammer Curl", None) is False

    def test_canonicalises_via_resolve_name(self):
        # resolve_name maps "Kettlebell Swing" → "KB Swing" (catalog key),
        # so the user-facing name still validates.
        assert is_valid_swap("KB Swing", "Dumbbell Swing") is True


class TestCatalogConsistency:
    """The catalog itself was a source of bugs: duplicate entries for the same
    canonical exercise let alternatives drift apart (DB OHP had 'Arnold Press';
    DB Overhead Press didn't). These tests pin the invariants we cleaned up."""

    def test_no_duplicate_canonical_keys(self):
        from equipment_swaps import EXERCISE_SWAPS
        from workout_data import resolve_name
        groups = {}
        for k in EXERCISE_SWAPS:
            groups.setdefault(resolve_name(k), []).append(k)
        dupes = {canon: keys for canon, keys in groups.items() if len(keys) > 1}
        assert not dupes, (
            f"Catalog has multiple keys resolving to the same canonical name: {dupes}. "
            "Each canonical exercise should have exactly one entry — drifting "
            "alternatives between aliases caused the original bug."
        )

    def test_every_listed_alternative_validates(self):
        # Self-referential check: every alt the catalog declares for an exercise
        # must pass is_valid_swap for that exercise. Catches any alt added with
        # a non-canonical name that resolve_name later normalises differently.
        from equipment_swaps import EXERCISE_SWAPS
        for orig, entry in EXERCISE_SWAPS.items():
            for alt in entry["alternatives"]:
                assert is_valid_swap(orig, alt["name"]), (
                    f"Catalog inconsistency: {orig!r} lists {alt['name']!r} as "
                    "an alternative but is_valid_swap rejects it."
                )


class TestFindSwapEntry:
    def test_direct_hit(self):
        key, entry = find_swap_entry("Hammer Curl")
        assert key == "Hammer Curl"
        assert entry["muscle_group"] == "biceps"

    def test_unknown_returns_none(self):
        key, entry = find_swap_entry("Truly Made Up Exercise XYZ")
        assert key is None
        assert entry is None

    def test_handles_empty(self):
        assert find_swap_entry("") == (None, None)
        assert find_swap_entry(None) == (None, None)


# ─── Integration tests: real DB, real Flask app ─────────────────────────────

@pytest.fixture(scope="module")
def app_ctx():
    """Spin up the app once with a clean DB. Tests share the app context but each
    creates its own user so isolation is by user_id, not by reset."""
    from app import app, db
    with app.app_context():
        db.create_all()
        # Run column migrations (the same logic app.py runs on boot).
        from sqlalchemy import inspect as sa_inspect, text
        inspector = sa_inspect(db.engine)
        if "exercise_swap" in inspector.get_table_names():
            existing = {c["name"] for c in inspector.get_columns("exercise_swap")}
            if "original_name" not in existing:
                db.session.execute(text(
                    'ALTER TABLE exercise_swap ADD COLUMN original_name VARCHAR(120)'
                ))
                db.session.commit()
        yield app, db


_USER_SEQ = [0]


@pytest.fixture
def user_factory(app_ctx):
    """Build a fresh user with full gym equipment for each test."""
    app, db = app_ctx
    from models import User, UserEquipment, PhysicalAssessment

    def make():
        _USER_SEQ[0] += 1
        u = User(email=f"swap-test-{_USER_SEQ[0]}@example.com", password_hash="x")
        db.session.add(u)
        db.session.commit()
        eq = UserEquipment(user_id=u.id, available_equipment=[
            "barbell", "dumbbells", "ez_bar", "kettlebells", "weight_plates",
            "lat_pulldown", "cable_machine", "leg_press", "leg_curl_ext",
            "chest_press_machine", "seated_row_machine", "smith_machine",
            "ab_machine", "pull_up_bar", "dip_station", "flat_bench",
            "incline_bench", "decline_bench", "resistance_bands", "trx",
            "medicine_ball", "foam_roller", "ab_wheel",
        ])
        pa = PhysicalAssessment(user_id=u.id, has_gym=True)
        db.session.add(eq)
        db.session.add(pa)
        db.session.commit()
        return u
    return make


class TestExerciseAtSlot:
    def test_finds_hammer_curl_in_phase1_wed(self, app_ctx, user_factory):
        # Phase 1 (week 1-3), Wednesday (day_idx=2), idx 2 = Hammer Curl
        # per spec §2 (Shoulder Volume + Arms day).
        app, _db = app_ctx
        from app import _exercise_at_slot
        u = user_factory()
        with app.test_request_context():
            assert _exercise_at_slot(u.id, 1, 2, 2) == "Hammer Curl"

    def test_finds_lying_leg_curl_in_phase1_fri(self, app_ctx, user_factory):
        # Phase 1, Friday (day_idx=4), idx 2 = Lying Leg Curl per spec §2
        # (Heavy Lower — Squat Focus).
        app, _db = app_ctx
        from app import _exercise_at_slot
        u = user_factory()
        with app.test_request_context():
            assert _exercise_at_slot(u.id, 1, 4, 2) == "Lying Leg Curl"

    def test_returns_none_for_out_of_range(self, app_ctx, user_factory):
        app, _db = app_ctx
        from app import _exercise_at_slot
        u = user_factory()
        with app.test_request_context():
            assert _exercise_at_slot(u.id, 1, 0, 99) is None


class TestParseCoachMarkers:
    def test_rejects_cross_muscle_group_swap(self, app_ctx, user_factory):
        # The bug: coach LLM emits a SWAP marker turning Hammer Curl into Lying
        # Leg Curl. Validation must drop the row, not persist it.
        app, db = app_ctx
        from app import _parse_coach_markers
        from models import ExerciseSwap
        u = user_factory()
        marker = (
            "Sure, swapping for you. "
            "[SWAP: day_idx=2, exercise_idx=6, old=Hammer Curl, "
            "new=Lying Leg Curl, reason=user request]"
        )
        with app.test_request_context():
            _parse_coach_markers(marker, u.id, week=1)
            rows = ExerciseSwap.query.filter_by(user_id=u.id).all()
        assert rows == []

    def test_accepts_valid_swap_and_records_original(self, app_ctx, user_factory):
        app, db = app_ctx
        from app import _parse_coach_markers
        from models import ExerciseSwap
        u = user_factory()
        # Phase 1 Wed (day_idx=2), idx=2 is Hammer Curl per spec §2.
        marker = (
            "[SWAP: day_idx=2, exercise_idx=2, old=Hammer Curl, "
            "new=Dumbbell Curl, reason=variation]"
        )
        with app.test_request_context():
            _parse_coach_markers(marker, u.id, week=1)
            row = ExerciseSwap.query.filter_by(user_id=u.id).first()
        assert row is not None
        assert row.swapped_to == "Dumbbell Curl"
        # The fix: we now record what the slot held when the swap was created,
        # so cross-phase carry-forward can detect when the slot has shifted.
        assert row.original_name == "Hammer Curl"


class TestApiExerciseSwapsReadFilter:
    def test_purges_stale_cross_muscle_swap(self, app_ctx, user_factory):
        # Seed a bad row (the exact bug shape) and confirm the GET endpoint
        # both omits it from the response and deletes it from the table.
        # Phase 1 Wed (day_idx=2), idx=2 is Hammer Curl per spec §2.
        app, db = app_ctx
        from models import ExerciseSwap
        u = user_factory()
        with app.app_context():
            db.session.add(ExerciseSwap(
                user_id=u.id, week=1, day_idx=2, exercise_idx=2,
                swapped_to="Lying Leg Curl",  # not in Hammer Curl alternatives
                original_name=None,  # legacy row, no snapshot
            ))
            db.session.commit()

            client = app.test_client()
            with client.session_transaction() as sess:
                sess["_user_id"] = str(u.id)
                sess["_fresh"] = True
            resp = client.get("/api/exercise-swaps")
            assert resp.status_code == 200
            data = resp.get_json()
            assert "1_2_2" not in data, f"stale swap leaked into response: {data}"

            remaining = ExerciseSwap.query.filter_by(user_id=u.id).all()
            assert remaining == [], "stale row should have been auto-deleted"

    def test_keeps_valid_swap(self, app_ctx, user_factory):
        app, db = app_ctx
        from models import ExerciseSwap
        u = user_factory()
        with app.app_context():
            db.session.add(ExerciseSwap(
                user_id=u.id, week=1, day_idx=2, exercise_idx=2,
                swapped_to="Dumbbell Curl",
                original_name="Hammer Curl",
            ))
            db.session.commit()

            client = app.test_client()
            with client.session_transaction() as sess:
                sess["_user_id"] = str(u.id)
                sess["_fresh"] = True
            resp = client.get("/api/exercise-swaps")
            assert resp.status_code == 200
            assert resp.get_json().get("1_2_2") == "Dumbbell Curl"


class TestCarryForwardAcrossPhase:
    def test_drops_swap_when_slot_changes_across_phase(self, app_ctx, user_factory):
        # Simulate: in week 4 (deload), day_idx=4, idx=3 is Hammer Curl per
        # workout_data.py:1168. Carry forward into week 5 (Phase 2 start) where
        # the same slot is something else entirely. The carry-forward must
        # refuse to copy the swap.
        app, db = app_ctx
        from app import _exercise_at_slot
        from models import ExerciseSwap
        from equipment_swaps import is_valid_swap

        u = user_factory()
        with app.test_request_context():
            prev_original = _exercise_at_slot(u.id, 4, 4, 3)
            new_original = _exercise_at_slot(u.id, 5, 4, 3)

        # Pre-conditions: this only tests something real if the slot actually
        # changes between weeks. If the program ever stabilises the slot, this
        # test will start passing trivially — fail loud rather than silently.
        if prev_original is None or new_original is None:
            pytest.skip("slot lookup unavailable for this week range")
        if prev_original == new_original:
            pytest.skip("week 4→5 keeps slot stable; nothing to test here")

        # Pick a swap target that's valid for prev but not for new.
        swap_target = None
        from equipment_swaps import EXERCISE_SWAPS
        prev_alts = EXERCISE_SWAPS.get(prev_original, {}).get("alternatives", [])
        for alt in prev_alts:
            if not is_valid_swap(new_original, alt["name"]):
                swap_target = alt["name"]
                break
        if swap_target is None:
            pytest.skip(
                f"no swap target distinguishes {prev_original} from {new_original}"
            )

        with app.app_context():
            db.session.add(ExerciseSwap(
                user_id=u.id, week=4, day_idx=4, exercise_idx=3,
                swapped_to=swap_target, original_name=prev_original,
            ))
            db.session.commit()

            # Replicate the carry-forward block in api_generate_week_plan.
            from app import _exercise_at_slot
            slot_cache = {}
            prev_swaps = ExerciseSwap.query.filter_by(user_id=u.id, week=4).all()
            for ps in prev_swaps:
                existing = ExerciseSwap.query.filter_by(
                    user_id=u.id, week=5,
                    day_idx=ps.day_idx, exercise_idx=ps.exercise_idx,
                ).first()
                if existing:
                    continue
                prev_orig = ps.original_name or _exercise_at_slot(
                    u.id, 4, ps.day_idx, ps.exercise_idx, _cache=slot_cache,
                )
                new_orig = _exercise_at_slot(
                    u.id, 5, ps.day_idx, ps.exercise_idx, _cache=slot_cache,
                )
                if not new_orig:
                    continue
                if prev_orig and prev_orig != new_orig:
                    continue
                if not is_valid_swap(new_orig, ps.swapped_to):
                    continue
                db.session.add(ExerciseSwap(
                    user_id=u.id, week=5,
                    day_idx=ps.day_idx, exercise_idx=ps.exercise_idx,
                    swapped_to=ps.swapped_to, original_name=new_orig,
                ))
            db.session.commit()

            week5_swaps = ExerciseSwap.query.filter_by(user_id=u.id, week=5).all()
        assert week5_swaps == [], (
            f"carry-forward leaked '{swap_target}' from {prev_original} (wk4) "
            f"into {new_original} (wk5)"
        )


class TestApiWorkoutsSwapOverlay:
    """When a swap is active, /api/workouts must return the swap target's
    own metadata (target_weight via engine on its own SetLog history,
    note from the catalog alternative entry) — NOT the slot's original
    prescription leaking through.

    The bug that motivated these tests: prescription stored Conv DL 5x5 at
    175 lb. User swapped to Dumbbell Romanian Deadlift. They had logged
    DB RDL at 45 lb. Display showed '5x5 · Last: 45 lb -> 175 lb' — the
    175 lb was the original Conv DL prescription leaking through to a
    physically impossible DB RDL load.
    """

    def test_swap_overlay_replaces_name_and_clears_original_target(
        self, app_ctx, user_factory
    ):
        from datetime import date, timedelta
        app, db = app_ctx
        from models import WeeklyPrescription, ExerciseSwap, SetLog
        u = user_factory()
        with app.app_context():
            # Original slot: Conventional Deadlift 5x5 at 175 lb (heavy)
            db.session.add(WeeklyPrescription(
                user_id=u.id, week=5, day_idx=3, exercise_order=0,
                exercise_name="Conventional Deadlift",
                sets=5, reps="5", rest="2-3 min",
                target_weight=175.0, note="RPE 8-9. Heavy and controlled.",
                source="engine",
            ))
            # User has DB RDL history at 45 lb (light, real)
            for i in range(5):
                db.session.add(SetLog(
                    user_id=u.id, exercise_name="Dumbbell Romanian Deadlift",
                    week=4, day_idx=3, set_number=i + 1,
                    weight=45.0, reps=8, done=True,
                    logged_date=date.today() - timedelta(days=3),
                ))
            # User's explicit swap: Conv DL -> DB RDL on this slot
            db.session.add(ExerciseSwap(
                user_id=u.id, week=5, day_idx=3, exercise_idx=0,
                swapped_to="Dumbbell Romanian Deadlift",
                original_name="Conventional Deadlift",
            ))
            db.session.commit()

            client = app.test_client()
            with client.session_transaction() as sess:
                sess["_user_id"] = str(u.id)
                sess["_fresh"] = True
            resp = client.get("/api/workouts")
            assert resp.status_code == 200
            data = resp.get_json()

            week5 = data.get("5")
            assert week5, "week 5 missing in response"
            day = week5["days"][3]
            ex = day["exercises"][0]

            # Name reflects the swap target
            assert ex["name"] == "Dumbbell Romanian Deadlift"
            # swapped_from set so client can render the badge
            assert ex.get("swapped_from") == "Conventional Deadlift"
            # target_weight must NOT be the original 175 lb. Engine should
            # project from DB RDL history (45 lb) — should be ~50 lb after
            # a small bump, definitely well below 175.
            tw = ex.get("target_weight")
            assert tw is None or tw < 100, (
                f"swap target_weight should reflect DB RDL history (~50), "
                f"not Conv DL prescription (175); got {tw}"
            )
            # Note must NOT be the original Conv DL note
            assert "Heavy and controlled" not in (ex.get("note") or ""), (
                f"note leaked from original Conv DL: {ex.get('note')!r}"
            )

    def test_swap_overlay_pulls_note_from_catalog_alternative(
        self, app_ctx, user_factory
    ):
        # The original's catalog alternative entry has its own note.
        # The swap overlay should surface that note for the swap target.
        app, db = app_ctx
        from models import WeeklyPrescription, ExerciseSwap
        from equipment_swaps import EXERCISE_SWAPS
        u = user_factory()
        # Pick a known original/alt pair from the catalog
        orig = "Conventional Deadlift"
        alt_entry = next(
            (a for a in EXERCISE_SWAPS[orig]["alternatives"]
             if a["name"] == "Dumbbell Romanian Deadlift"), None,
        )
        assert alt_entry, "test fixture assumes Conv DL has DB RDL alternative"
        expected_note = alt_entry["note"]
        with app.app_context():
            db.session.add(WeeklyPrescription(
                user_id=u.id, week=5, day_idx=3, exercise_order=0,
                exercise_name=orig, sets=5, reps="5", rest="2-3 min",
                target_weight=175.0, note="RPE 8-9. Heavy.",
                source="engine",
            ))
            db.session.add(ExerciseSwap(
                user_id=u.id, week=5, day_idx=3, exercise_idx=0,
                swapped_to="Dumbbell Romanian Deadlift",
                original_name=orig,
            ))
            db.session.commit()

            client = app.test_client()
            with client.session_transaction() as sess:
                sess["_user_id"] = str(u.id)
                sess["_fresh"] = True
            resp = client.get("/api/workouts")
            ex = resp.get_json()["5"]["days"][3]["exercises"][0]
        assert ex.get("note") == expected_note, (
            f"swap should surface alternative's catalog note "
            f"({expected_note!r}); got {ex.get('note')!r}"
        )
