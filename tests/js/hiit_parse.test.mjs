/** S063/S065: the timer runs the coach's structure — segments first, then
 * the coach's own prose format — never a fabricated default. */
import { describe, it, expect, beforeAll } from 'vitest';
import { loadAppJs } from './load.mjs';

describe('HIIT structure from the coach', () => {
  beforeAll(() => { loadAppJs(); });

  it('parses "5×3 min hard / 2 min easy" prose', () => {
    const cfg = window._parseHiitDetail('10 min warmup; 5×3 min hard @ HR ≤178 / 2 min easy; 5 min cooldown', '40 min');
    expect(cfg).not.toBeNull();
    expect(cfg.rounds).toBe(5); expect(cfg.work).toBe(180); expect(cfg.rest).toBe(120);
    expect(cfg.warmup).toBe(600); expect(cfg.cooldown).toBe(300);
  });

  it('builds phases from served segments that sum to the label', () => {
    const segs = [{kind:'warmup',minutes:10},{kind:'work',minutes:3,reps:5},{kind:'recovery',minutes:2,reps:5},{kind:'cooldown',minutes:5}];
    const phases = window._phasesFromSegments(segs, '40 min');
    expect(phases).not.toBeNull();
    const total = phases.reduce((a, p) => a + p.duration, 0);
    expect(total).toBe(40 * 60);
    expect(phases[phases.length - 1].name).toBe('COOLDOWN');
  });

  it('refuses segments that contradict the label', () => {
    const segs = [{kind:'work',minutes:3,reps:5},{kind:'recovery',minutes:2,reps:5}];
    expect(window._phasesFromSegments(segs, '60 min')).toBeNull();
  });

  it('still fails loud on unparseable prose', () => {
    expect(window._parseHiitDetail('hard intervals, feel it out', '30 min')).toBeNull();
  });
});
