# Weight Accordion Data Map

## Data Sources

### 1. body_stats.py -- Population Percentile Data

**`_STRENGTH_PERCENTILES`** -- 1RM/bodyweight ratio tables by sex, exercise, and percentile tier:

- Male exercises: Barbell Bench Press, Barbell Back Squat, Conventional Deadlift, Barbell Bent-Over Row, DB Overhead Press, Barbell OHP, Lat Pulldown, Barbell Hip Thrust, EZ-Bar Curl, Cable Tricep Pushdown
- Female exercises: Barbell Bench Press, Barbell Back Squat, Conventional Deadlift, Barbell Bent-Over Row, DB Overhead Press
- Each has percentile breakpoints at: 10, 25, 50, 75, 90, 95
- Values are 1RM/bodyweight ratios (e.g., male bench 50th = 0.80)

**`compute_1rm_percentile(one_rm, body_weight, exercise, age, sex)`** -- returns:
```python
{"percentile": int, "relative_strength": float, "rating": str}
```
- Ratings: Beginner (<25), Novice (25-49), Intermediate (50-74), Advanced (75-89), Elite (90+)
- Age-adjusted via `_AGE_FACTORS` (peak at 18-35, declines to 0.70 at 65+)
- Fuzzy matches exercise names if no exact match found

**`estimate_1rm(weight, reps)`** -- Epley formula: `weight * (1 + reps/30)`

### 2. static/app.js -- Client-Side Weight Cache

**`_weightsCache`** -- populated from `GET /api/weights` on app init (line 3610). Structure:
```js
{
  "Barbell Bench Press": {
    current: 135,           // latest working weight
    history: [
      {
        weight: 135,        // working weight used
        reps: "4x10",       // sets_label (prescription string, NOT actual reps)
        rpe: "just_right",  // "too_easy" | "just_right" | "too_hard"
        rpe_score: 7,       // 1-10 RPE (added by recordWeight, not in GET response)
        reps_completed: 10, // actual reps done (added by recordWeight, not in GET response)
        date: "2026-03-28",
        week: 3,
        day: 1,
        // Baseline entries also have:
        testWeight: 95,
        testReps: 13,
        estimated1RM: 136,
      }
    ]
  }
}
```

**`getExerciseData(exName)`** -- returns `_weightsCache[exName] || null`

**IMPORTANT GAP**: `GET /api/weights` does NOT return `reps_completed` or `rpe_score` in history entries. The client adds these locally via `recordWeight()` but they are lost on reload. The new `/api/weight-detail` endpoint fixes this by returning `reps_completed` as `reps`.

### 3. static/app.js -- 1RM Estimation (Client)

**`estimate1RM(weight, reps)`** (line 1014):
```js
function estimate1RM(weight, reps) {
  if (reps <= 0) return 0;
  if (reps === 1) return weight;
  return Math.round(weight * (1 + reps / 30));  // Epley formula
}
```
Identical to server-side `body_stats.estimate_1rm()`.

**`workingWeightFrom1RM(oneRM)`**: `Math.round(oneRM * 0.75 / 5) * 5` (75% of 1RM, rounded to nearest 5)

### 4. GET /api/weights (app.py line 1063)

Returns all exercises for the current user. Per exercise:
```json
{
  "Exercise Name": {
    "current": 135,
    "history": [
      {
        "weight": 135,
        "reps": "4x10",         // sets_label string
        "rpe": "just_right",
        "date": "2026-03-28",
        "week": 3,
        "day": 1,
        "testWeight": 95,       // only on baseline entries
        "testReps": 13,         // only on baseline entries
        "estimated1RM": 136     // only on baseline entries
      }
    ]
  }
}
```

Does NOT include: `reps_completed`, `rpe_score`, `difficulty_notes`.

### 5. ExerciseLog Model (models.py line 97)

All fields on the DB model:
- `exercise_name` (String 100, indexed)
- `weight` (Float) -- working weight
- `sets_label` (String 50) -- e.g. "4x10" or "baseline: 95lb x 13"
- `rpe` (String 20) -- "too_easy", "just_right", "too_hard"
- `rpe_score` (Integer, nullable) -- 1-10 RPE
- `reps_completed` (Integer, nullable) -- actual reps done
- `difficulty_notes` (Text, nullable)
- `week` (Integer)
- `day_idx` (Integer)
- `logged_date` (Date)
- `test_weight` (Float, nullable) -- baseline test weight
- `test_reps` (Integer, nullable) -- baseline test reps
- `estimated_1rm` (Float, nullable) -- stored baseline 1RM
- `user_id` (Integer, FK)

### 6. Age/Sex Resolution

No age or sex columns on User model. Derived from PsychIntake conversation:
- Scan user messages for "male"/"female"/"m"/"f" -> sex
- Scan user messages for integer 15-80 -> age
- Defaults: sex="male", age=30

---

## New Endpoint: GET /api/weight-detail/<exercise_name>

**Location**: app.py line 1280, between `/api/weights/baseline` and completions routes.

**Response**:
```json
{
  "exercise": "Barbell Bench Press",
  "timeline": [
    {
      "date": "2026-03-15",
      "weight": 135,
      "reps": 10,             // reps_completed (actual)
      "rpe": "just_right",
      "week": 1,
      "sets_label": "4x10",
      "est_1rm": 136,         // only if log.estimated_1rm exists
      "baseline_weight": 95,  // only if log.test_weight exists
      "baseline_reps": 13     // only if log.test_weight exists
    }
  ],
  "current_1rm": 180,         // Epley from last log entry
  "baseline_1rm": 136,        // Epley from first baseline entry
  "percentile": 62,           // population percentile (age-adjusted)
  "rating": "Intermediate",   // Beginner/Novice/Intermediate/Advanced/Elite
  "total_sessions": 8
}
```

**Key behaviors**:
- Timeline ordered by `logged_date ASC`
- `current_1rm` computed from last entry's weight and `reps_completed` (defaults to 10 if null)
- `baseline_1rm` computed from first entry that has `test_weight`
- Percentile uses `compute_1rm_percentile(one_rm, body_weight, exercise, age, sex)` with age/sex from PsychIntake
- Bodyweight sourced from latest BodyWeight log, falling back to PhysicalAssessment, then 180
- Wrapped in try/except so percentile failures don't break the response
