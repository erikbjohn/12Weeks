/** S020 (real reader): a `data:` line split across two network reads must be
 * reassembled by the ACTUAL sendChatMessage loop in app.js, not a copy. */
import { describe, it, expect, beforeAll } from 'vitest';
import { loadAppJs } from './load.mjs';

function streamOf(chunks) {
  const enc = new TextEncoder(); let i = 0;
  return { getReader() { return { read: () => Promise.resolve(i < chunks.length ? { done: false, value: enc.encode(chunks[i++]) } : { done: true }), cancel: () => {} }; } };
}

describe('sendChatMessage reassembles split SSE frames', () => {
  beforeAll(() => { loadAppJs(); });
  it('a data: line cut mid-word arrives whole in the bubble', async () => {
    document.body.innerHTML = '<input id="ci" value="hello"><div id="cc"></div>';
    window.fetch = () => Promise.resolve({ ok: true, status: 200, body: streamOf(['data: Deadli', 'ft 145x6 held.\n\ndata: [DONE]\n\n']) });
    window.renderCoachMarkdown = window.renderCoachMarkdown || ((t) => t);
    await window.sendChatMessage('ci', 'cc');
    const bubble = document.getElementById('stream-bubble-cc');
    expect(bubble).toBeTruthy();
    expect(bubble.textContent).toContain('Deadlift 145x6 held.');
    expect(bubble.textContent).not.toContain('Deadli ');
  });
});
