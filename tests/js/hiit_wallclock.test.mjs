/** S027: the HIIT/plank overlay is wall-clock — a phase that elapsed while the
 * tab was suspended is completed on the next tick, and marked done. */
import { describe, it, expect, beforeAll, vi } from 'vitest';
import { loadAppJs } from './load.mjs';

describe('HIIT wall-clock catch-up', () => {
  beforeAll(() => { loadAppJs(); });

  it('completes every work phase that elapsed while hidden', () => {
    document.body.innerHTML = '<div id="hiit-overlay"></div>';
    const marked = [];
    window.apiPost = () => Promise.resolve({ ok: true });
    window._hiitMarkSetDone = (i) => marked.push(i);
    window._hiitRenderPhase = () => {}; window._hiitRenderCount = () => {};
    window.timerBeep = () => {}; window.wakeLockAcquire = () => {}; window.wakeLockRelease = () => {};
    window._hiitFinish = () => { window.__finished = true; window._hiitState = null; };
    // 3 sets of 30s work / 10s rest, started 200s "ago" (screen locked)
    const now = Date.now();
    window.__testHooks.setHiitState && window.__testHooks.setHiitState(null);
    vi.spyOn(Date, 'now').mockReturnValue(now - 200000);
    window.startExerciseHiit('Plank', 4, 1, 0, 30, 10, 3, 0);
    Date.now.mockReturnValue(now);
    window._hiitTick();
    expect(marked).toEqual([0, 1, 2]);
    expect(window.__finished).toBe(true);
    Date.now.mockRestore();
  });
});
