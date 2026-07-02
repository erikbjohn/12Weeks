/**
 * Weight-prefill contract tests.
 *
 * History: getSuggestedWeight() used to carry a static WEIGHT_ESTIMATES table
 * and keyword-ratio fallbacks (e.g. ~25% of bench for anything named 'raise'/
 * 'curl'/'fly'/'extension'), silently prefilled into the weight input for any
 * exercise with no history and no target_weight — checking the set then logged
 * that invented number into SetLog as performance data. That violated
 * coach-or-nothing (2026-07-01 audit, finding static/app.js:2088): with no
 * prescription and no history the input must stay EMPTY.
 *
 * Earlier bug (commit 8b6df42): the override used `if (ex.target_weight)`
 * which is falsy for 0 (the bodyweight sentinel), so a bogus estimate stuck.
 * resolveDisplayWeight now uses `!= null` and maps 0 to an empty input.
 */
import { describe, it, expect, beforeAll } from 'vitest';
import { loadAppJs } from './load.mjs';

describe('getSuggestedWeight — no static estimates without history', () => {
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

  it("returns null for Hanging Leg Raise with no history (no keyword guess)", () => {
    const out = window.getSuggestedWeight('Hanging Leg Raise', 7);
    expect(out.weight).toBeNull();
  });

  it("returns null weight for unknown bodyweight exercises", () => {
    const out = window.getSuggestedWeight('Plank', 7);
    expect(out.weight).toBeNull();
  });

  it("returns null for Pallof Press with no history (no bench-ratio guess)", () => {
    const out = window.getSuggestedWeight('Pallof Press', 7);
    expect(out.weight).toBeNull();
  });

  it("still suggests from the lift's OWN logged history", () => {
    const out = window.getSuggestedWeight('Barbell Bench Press', 7);
    expect(out.weight).toBe(140); // real user data, not a static estimate
  });
});


describe('resolveDisplayWeight — the actual fix', () => {
  beforeAll(() => {
    loadAppJs();
  });

  it("target_weight=0 means bodyweight → empty string (suppresses estimator)", () => {
    const ex = { name: 'Hanging Leg Raise', target_weight: 0 };
    const suggestion = { weight: 35, reason: 'estimated' }; // bogus 35
    expect(window.resolveDisplayWeight(ex, suggestion)).toBe('');
  });

  it("target_weight=null falls through to suggestion", () => {
    const ex = { name: 'Cable Lateral Raise', target_weight: null };
    const suggestion = { weight: 15, reason: 'engine' };
    expect(window.resolveDisplayWeight(ex, suggestion)).toBe(15);
  });

  it("target_weight=undefined falls through to suggestion", () => {
    const ex = { name: 'Cable Lateral Raise' };
    const suggestion = { weight: 15, reason: 'engine' };
    expect(window.resolveDisplayWeight(ex, suggestion)).toBe(15);
  });

  it("target_weight as positive number wins over suggestion", () => {
    const ex = { name: 'Barbell Bench Press', target_weight: 140 };
    const suggestion = { weight: 100, reason: 'estimated' };
    expect(window.resolveDisplayWeight(ex, suggestion)).toBe(140);
  });

  it("returns empty when neither target_weight nor suggestion has a value", () => {
    const ex = {};
    const suggestion = { weight: null };
    expect(window.resolveDisplayWeight(ex, suggestion)).toBe('');
  });

  it("with displayName, applies roundWeight to non-zero prescriptions", () => {
    const ex = { name: 'Barbell Back Squat', target_weight: 142.5 };
    const suggestion = null;
    // roundWeight rounds barbell weights; the exact rounded value
    // depends on implementation but should be a multiple of 5.
    const out = window.resolveDisplayWeight(ex, suggestion, 'Barbell Back Squat');
    expect(typeof out).toBe('number');
    expect(out % 5).toBe(0); // some multiple of 5
  });

  it("with displayName, target_weight=0 still returns empty (no rounding)", () => {
    const ex = { name: 'Plank', target_weight: 0 };
    expect(window.resolveDisplayWeight(ex, null, 'Plank')).toBe('');
  });
});
