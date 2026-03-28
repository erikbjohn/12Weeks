"""All 12 weeks of workout data."""

PHASES = {
    1: {
        "label": "Phase 1 - Wks 1-4",
        "focus": "Hypertrophy base + fat loss foundation",
        "lifting": "4x10-12, RPE 7-8",
        "deficit": "400-500 kcal below TDEE",
        "protein": "1g/lb bodyweight",
    },
    2: {
        "label": "Phase 2 - Wks 5-8",
        "focus": "Strength + body recomposition",
        "lifting": "5x5 main lifts, 3x12 accessories",
        "deficit": "400-500 kcal below TDEE",
        "protein": "1g/lb bodyweight",
    },
    3: {
        "label": "Phase 3 - Wks 9-12",
        "focus": "Peak leanness + power retention",
        "lifting": "3-4x3-5 heavy, 3x15 pump",
        "deficit": "300-400 kcal (tighten up)",
        "protein": "1g/lb bodyweight",
    },
}

RUNS = {
    "z2_40": {"type": "z2", "label": "Zone 2", "time": "40 min", "detail": "HR 130-145. Conversational pace. Easy - you can hold a sentence."},
    "z2_35": {"type": "z2", "label": "Zone 2", "time": "35 min", "detail": "HR 130-145. Conversational pace. Aerobic base work."},
    "z2_45": {"type": "z2", "label": "Zone 2", "time": "45 min", "detail": "HR 130-145. Steady aerobic. Fat oxidation zone."},
    "z2_50": {"type": "z2", "label": "Zone 2", "time": "50 min", "detail": "HR 130-145. Longest Zone 2 of the week. Keep it honest."},
    "z2_55": {"type": "z2", "label": "Zone 2", "time": "55 min", "detail": "HR 130-145. Aerobic volume building."},
    "z2_30": {"type": "z2", "label": "Zone 2", "time": "30 min", "detail": "HR 130-145. Easy aerobic. Deload / taper run."},
    "z2_20": {"type": "z2", "label": "Zone 2", "time": "20 min", "detail": "HR 130-145. Short easy aerobic. Deload week."},
    "tempo25": {"type": "tempo", "label": "Tempo", "time": "25 min", "detail": "HR 155-165. Comfortably hard. 5 min easy warmup, 15 min at tempo, 5 min cooldown."},
    "tempo30": {"type": "tempo", "label": "Tempo", "time": "30 min", "detail": "HR 155-165. 5 min easy, 20 min sustained tempo, 5 min cooldown."},
    "tempo35": {"type": "tempo", "label": "Tempo", "time": "35 min", "detail": "HR 155-165. 5 min easy, 25 min tempo, 5 min cooldown. Hardest tempo of the plan."},
    "hiit20": {"type": "hiit", "label": "HIIT", "time": "20 min", "detail": "10x 30 sec all-out / 90 sec walk. Or 5 min warmup, 8x 30:90, 3 min cooldown."},
    "hiit25": {"type": "hiit", "label": "HIIT", "time": "25 min", "detail": "10x 30 sec all-out / 90 sec walk. 5 min warmup, 10x 30:90, 2 min cooldown."},
    "hiit30": {"type": "hiit", "label": "HIIT", "time": "30 min", "detail": "12x 30 sec all-out / 90 sec walk. 5 min warmup, 12x 30:90, 3 min cooldown."},
    "long60": {"type": "long", "label": "Long", "time": "60 min", "detail": "HR under 140. Easy conversational. Your aerobic base is your asset - don't push it."},
    "long75": {"type": "long", "label": "Long", "time": "75 min", "detail": "HR under 140. Build the run slightly - still aerobic, not a race."},
    "long90": {"type": "long", "label": "Long", "time": "90 min", "detail": "HR under 140. Peak long run. Take fuel if you go over 75 min."},
    "easy20": {"type": "easy", "label": "Easy", "time": "20 min", "detail": "HR under 130. Deload week. Shuffle if you need to - just move."},
    "easy30": {"type": "easy", "label": "Easy", "time": "30 min", "detail": "HR under 130. Easy and honest. Deload week."},
    "min": {"type": "min", "label": "Min mile", "time": "1+ mile", "detail": "Easy, sub-HR 130. Streak day. This is the only obligation."},
}

