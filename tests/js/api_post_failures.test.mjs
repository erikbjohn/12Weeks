/**
 * S014: a rejected /api/sets save must not leave the checkmark green.
 *   5xx → queued for replay (optimistic UI stays; it WILL be written)
 *   4xx → definitive rejection: toast + res.rejected so toggleSet reverts
 */
import { describe, it, expect, beforeAll, vi } from 'vitest';
import { loadAppJs } from './load.mjs';

function mockRes(status, json) {
  const r = { ok: status < 400, status, json: () => Promise.resolve(json), clone() { return this; } };
  return r;
}

describe('apiPost failure classification', () => {
  beforeAll(() => { loadAppJs(); });

  it('5xx queues the write and does not mark it rejected', async () => {
    const queued = [];
    window.queueForSync = (url, body) => { queued.push({ url, body }); };
    window.showToast = () => {};
    window.fetch = () => Promise.resolve(mockRes(500, { error: 'Save failed' }));
    const res = await window.apiPost('/api/sets', { a: 1 });
    expect(queued).toHaveLength(1);
    expect(res.rejected).toBeFalsy();
  });

  it('4xx is a definitive rejection: toast with the server text, not queued', async () => {
    const queued = [];
    const toasts = [];
    window.queueForSync = (url, body) => { queued.push({ url, body }); };
    window.showToast = (m) => { toasts.push(m); };
    window.fetch = () => Promise.resolve(mockRes(400, { error: 'Nothing to log' }));
    const res = await window.apiPost('/api/sets', { a: 1 });
    await new Promise(r => setTimeout(r, 0));
    expect(queued).toHaveLength(0);
    expect(res.rejected).toBe(true);
    expect(toasts.join(' ')).toContain('Nothing to log');
  });
});

describe('toggleSet reverts the optimistic checkmark on a 4xx', () => {
  beforeAll(() => { loadAppJs(); });

  it('checkmark and cache go back to un-done', async () => {
    document.body.innerHTML = `
      <div class="set-row">
        <input id="wt-1-0-0-0" value="100"><input id="reps-1-0-0-0" value="5" placeholder="5">
        <button id="btn"></button>
      </div>`;
    window.showToast = () => {};
    window.queueForSync = () => {};
    window._confirmSetIfSuspicious = () => true;
    window.renderDetail = () => {};
    window.fetch = () => Promise.resolve(mockRes(400, { error: 'rejected' }));
    const btn = document.getElementById('btn');
    window.toggleSet(1, 0, 0, 0, 60, 'Bench', btn);
    expect(btn.classList.contains('done')).toBe(true); // optimistic
    await new Promise(r => setTimeout(r, 20));
    expect(btn.classList.contains('done')).toBe(false); // reverted
    expect(btn.closest('.set-row').classList.contains('set-done')).toBe(false);
  });
});
