/**
 * Regression test for the bodyweight-exercise weight-prefill bug.
 *
 * Bug: getSuggestedWeight()'s keyword-fallback returns ~25% of bench
 * for any exercise name containing 'raise', 'curl', 'fly', 'extension'.
 * For Erik (bench 140), Hanging Leg Raise prefilled with 35 — even
 * though the prescription says target_weight=0 (bodyweight).
 *
 * The override at app.js:10295 used `if (ex.target_weight)` which is
 * falsy for 0, so the bogus 35 stuck.
 *
 * Fixed at commit 8b6df42 by switching to `if (ex.target_weight != null)`
 * and mapping target_weight=0 to an empty input.
 *
 * This test pins both behaviors:
 *   1. The estimator returns 35 for Hanging Leg Raise + bench=140 (the
 *      mechanism is still there — it's the override's job to suppress it).
 *   2. (Future: a test for the override resolution itself, once we
 *      extract that logic into a pure function.)
 */
import { describe, it, expect, beforeAll } from 'vitest';
import { loadAppJs } from './load.mjs';

describe('getSuggestedWeight — keyword-fallback estimator', () => {
  beforeAll(() => {
    loadAppJs();
    // Seed via the __testHooks setter — `_weightsCache` is let-scoped
    // inside app.js so a direct window assignment doesn't reach the
    // function's closure.
    window.__testHooks.setWeightsCache({
      'Barbell Bench Press': { current: 140, history: [] },
      'Barbell Back Squat': { current: 158, history: [] },
    });
  });

  it("returns ~35 lb for Hanging Leg Raise when bench=140 (estimator works)", () => {
    const out = window.getSuggestedWeight('Hanging Leg Raise', 7);
    expect(out.weight).toBe(35); // 140 * 0.25 = 35
    expect(out.reason).toBe('estimated');
  });

  it("returns null weight for unknown bodyweight exercises (no keyword match)", () => {
    const out = window.getSuggestedWeight('Plank', 7);
    expect(out.weight).toBeNull();
  });

  it("Pallof Press would also estimate from bench (press → 50%)", () => {
    // Documents the same class of bug — the estimator doesn't know
    // which exercises are bodyweight. Override semantics in the render
    // layer are what protect us.
    const out = window.getSuggestedWeight('Pallof Press', 7);
    expect(out.weight).toBe(70); // 140 * 0.5 = 70
  });
});