# Exercise definitions
EX = {
    # UPPER A
    "bench": {"name": "Barbell Bench Press", "sets": "4x10", "note": "Control the eccentric, 2 sec down"},
    "incline_db": {"name": "Incline DB Press", "sets": "4x10", "note": "45 deg incline, full ROM"},
    "cable_row": {"name": "Cable Seated Row", "sets": "4x10", "note": "Elbows tight, squeeze at end"},
    "pullup": {"name": "Pull-Ups", "sets": "4x8", "note": "Full hang to chin over bar, add weight if easy"},
    "ohp": {"name": "DB Overhead Press", "sets": "3x12", "note": "Standing or seated, controlled"},
    "face_pull": {"name": "Face Pull", "sets": "3x15", "note": "External rotation, pull to forehead"},
    "lat_raise": {"name": "Lateral Raise", "sets": "3x15", "note": "Slow and controlled, no swinging"},
    "curl_bar": {"name": "EZ-Bar Curl", "sets": "3x12", "note": "Full ROM, squeeze at top"},
    "tri_ext": {"name": "Cable Tricep Pushdown", "sets": "3x12", "note": "Elbows locked, full extension"},
    # LOWER A
    "squat": {"name": "Barbell Back Squat", "sets": "4x10", "note": "Below parallel, controlled descent"},
    "rdl": {"name": "Romanian Deadlift", "sets": "4x10", "note": "Hip hinge, feel the hamstring stretch"},
    "leg_press": {"name": "Leg Press", "sets": "3x12", "note": "Feet shoulder-width, full depth"},
    "lunge": {"name": "Walking Lunge", "sets": "3x12", "note": "Each leg, maintain upright torso"},
    "leg_curl": {"name": "Lying Leg Curl", "sets": "3x12", "note": "Controlled, don't let hips rise"},
    "calf_stand": {"name": "Standing Calf Raise", "sets": "4x15", "note": "Full stretch at bottom, squeeze at top"},
    # PUSH/PULL
    "dips": {"name": "Weighted Dips", "sets": "4x10", "note": "Forward lean for chest, upright for tri"},
    "inc_fly": {"name": "Incline Cable Fly", "sets": "3x12", "note": "Slight bend in elbow, full stretch"},
    "pull_down": {"name": "Wide-Grip Lat Pulldown", "sets": "4x10", "note": "Pull to upper chest, lean back slightly"},
    "db_row": {"name": "Single-Arm DB Row", "sets": "4x10", "note": "Each side, row to hip not chest"},
    "shrug": {"name": "DB Shrug", "sets": "3x15", "note": "Full elevation, 1 sec hold at top"},
    "hammer": {"name": "Hammer Curl", "sets": "3x12", "note": "Neutral grip, both arms alternate"},
    "skull": {"name": "Skull Crusher", "sets": "3x12", "note": "EZ bar, elbows in, controlled"},
    # FULL BODY
    "deadlift": {"name": "Conventional Deadlift", "sets": "3x8", "note": "Hip-width stance, bar over mid-foot"},
    "hip_thrust": {"name": "Barbell Hip Thrust", "sets": "4x10", "note": "Full extension, squeeze glutes at top"},
    "split_sq": {"name": "Bulgarian Split Squat", "sets": "3x10", "note": "Each leg. Rear foot elevated, upright torso."},
    "kb_swing": {"name": "KB Swing", "sets": "3x15", "note": "Hip drive - not a squat. Explosive."},
    "push_press": {"name": "Push Press", "sets": "3x8", "note": "Leg drive to initiate, lock out overhead"},
    "goblet": {"name": "Goblet Squat", "sets": "3x12", "note": "KB or DB at chest, upright torso"},
    "inv_row": {"name": "Inverted Row", "sets": "3x12", "note": "Body straight, pull chest to bar"},
    "plank": {"name": "Plank", "sets": "3x45s", "note": "Brace hard - don't sag"},
    # PHASE 2
    "deadlift5": {"name": "Conventional Deadlift", "sets": "5x5", "note": "RPE 8-9. Heavy and controlled. No bouncing."},
    "squat5": {"name": "Barbell Back Squat", "sets": "5x5", "note": "RPE 8-9. Heavy. Below parallel every rep."},
    "bench5": {"name": "Barbell Bench Press", "sets": "5x5", "note": "RPE 8-9. Spotter or use safeties."},
    "weighted_pu": {"name": "Weighted Pull-Up", "sets": "5x5", "note": "Add 20-40 lb. Full hang, chin over."},
    "bb_row": {"name": "Barbell Bent-Over Row", "sets": "5x5", "note": "45 deg torso, pull to belly button"},
    "cable_fly2": {"name": "Cable Chest Fly", "sets": "3x12", "note": "Arms wide, squeeze hard at center"},
    "pull_down2": {"name": "Lat Pulldown", "sets": "3x12", "note": "Full stretch at top"},
    "rear_delt": {"name": "Rear Delt Fly", "sets": "3x15", "note": "Bent over or cable, squeeze shoulder blades"},
    "tri_dip": {"name": "Tricep Dip", "sets": "3x12", "note": "Bodyweight or weighted"},
    "ohp5": {"name": "Barbell OHP", "sets": "5x5", "note": "Standing strict press. No leg drive."},
    "clean": {"name": "Power Clean", "sets": "4x5", "note": "From floor. Explosive pull, high elbows."},
    "box_jump": {"name": "Box Jump", "sets": "4x5", "note": "Max effort. Land soft. Reset each rep."},
    "deadlift_p2": {"name": "Deadlift", "sets": "3x5", "note": "RPE 9. Top set of the week."},
    "bench_p2": {"name": "Bench Press", "sets": "3x5", "note": "RPE 8. Push hard."},
    "row_p2": {"name": "Bent-Over Row", "sets": "3x8", "note": "Controlled, heavy-ish"},
    "lunge_p2": {"name": "DB Walking Lunge", "sets": "3x12", "note": "Each leg, weighted"},
    "push_ups": {"name": "Push-Ups", "sets": "2x20", "note": "Controlled, full ROM. Flush set."},
    "ab_wheel": {"name": "Ab Wheel Rollout", "sets": "3x10", "note": "From knees or toes. Don't sag."},
    # PHASE 3
    "squat3": {"name": "Back Squat", "sets": "4x3", "note": "RPE 9+. Max controllable speed on way up."},
    "deadlift3": {"name": "Deadlift", "sets": "4x3", "note": "RPE 9+. Lock out hard. Re-set each rep."},
    "bench3": {"name": "Bench Press", "sets": "4x3", "note": "RPE 9+. Explosive concentric."},
    "wpu3": {"name": "Weighted Pull-Up", "sets": "4x3", "note": "Heavy. Max weight you can do cleanly for 3."},
    "box_jump3": {"name": "Box Jump", "sets": "4x5", "note": "Max height. Land quiet. Full reset."},
    "med_ball": {"name": "Med Ball Slam", "sets": "3x10", "note": "Overhead to floor, explosive. 15-20 lb ball."},
    "power_clean3": {"name": "Power Clean", "sets": "4x3", "note": "Heaviest of the plan. Focus on speed off floor."},
    "pump_sq": {"name": "Goblet Squat (pump)", "sets": "3x15", "note": "Light, controlled, feel the burn"},
    "pump_press": {"name": "DB Bench (pump)", "sets": "3x15", "note": "Light, squeeze, slow eccentric"},
    "pump_row": {"name": "Cable Row (pump)", "sets": "3x15", "note": "Light, full ROM, pause at end"},
    "pump_curl": {"name": "DB Curl (pump)", "sets": "3x15", "note": "Controlled, squeeze at top"},
    "pump_tri": {"name": "Tricep Pushdown (pump)", "sets": "3x15", "note": "Full extension, controlled"},
    "hip_thrust3": {"name": "Barbell Hip Thrust", "sets": "3x5", "note": "Heavy. Power through glutes."},
    "split_sq3": {"name": "Bulgarian Split Squat", "sets": "3x8", "note": "Heavier than P2, explosive up"},
    "ohp3": {"name": "Barbell OHP", "sets": "4x3", "note": "RPE 9. Strict press, no leg drive."},
    "db_row3": {"name": "DB Row", "sets": "3x8", "note": "Heavy, explosive pull"},
    "leg_press3": {"name": "Leg Press (pump)", "sets": "3x15", "note": "Light-moderate, full ROM"},
    "calf3": {"name": "Calf Raise (pump)", "sets": "3x20", "note": "Full stretch, slow."},
    # TEST WEEK
    "test_sq": {"name": "Back Squat - 1RM test", "sets": "Work to 1RM", "note": "5->3->2->1 ladder. Rest fully between."},
    "test_dl": {"name": "Deadlift - 1RM test", "sets": "Work to 1RM", "note": "5->3->2->1 ladder."},
    "test_bench": {"name": "Bench Press - 1RM test", "sets": "Work to 1RM", "note": "Use safeties. Spotter ideal."},
    "test_pu": {"name": "Weighted Pull-Up - max", "sets": "Max weight x 1", "note": "Find your max single."},
}


