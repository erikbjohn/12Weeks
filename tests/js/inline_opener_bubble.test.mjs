/** 2026-09-02: the inline coach opener must fill ITS OWN bubble, not the first
 * history bubble — after today's history is inserted above it, the dots stayed. */
import { describe, it, expect, beforeAll } from 'vitest';
import { loadAppJs } from './load.mjs';

function streamOf(chunks) {
  const enc = new TextEncoder(); let i = 0;
  return { getReader() { return { read: () => Promise.resolve(i < chunks.length ? { done: false, value: enc.encode(chunks[i++]) } : { done: true }), cancel: () => {} }; } };
}

describe('inline coach opener', () => {
  beforeAll(() => { loadAppJs(); });
  it('renders history above the opener and fills the opener bubble, leaving no typing dots', async () => {
    document.body.innerHTML = '<div id="coach-inline-messages"><div class="chat-bubble coach" id="coach-inline-opener"><div class="chat-typing"></div></div></div>';
    window.renderCoachMarkdown = window.renderCoachMarkdown || ((t) => t);
    window.fetch = (url) => {
      if (String(url).includes('today-history')) return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([{ role: 'assistant', content: 'earlier reply', type: 'chat' }]) });
      return Promise.resolve({ ok: true, status: 200, body: streamOf(['data: opener text\n\ndata: [DONE]\n\n']) });
    };
    await window._renderTodayHistoryInline();
    await window._fetchInlineCoachOpener();
    const el = document.getElementById('coach-inline-messages');
    expect(el.textContent).toContain('earlier reply');
    expect(document.getElementById('coach-inline-opener').textContent).toContain('opener text');
    expect(el.querySelector('.chat-typing')).toBeNull();
    expect(el.textContent.indexOf('earlier reply')).toBeLessThan(el.textContent.indexOf('opener text'));
  });
});
