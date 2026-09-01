/** S020: buffered SSE parsing and non-OK responses as error frames. */
import { describe, it, expect, beforeAll } from 'vitest';
import { loadAppJs } from './load.mjs';

function streamOf(chunks) {
  const enc = new TextEncoder();
  let i = 0;
  return { getReader() { return { read: () => Promise.resolve(i < chunks.length ? { done: false, value: enc.encode(chunks[i++]) } : { done: true }) }; } };
}

// The same loop shape every reader in app.js uses after the S020 patch.
async function drain(reader) {
  const decoder = new TextDecoder(); let _sseBuf = ''; let full = ''; let err = null;
  while (true) {
    const r = await reader.read(); if (r.done) break;
    const chunk = decoder.decode(r.value, { stream: true });
    _sseBuf += chunk; const lines = _sseBuf.split('\n'); _sseBuf = lines.pop();
    let stop = false;
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      const d = line.slice(6);
      if (d === '[DONE]') { stop = true; break; }
      if (d.startsWith('[ERROR')) { err = d; stop = true; break; }
      full += d.replace(/\\n/g, '\n');
    }
    if (stop) break;
  }
  return { full, err };
}

describe('SSE reading', () => {
  beforeAll(() => { loadAppJs(); });

  it('a data: line split across reads is reassembled, not truncated', async () => {
    const res = { ok: true, body: streamOf(['data: hel', 'lo wor', 'ld\n\ndata: [DONE]\n\n']) };
    const { full } = await drain(window.sseReader(res));
    expect(full).toBe('hello world');
  });

  it('a 429 becomes a friendly [ERROR] frame instead of an empty stream', async () => {
    const res = { ok: false, status: 429, clone() { return this; }, json: () => Promise.resolve({ error: 'rate' }) };
    const { err } = await drain(window.sseReader(res));
    expect(err).toContain('Too fast');
  });

  it('a 5xx surfaces the server error text', async () => {
    const res = { ok: false, status: 502, clone() { return this; }, json: () => Promise.resolve({ error: 'upstream dead' }) };
    const { err } = await drain(window.sseReader(res));
    expect(err).toContain('upstream dead');
  });
});