def _ex(key):
    return dict(EX[key])


def get_phase(week):
    if week <= 4:
        return 1
    if week <= 8:
        return 2
    return 3


def get_workouts(week):
    """Return list of 7 day dicts for the given week number (1-12)."""
    is_deload = week in (4, 8)
    is_test = week == 12

    if is_test:
        return _test_week()
    if is_deload:
        return _deload_week(week)

    phase = get_phase(week)
    if phase == 1:
        return _phase1_week(week)
    if phase == 2:
        return _phase2_week(week)
    return _phase3_week(week)


def _run(key):
    return dict(RUNS[key])


def _phase1_week(week):
    return [
        {
            "day": "Mon", "liftName": "Upper A - Chest & Back",
            "exercises": [_ex("bench"), _ex("cable_row"), _ex("incline_db"), _ex("pullup"), _ex("face_pull"), _ex("lat_raise"), _ex("curl_bar"), _ex("tri_ext")],
            "run": _run("z2_40"),
            "timing": ["6:00", "Lift - Upper A (55 min)", "7:00", "5 min transition", "7:05", "Zone 2 run 40 min", "7:45", "Post-workout nutrition"],
            "notes": "Bench with safeties or use DB if solo. Pull-ups - add weight if you hit 10 reps easily.",
        },
        {
            "day": "Tue", "liftName": "Lower A - Squat Focus",
            "exercises": [_ex("squat"), _ex("rdl"), _ex("leg_press"), _ex("lunge"), _ex("leg_curl"), _ex("calf_stand")],
            "run": _run("long60"),
            "timing": ["6:00", "Lift - Lower A (55 min)", "7:00", "5 min transition", "7:05", "Long run 60 min", "8:05", "Post-workout nutrition"],
            "notes": "Long run right after legs will be uncomfortable - that's the adaptation. Keep HR honest.",
        },
        {
            "day": "Wed", "liftName": "Push & Pull - Chest, Shoulder, Back",
            "exercises": [_ex("dips"), _ex("inc_fly"), _ex("pull_down"), _ex("db_row"), _ex("ohp"), _ex("shrug"), _ex("hammer"), _ex("skull")],
            "run": _run("z2_35"),
            "timing": ["6:00", "Lift - Push/Pull (55 min)", "7:00", "5 min transition", "7:05", "Zone 2 run 35 min", "7:40", "Post-workout nutrition"],
            "notes": "Midweek volume day. Rest 60 sec between sets. Move with purpose.",
        },
        {
            "day": "Thu", "liftName": "Lower B - Hinge Focus",
            "exercises": [_ex("deadlift"), _ex("hip_thrust"), _ex("split_sq"), _ex("leg_curl"), _ex("calf_stand"), _ex("plank")],
            "run": _run("tempo25"),
            "timing": ["6:00", "Lift - Lower B (50 min)", "6:55", "5 min transition", "7:00", "Tempo run 25 min", "7:25", "Post-workout nutrition"],
            "notes": "Deadlift heavy. Tempo run after heavy hinge work is hard - warm into it.",
        },
        {
            "day": "Fri", "liftName": "Upper B - Shoulder & Arms",
            "exercises": [_ex("ohp"), _ex("lat_raise"), _ex("face_pull"), _ex("pullup"), _ex("cable_row"), _ex("curl_bar"), _ex("hammer"), _ex("tri_ext"), _ex("skull")],
            "run": _run("hiit20"),
            "timing": ["6:00", "Lift - Upper B (50 min)", "6:55", "5 min transition", "7:00", "HIIT run 20 min", "7:20", "Post-workout nutrition"],
            "notes": "Hardest metabolic day of the week. HIIT after lifting is serious CNS load. Eat well tonight. Sleep 8 hours.",
        },
        {
            "day": "Sat", "liftName": "Full Body - Compound Circuit",
            "exercises": [_ex("kb_swing"), _ex("goblet"), _ex("inv_row"), _ex("push_press"), _ex("plank"), _ex("deadlift")],
            "run": _run("z2_45"),
            "timing": ["6:00", "Lift - Full Body (50 min)", "6:55", "5 min transition", "7:00", "Zone 2 run 45 min", "7:45", "Post-workout nutrition"],
            "notes": "Saturday full body is compound-focused and slightly lower intensity. Enjoy the Zone 2.",
        },
        {
            "day": "Sun", "liftName": "Rest - Streak Day Only",
            "exercises": [], "run": _run("min"),
            "timing": ["Morning", "Min 1 mile at easy pace", "-", "No lifting"],
            "notes": "Complete rest from lifting. One easy mile to honor the streak. Sub-HR 130.",
            "isRest": True,
        },
    ]


