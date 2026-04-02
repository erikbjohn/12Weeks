# Workout Overhaul Test Report
**Date:** 2026-03-30
**File:** `/Users/erikbjohn/Documents/Github/12Weeks/static/app.js` (7478 lines)

---

## 1. Brace Balance
- Open braces `{`: **2249**
- Close braces `}`: **2249**
- **PASS**

## 2. Duplicate const Declarations
Checked: `startWorkoutSession`, `logFocusSet`, `startTimedSet`, `showExerciseTransition`, `advanceWorkoutSession`
- No duplicate `const` declarations found in any function.
- **PASS**

## 3. Warm-up Prepend Logic (`startWorkoutSession`, line 6945)
- Reads `dayData.warmup.steps` via `(dayData.warmup && dayData.warmup.steps) || []` -- **OK**
- Maps to exercise format with `_isWarmup: true`, `name`, `sets: '1x' + duration`, `rest: '0s'`, `note` -- **OK**
- Prepends to `_workoutExercises` via spread: `[...warmupAsExercises, ...dayData.exercises]` -- **OK**
- Calls `showExerciseTransition(0)` (not `enterExerciseFocus`) -- **OK**
- **PASS**

## 4. RPE Skip for Warm-ups

### `logFocusSet` (line 7154)
- Lines 7197-7206: After all sets done, checks `currentEx._isWarmup` (via `_workoutExercises[_workoutExIdx]`)
- If warm-up, calls `advanceWorkoutSession()` and returns without showing RPE -- **OK**
- **PASS**

### `startTimedSet` (line 7226)
- Lines 7271-7280: Same pattern -- checks `currentEx._isWarmup`, skips RPE -- **OK**
- **PASS**

## 5. Transition Screen (`showExerciseTransition`, line 7455)
- Shows exercise name via `escapeHtml(displayName)` -- **OK**
- Shows sets and rest info -- **OK**
- Shows note if present via `escapeHtml(ex.note)` -- **OK**
- Has video link (YouTube search) -- **OK**
- Has swap button only for non-warmup: `${!isWarmup ? '...' : ''}` -- **OK**
- Has "LET'S GO" button calling `enterExerciseFocus(exIdx)` -- **OK**
- **PASS**

## 6. `advanceWorkoutSession` (line 6969)
- Calls `showExerciseTransition(_workoutExIdx)` -- **OK** (not `enterExerciseFocus`)
- **PASS**

## 7. Backtick / Template Literal Issues
- Exercise names go through `escapeHtml()` -- safe.
- Swap button on line 7475 uses complex quote escaping: `displayName.replace(/'/g, "\\\\'")` for the onclick handler -- fragile but functional for single quotes. **Names with backslashes could still break.**
- "LET'S GO" apostrophe is in HTML text content, not an attribute -- safe.
- **PASS (with caveat about backslash edge case)**

---

## BUGS FOUND

### BUG 1 (Critical): `enterExerciseFocus` ignores `_workoutExercises` index offset

**Location:** Line 7038-7044

```js
async function enterExerciseFocus(exIdx) {
  ...
  if (!dayData || !dayData.exercises || !dayData.exercises[exIdx]) return;
  const ex = dayData.exercises[exIdx];
```

**Problem:** When the transition screen calls `enterExerciseFocus(exIdx)`, `exIdx` is the index into `_workoutExercises` (which has warm-ups prepended). But `enterExerciseFocus` reads from `dayData.exercises[exIdx]`, which does NOT have warm-ups. This causes:

1. **Warm-up exercises:** The guard `!dayData.exercises[exIdx]` will pass if `exIdx < dayData.exercises.length`, but it will load the WRONG exercise (a real exercise instead of the warm-up). If warm-ups exceed the exercises array length, the function silently returns and nothing happens.
2. **Real exercises after warm-ups:** Index is shifted by the number of warm-up steps. E.g., if there are 3 warm-ups, the first real exercise is at `_workoutExercises[3]` but `enterExerciseFocus(3)` tries `dayData.exercises[3]`, which is the 4th real exercise.

**Fix needed:** When `_workoutActive` is true, `enterExerciseFocus` must read from `_workoutExercises[exIdx]` instead of `dayData.exercises[exIdx]`.

### BUG 2 (Moderate): `submitFocusRPE` uses wrong index for `setsLabel`

**Location:** Line 7444

```js
const setsLabel = weekData ? weekData.days[currentDay].exercises[_focusExIdx].sets : '';
```

**Problem:** `_focusExIdx` is set from the `_workoutExercises` index, but this line reads `dayData.exercises[_focusExIdx]` which has no warm-ups. Same offset problem as Bug 1. Will crash with `Cannot read properties of undefined` if `_focusExIdx` exceeds `dayData.exercises.length`, or return wrong data if it doesn't.

**Fix needed:** Either translate `_focusExIdx` to the `dayData.exercises` index (subtract warm-up count), or read from `_workoutExercises[_focusExIdx]`.

---

## Summary

| Check | Status |
|-------|--------|
| Brace balance | PASS |
| Duplicate const | PASS |
| Warm-up prepend | PASS |
| RPE skip for warm-ups | PASS |
| Transition screen | PASS |
| advanceWorkoutSession flow | PASS |
| Template literal safety | PASS (minor caveat) |
| **enterExerciseFocus index bug** | **FAIL - Critical** |
| **submitFocusRPE index bug** | **FAIL - Moderate** |

**Verdict: 2 bugs must be fixed before ship.** Both stem from `enterExerciseFocus` and `submitFocusRPE` using `dayData.exercises[idx]` without accounting for warm-up prepend offset.
