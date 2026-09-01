/** S019: today's card always has a weigh-in affordance. */
import { describe, it, expect, beforeAll } from 'vitest';
import { loadAppJs } from './load.mjs';

describe('weighInChipHtml', () => {
  beforeAll(() => { loadAppJs(); });
  it('offers an input when today is not logged', () => {
    window.__testHooks.setWeightsCache && window.__testHooks.setWeightsCache({});
    // no bodyweight today
    const html = window.weighInChipHtml();
    expect(html).toContain('id="th-weight"');
    expect(html).toContain('Log weigh-in');
  });
});