def _phase2_week(week):
    return [
        {
            "day": "Mon", "liftName": "Lower Strength - Squat Focus",
            "exercises": [_ex("squat5"), _ex("hip_thrust"), _ex("split_sq"), _ex("leg_curl"), _ex("calf_stand"), _ex("ab_wheel")],
            "run": _run("tempo30"),
            "timing": ["6:00", "Lift - Lower Strength (60 min)", "7:05", "5 min transition", "7:10", "Tempo run 30 min", "7:40", "Post-workout nutrition"],
            "notes": "5x5 squat is the anchor. Rest 3 min between heavy sets. Don't rush it.",
        },
        {
            "day": "Tue", "liftName": "Upper Strength - Pull Focus",
            "exercises": [_ex("weighted_pu"), _ex("bb_row"), _ex("pull_down2"), _ex("rear_delt"), _ex("curl_bar"), _ex("hammer")],
            "run": _run("long75"),
            "timing": ["6:00", "Lift - Upper Pull (55 min)", "7:00", "5 min transition", "7:05", "Long run 75 min", "8:20", "Post-workout nutrition"],
            "notes": "Long run day - lift is pull-focused. HR under 140 on the run. Eat 100-150 extra kcal today.",
        },
        {
            "day": "Wed", "liftName": "Full Body - Power + Accessories",
            "exercises": [_ex("clean"), _ex("box_jump"), _ex("deadlift_p2"), _ex("bench_p2"), _ex("row_p2"), _ex("lunge_p2"), _ex("ab_wheel")],
            "run": _run("hiit25"),
            "timing": ["6:00", "Lift - Full Body Power (60 min)", "7:05", "5 min transition", "7:10", "HIIT run 25 min", "7:35", "Post-workout nutrition"],
            "notes": "Power clean first when CNS is fresh. HIIT after this is peak metabolic demand.",
        },
        {
            "day": "Thu", "liftName": "Lower Strength - Hinge Focus",
            "exercises": [_ex("deadlift5"), _ex("split_sq"), _ex("leg_press"), _ex("leg_curl"), _ex("calf_stand"), _ex("plank")],
            "run": _run("z2_40"),
            "timing": ["6:00", "Lift - Lower Hinge (60 min)", "7:05", "5 min transition", "7:10", "Zone 2 run 40 min", "7:50", "Post-workout nutrition"],
            "notes": "5x5 deadlift is the centerpiece. Zone 2 after heavy pulls - keep it genuinely easy.",
        },
        {
            "day": "Fri", "liftName": "Upper Strength - Press Focus",
            "exercises": [_ex("bench5"), _ex("ohp5"), _ex("cable_fly2"), _ex("tri_dip"), _ex("face_pull"), _ex("lat_raise"), _ex("tri_ext")],
            "run": _run("tempo30"),
            "timing": ["6:00", "Lift - Upper Press (55 min)", "7:00", "5 min transition", "7:05", "Tempo run 30 min", "7:35", "Post-workout nutrition"],
            "notes": "Double tempo week - Monday and Friday. Accelerates VO2max and fat oxidation.",
        },
        {
            "day": "Sat", "liftName": "Full Body - Volume + Core",
            "exercises": [_ex("squat"), _ex("bench"), _ex("bb_row"), _ex("push_press"), _ex("ab_wheel"), _ex("plank"), _ex("calf_stand")],
            "run": _run("z2_50"),
            "timing": ["6:00", "Lift - Full Body Volume (55 min)", "7:00", "5 min transition", "7:05", "Zone 2 run 50 min", "7:55", "Post-workout nutrition"],
            "notes": "Highest aerobic volume day. Lift is compound and moderate.",
        },
        {
            "day": "Sun", "liftName": "Rest - Streak Day Only",
            "exercises": [], "run": _run("min"),
            "timing": ["Morning", "Min 1 mile at easy pace", "-", "No lifting"],
            "notes": "Complete rest from lifting. One easy mile. Nothing else.",
            "isRest": True,
        },
    ]


