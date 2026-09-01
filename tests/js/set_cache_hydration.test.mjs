/** S006: two Barbell lifts on one day, sets only under Bench → Row gets none. */
import { describe, it, expect, beforeAll } from 'vitest';
import { loadAppJs } from './load.mjs';

describe('resolveSetKey — canonical equality, never prefix fuzz', () => {
  beforeAll(() => { loadAppJs(); window._aliasMap = { 'KB Swing': 'Kettlebell Swing' }; });

  it('does not hydrate Bent-Over Row from Bench Press', () => {
    const setData = { '4_1_Barbell Bench Press': { 0: { done: true, weight: 135, reps: 5 } } };
    expect(window.resolveSetKey(setData, 4, 1, 'Barbell Bent-Over Row', 'Barbell Bent-Over Row')).toBeNull();
  });

  it('resolves an alias to the stored canonical key', () => {
    const setData = { '4_1_Kettlebell Swing': { 0: { done: true, weight: 53, reps: 15 } } };
    expect(window.resolveSetKey(setData, 4, 1, 'KB Swing', 'KB Swing')).toBe('4_1_Kettlebell Swing');
  });

  it('honours the original (pre-swap) name', () => {
    const setData = { '4_1_Barbell Row': { 0: { done: true } } };
    expect(window.resolveSetKey(setData, 4, 1, 'Dumbbell Row', 'Barbell Row')).toBe('4_1_Barbell Row');
  });
});
