/** S013: an unreachable server must never read as "onboarding incomplete". */
import { describe, it, expect, beforeAll } from 'vitest';
import { loadAppJs } from './load.mjs';

describe('checkOnboardingComplete tri-state', () => {
  beforeAll(() => { loadAppJs(); });

  it('returns null (unknown) when any probe is a 5xx', async () => {
    window.fetch = () => Promise.resolve({ ok: false, status: 502, json: () => Promise.reject(new Error('html')) });
    expect(await window.checkOnboardingComplete()).toBeNull();
  });

  it('returns null when the network throws', async () => {
    window.fetch = () => Promise.reject(new Error('offline'));
    expect(await window.checkOnboardingComplete()).toBeNull();
  });

  it('returns false only on real incomplete data', async () => {
    window.fetch = () => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ completed: false, computed: false }) });
    expect(await window.checkOnboardingComplete()).toBe(false);
  });

  it('showServerUnreachable keeps the header and offers Retry', () => {
    document.body.innerHTML = '<header style="display:none"></header><div id="detail-panel"></div>';
    window.showServerUnreachable();
    expect(document.querySelector('header').style.display).not.toBe('none');
    expect(document.getElementById('detail-panel').textContent).toContain('Retry');
  });
});