def _phase3_week(week):
    return [
        {
            "day": "Mon", "liftName": "Lower Power - Squat + Jumps",
            "exercises": [_ex("box_jump3"), _ex("squat3"), _ex("hip_thrust3"), _ex("split_sq3"), _ex("pump_sq"), _ex("calf3"), _ex("ab_wheel")],
            "run": _run("hiit30"),
            "timing": ["6:00", "Lift - Lower Power (60 min)", "7:05", "5 min transition", "7:10", "HIIT run 30 min", "7:40", "Post-workout nutrition"],
            "notes": "Box jumps first - always. CNS must be fresh for power work. 4x3 squat is the heaviest of the plan.",
        },
        {
            "day": "Tue", "liftName": "Upper Power - Pull + Push",
            "exercises": [_ex("power_clean3"), _ex("wpu3"), _ex("bench3"), _ex("ohp3"), _ex("pump_row"), _ex("pump_curl"), _ex("pump_tri")],
            "run": _run("long90"),
            "timing": ["6:00", "Lift - Upper Power (60 min)", "7:05", "5 min transition", "7:10", "Long run 90 min", "8:40", "Post-workout nutrition"],
            "notes": "90 min long run. HR under 140. Bring fuel if needed. Add 150 kcal today.",
        },
        {
            "day": "Wed", "liftName": "Full Body Power - All Patterns",
            "exercises": [_ex("med_ball"), _ex("deadlift3"), _ex("bench3"), _ex("wpu3"), _ex("lunge_p2"), _ex("pump_press"), _ex("pump_row"), _ex("plank")],
            "run": _run("tempo35"),
            "timing": ["6:00", "Lift - Full Body Power (60 min)", "7:05", "5 min transition", "7:10", "Tempo run 35 min", "7:45", "Post-workout nutrition"],
            "notes": "Med ball slams first to prime explosiveness. Longest tempo of the plan after this.",
        },
        {
            "day": "Thu", "liftName": "Lower Power - Accessory + Pump",
            "exercises": [_ex("hip_thrust3"), _ex("split_sq3"), _ex("leg_press3"), _ex("leg_curl"), _ex("pump_sq"), _ex("calf3"), _ex("ab_wheel")],
            "run": _run("z2_45"),
            "timing": ["6:00", "Lift - Lower Accessories (55 min)", "7:00", "5 min transition", "7:05", "Zone 2 run 45 min", "7:50", "Post-workout nutrition"],
            "notes": "Lower intensity day - intentional after Mon/Tue/Wed. Zone 2 is your friend.",
        },
        {
            "day": "Fri", "liftName": "Upper Power - Peak Press + Pump",
            "exercises": [_ex("med_ball"), _ex("bench3"), _ex("ohp3"), _ex("wpu3"), _ex("pump_press"), _ex("pump_row"), _ex("pump_curl"), _ex("pump_tri")],
            "run": _run("hiit30"),
            "timing": ["6:00", "Lift - Upper Power + Pump (60 min)", "7:05", "5 min transition", "7:10", "HIIT run 30 min", "7:40", "Post-workout nutrition"],
            "notes": "Second HIIT of the week. You're in peak shape now. Hardest weeks are 10-11.",
        },
        {
            "day": "Sat", "liftName": "Full Body - Volume + Aerobic",
            "exercises": [_ex("squat3"), _ex("bench"), _ex("bb_row"), _ex("pump_sq"), _ex("pump_press"), _ex("pump_row"), _ex("plank"), _ex("calf3")],
            "run": _run("z2_55"),
            "timing": ["6:00", "Lift - Full Body (55 min)", "7:00", "5 min transition", "7:05", "Zone 2 run 55 min", "8:00", "Post-workout nutrition"],
            "notes": "Highest aerobic day. 55 min Zone 2 is the peak.",
        },
        {
            "day": "Sun", "liftName": "Rest - Streak Day Only",
            "exercises": [], "run": _run("min"),
            "timing": ["Morning", "Min 1 mile at easy pace", "-", "No lifting"],
            "notes": "Rest. One mile. That's it.",
            "isRest": True,
        },
    ]


