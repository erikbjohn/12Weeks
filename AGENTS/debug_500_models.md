# Debug 500 — Model/Import Audit

Date: 2026-03-30

## CHECK 1: Model Classes vs. app.py Imports

### Models defined in models.py (class name : line number)

| # | Class | Line |
|---|-------|------|
| 1 | User | 10 |
| 2 | Invite | 31 |
| 3 | CoachMemory | 43 |
| 4 | ComplianceScore | 56 |
| 5 | MuscleGroupProfile | 69 |
| 6 | SessionAnalysis | 81 |
| 7 | ExerciseLog | 97 |
| 8 | SetLog | 117 |
| 9 | ExerciseSwap | 132 |
| 10 | ExerciseCompletion | 143 |
| 11 | WarmupCompletion | 155 |
| 12 | RunLog | 165 |
| 13 | DayCompletion | 179 |
| 14 | MealLog | 190 |
| 15 | AppState | 202 |
| 16 | BodyWeight | 213 |
| 17 | BodyMeasurement | 223 |
| 18 | ProgressPhoto | 233 |
| 19 | WeeklyCheckIn | 246 |
| 20 | SupplementLog | 260 |
| 21 | MorningCheckIn | 271 |
| 22 | PsychIntake | 287 |
| 23 | GarminTokens | 299 |
| 24 | PhysicalAssessment | 308 |
| 25 | UserEquipment | 337 |
| 26 | UserConstraints | 347 |
| 27 | TrainingGoal | 360 |
| 28 | UserFoodSelections | 382 |
| 29 | WeeklyReport | 392 |
| 30 | ChatMessage | 412 |
| 31 | DailyCoachState | 424 |

Total: 31 model classes in models.py.

### Imports in app.py (lines 36-45)

```python
from models import (
    db, User, Invite, ExerciseLog, ExerciseCompletion, ExerciseSwap, DayCompletion,
    MealLog, AppState, BodyWeight, BodyMeasurement,
    WeeklyCheckIn, SupplementLog, MorningCheckIn, ChatMessage,
    ProgressPhoto, PsychIntake, GarminTokens, PhysicalAssessment,
    UserConstraints, TrainingGoal, UserFoodSelections, WeeklyReport,
    UserEquipment, WarmupCompletion, RunLog, SetLog, CoachMemory,
    ComplianceScore, MuscleGroupProfile, SessionAnalysis,
    DailyCoachState,
)
```

### Cross-check result: ALL CLEAR

Every class imported in app.py exists in models.py. Every class in models.py is imported in app.py. No phantom imports. No missing classes. The `db` object is also correctly imported.

**VERDICT: NOT THE CRASH CAUSE.**

---

## CHECK 2: coach.py Import Analysis

### Top-level imports (lines 1-5):
```python
import os
import logging
from datetime import date, timedelta
```

These are all stdlib. No risk of ImportError.

### _format_today (line 234):
```python
def _format_today(ctx):
    try:
        from utils_time import user_local_now, format_user_local
        ...
    except Exception:
        return f"{date.today()...}"
```

The `utils_time` import is inside a try/except, so even if utils_time fails, it degrades gracefully.

**VERDICT: NOT THE CRASH CAUSE.**

---

## CHECK 3: utils_time.py Analysis

```python
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from pytz import timezone as _pytz_tz
    class ZoneInfo:
        def __new__(cls, key):
            return _pytz_tz(key)
```

Fallback logic: if `zoneinfo` (Python 3.9+) is missing, it falls back to `pytz`. If BOTH are missing, the module-level import would raise `ImportError` and any module importing `utils_time` at the top level would fail.

However, `zoneinfo` is available in Python 3.9+. The server is almost certainly running 3.9+. And the only consumer (`coach.py` line 238) wraps the import in try/except.

**VERDICT: NOT THE CRASH CAUSE** (unless running Python < 3.9 without pytz installed, which is unlikely).

---

## CHECK 4: compliance.py and training_engine.py

### compliance.py top-level imports:
```python
from datetime import date, datetime, timedelta, timezone
from models import db, MorningCheckIn, MealLog, DayCompletion, SetLog, ComplianceScore
import math
```

All models exist in models.py. `math` is stdlib. Safe.

### training_engine.py top-level imports:
```python
from datetime import date, datetime, timedelta, timezone
from models import db, SetLog, MuscleGroupProfile, SessionAnalysis, ExerciseCompletion, AppState
```

All models exist in models.py. Safe.

Both modules are also wrapped in try/except in app.py (lines 25-34), so even if they fail, the app provides stub fallbacks.

**VERDICT: NOT THE CRASH CAUSE.**

---

## OVERALL CONCLUSION

**No model/import mismatch found.** All 31 model classes in models.py are correctly imported in app.py. No phantom imports. All top-level imports across coach.py, compliance.py, training_engine.py, and utils_time.py resolve to existing modules and models.

The 500 error is NOT caused by:
- Missing model classes
- Import mismatches between models.py and app.py
- Failed top-level imports in coach.py
- utils_time.py ZoneInfo/pytz fallback
- compliance.py or training_engine.py import failures

### Next steps to investigate:
1. Check the actual server logs / traceback for the 500 error
2. Check database migration state (missing columns or tables)
3. Check for runtime errors in route handlers (not import-time)
4. Check environment variables (DATABASE_URL, API keys, etc.)
5. Check if a recent deploy introduced a syntax error in a template
