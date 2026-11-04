import { describe, expect, test, vi } from 'vitest';
import { envelope, savedText } from '../../src/shell/envelope';

const TEXT = '{\n  "scans": [{"tr": 2.0}]\n}\n';
const NAME = 'fmri-qa-20261103-0905.zip';

describe('envelope', () => {
  test('Python ready: document_json is called with the inputs, and its text kept verbatim', async () => {
    const call = vi.fn(async () => TEXT);
    const document = await envelope({ kind: 'ready' }, call, ['a', 'b']);
    expect(document).toEqual({ text: TEXT });
    expect(call).toHaveBeenCalledWith(['a', 'b']);
    expect(savedText(NAME, document)).toBe(`Saved ${NAME}, with fmri-qa.json.`);
  });

  test('Python still starting: no call, and the outcome says so', async () => {
    const call = vi.fn(async () => TEXT);
    const document = await envelope({ kind: 'starting' }, call, ['a']);
    expect(call).not.toHaveBeenCalled();
    expect(savedText(NAME, document)).toBe(`Saved ${NAME} without fmri-qa.json: Python has not started yet.`);
  });

  test('Python did not start: no call, and the outcome gives its reason', async () => {
    const call = vi.fn(async () => TEXT);
    const document = await envelope({ kind: 'failed', reason: 'boot failed' }, call, ['a']);
    expect(call).not.toHaveBeenCalled();
    expect(savedText(NAME, document)).toBe(`Saved ${NAME} without fmri-qa.json: Python did not start (boot failed).`);
  });

  test('the call rejects (a crashed worker): no document, and the reason', async () => {
    const document = await envelope({ kind: 'ready' }, async () => Promise.reject(new Error('worker died')), ['a']);
    expect(document).toEqual({ missing: 'Python could not write it (worker died)' });
    expect(savedText(NAME, document)).toBe(`Saved ${NAME} without fmri-qa.json: Python could not write it (worker died).`);
  });
});