def _deload_week(week):
    return [
        {
            "day": "Mon", "liftName": "Deload - Upper (60% load)",
            "exercises": [
                {"name": "DB Bench Press", "sets": "3x8", "note": "60% normal weight"},
                {"name": "Cable Row", "sets": "3x8", "note": "Light - focus on squeeze"},
                {"name": "DB OHP", "sets": "3x8", "note": "60% load"},
                {"name": "Pull-Up", "sets": "3x6", "note": "Bodyweight only"},
                {"name": "Face Pull", "sets": "2x15", "note": "Shoulder health - feel it"},
            ],
            "run": _run("easy20"),
            "timing": ["6:00", "Deload lift - Upper (40 min)", "6:45", "Easy run 20 min", "7:05", "Done"],
            "notes": "Deload week. Everything at 60% of your working weight. This is where you consolidate adaptation.",
        },
        {
            "day": "Tue", "liftName": "Deload - Lower (60% load)",
            "exercises": [
                {"name": "Goblet Squat", "sets": "3x8", "note": "Light KB or DB"},
                {"name": "RDL", "sets": "3x8", "note": "60% load, feel the hamstrings"},
                {"name": "Leg Press", "sets": "3x10", "note": "Light, full ROM"},
                {"name": "Lying Leg Curl", "sets": "2x10", "note": "Controlled"},
                {"name": "Calf Raise", "sets": "3x12", "note": "Slow and controlled"},
            ],
            "run": _run("easy20"),
            "timing": ["6:00", "Deload lift - Lower (40 min)", "6:45", "Easy run 20 min", "7:05", "Done"],
            "notes": "Easy day. Flush the legs. Do not be tempted to go heavy.",
        },
        {
            "day": "Wed", "liftName": "Deload - Full Body (60% load)",
            "exercises": [
                {"name": "Deadlift", "sets": "2x5", "note": "60% 1RM. Focus on setup."},
                {"name": "Bench Press", "sets": "2x8", "note": "Light - move well"},
                {"name": "Bent-Over Row", "sets": "2x8", "note": "Light, controlled"},
                {"name": "Plank", "sets": "2x30s", "note": "Brace and breathe"},
            ],
            "run": _run("easy20"),
            "timing": ["6:00", "Deload lift - Full Body (35 min)", "6:40", "Easy run 20 min", "7:00", "Done"],
            "notes": "Short and easy. The goal this week is active recovery, not training.",
        },
        {
            "day": "Thu", "liftName": "Rest - Streak Day Only",
            "exercises": [], "run": _run("min"),
            "timing": ["Morning", "Min 1 mile - easy", "-", "No lifting"],
            "notes": "Full rest from lifting. One mile to keep the streak alive.",
            "isRest": True,
        },
        {
            "day": "Fri", "liftName": "Deload - Upper Light",
            "exercises": [
                {"name": "Push-Up", "sets": "2x15", "note": "Bodyweight. Just move."},
                {"name": "Inverted Row", "sets": "2x12", "note": "Bodyweight, controlled"},
                {"name": "DB Lateral Raise", "sets": "2x15", "note": "Light"},
                {"name": "Hammer Curl", "sets": "2x12", "note": "Light"},
            ],
            "run": _run("easy20"),
            "timing": ["6:00", "Deload lift - Upper light (30 min)", "6:35", "Easy run 20 min", "6:55", "Done"],
            "notes": "Very light. Barely a workout. Perfect for a deload day.",
        },
        {
            "day": "Sat", "liftName": "Rest - Streak Day Only",
            "exercises": [], "run": _run("min"),
            "timing": ["Morning", "Min 1 mile - easy", "-", "No lifting"],
            "notes": "Rest. Streak mile only. Eat at maintenance today.",
            "isRest": True,
        },
        {
            "day": "Sun", "liftName": "Rest - Streak Day Only",
            "exercises": [], "run": _run("min"),
            "timing": ["Morning", "Min 1 mile - easy", "-", "No lifting"],
            "notes": "Rest. Come back Monday ready to work.",
            "isRest": True,
        },
    ]


