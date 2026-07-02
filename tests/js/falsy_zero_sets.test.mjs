/**
 * Falsy-zero set-logging contract tests (2026-07-01 audit, theme 9b-frontend).
 *
 * History: toggleSet / saveSetField / logFocusSet all computed
 * `reps = repsTyped || repsTarget`, so an explicitly typed 0 (a FAILED set)
 * was falsy and silently replaced by the placeholder target before being
 * written to SetLog — the coach, history, and next-week progression then saw
 * a completed target-rep set that never happened. Same class of bug in the
 * weight prefill: `setData.weight ? setData.weight : carryWeight` dropped a
 * logged 0 (bodyweight set) and re-prefilled the suggested load, which a
 * re-toggle then re-saved over the logged 0.
 *
 * The canonical helpers are resolveLoggedReps / resolvePrefillWeight.
 */
import { describe, it, expect, beforeAll } from 'vitest';
import { loadAppJs } from './load.mjs';

describe('resolveLoggedReps — typed 0 is real data', () => {
  beforeAll(() => { loadAppJs(); });

  it('typed 0 stays 0 (failed set), never upgraded to the target', () => {
    expect(window.resolveLoggedReps('0', '8')).toBe(0);
  });

  it('empty field falls back to the target ("hit the target" convention)', () => {
    expect(window.resolveLoggedReps('', '8')).toBe(8);
  });

  it('typed value wins over the target', () => {
    expect(window.resolveLoggedReps('6', '8')).toBe(6);
  });

  it('empty field with no target resolves to 0', () => {
    expect(window.resolveLoggedReps('', '')).toBe(0);
  });

  it('timed-style target ("30s") parses for the empty-field fallback', () => {
    expect(window.resolveLoggedReps('', '30s')).toBe(30);
  });
});

describe('resolvePrefillWeight — logged 0 on a done set is real', () => {
  beforeAll(() => { loadAppJs(); });

  it('done set logged at 0 lb prefills 0, not the carried suggestion', () => {
    expect(window.resolvePrefillWeight({ done: true, weight: 0, reps: 12 }, 80)).toBe(0);
  });

  it('undone cached 0 means "nothing typed yet" → falls back to carry', () => {
    expect(window.resolvePrefillWeight({ done: false, weight: 0, reps: 0 }, 80)).toBe(80);
  });

  it('positive logged weight wins regardless of done state', () => {
    expect(window.resolvePrefillWeight({ done: false, weight: 95 }, 80)).toBe(95);
    expect(window.resolvePrefillWeight({ done: true, weight: 95 }, 80)).toBe(95);
  });

  it('no cache entry falls back to carry', () => {
    expect(window.resolvePrefillWeight(null, 80)).toBe(80);
    expect(window.resolvePrefillWeight(undefined, 80)).toBe(80);
  });
});