def _test_week():
    return [
        {
            "day": "Mon", "liftName": "Strength Test - Lower",
            "exercises": [_ex("test_sq"), _ex("test_dl"), _ex("pump_sq"), _ex("calf3")],
            "run": _run("z2_20"),
            "timing": ["6:00", "Squat 1RM ladder (30 min)", "6:35", "Deadlift 1RM ladder (25 min)", "7:05", "Pump accessories (15 min)", "7:20", "Easy run 20 min", "7:40", "Done"],
            "notes": "Test week. Warm up thoroughly: 5x5, 3x3, 2x2, 1x1 approach to max. Rest 3-5 min between heavy singles.",
        },
        {
            "day": "Tue", "liftName": "Strength Test - Upper",
            "exercises": [_ex("test_bench"), _ex("test_pu"), _ex("pump_press"), _ex("pump_curl")],
            "run": _run("z2_20"),
            "timing": ["6:00", "Bench 1RM ladder (30 min)", "6:35", "Weighted pull-up 1RM (20 min)", "7:00", "Pump work (15 min)", "7:15", "Easy run 20 min", "7:35", "Done"],
            "notes": "Compare your bench and pull-up max to week 1. This is your 12-week progress marker.",
        },
        {
            "day": "Wed", "liftName": "Full Body - Moderate Finish",
            "exercises": [
                {"name": "Goblet Squat", "sets": "3x12", "note": "Moderate weight"},
                {"name": "DB Bench", "sets": "3x12", "note": "Moderate"},
                {"name": "DB Row", "sets": "3x12", "note": "Controlled"},
                {"name": "Plank", "sets": "3x45s", "note": "Solid brace"},
            ],
            "run": _run("z2_30"),
            "timing": ["6:00", "Full body moderate (45 min)", "6:50", "Zone 2 run 30 min", "7:20", "Done"],
            "notes": "Last real training session. No PRs today - just move well and feel good.",
        },
        {
            "day": "Thu", "liftName": "Rest - Streak Day Only",
            "exercises": [], "run": _run("min"),
            "timing": ["Morning", "Min 1 mile", "-", "Rest"],
            "notes": "Rest.",
            "isRest": True,
        },
        {
            "day": "Fri", "liftName": "Full Body - Final Session",
            "exercises": [
                {"name": "Squat", "sets": "3x5", "note": "Moderate - not max"},
                {"name": "Bench", "sets": "3x5", "note": "Moderate"},
                {"name": "Pull-Up", "sets": "3x5", "note": "Bodyweight or light weight"},
                {"name": "KB Swing", "sets": "3x15", "note": "Explosive - feel the power"},
            ],
            "run": _run("z2_30"),
            "timing": ["6:00", "Final session (40 min)", "6:45", "Zone 2 run 30 min", "7:15", "Done"],
            "notes": "Final workout of the 12 weeks. Finish clean. Note how this feels vs Week 1.",
        },
        {
            "day": "Sat", "liftName": "Rest - Streak Day Only",
            "exercises": [], "run": _run("min"),
            "timing": ["Morning", "Min 1 mile", "-", "Rest"],
            "notes": "Rest.",
            "isRest": True,
        },
        {
            "day": "Sun", "liftName": "Rest - Streak Day Only",
            "exercises": [], "run": _run("min"),
            "timing": ["Morning", "Min 1 mile", "-", "Done - 12 weeks complete."],
            "notes": "You did it.",
            "isRest": True,
        },
    ]
