/**
 * The run's `fmri-qa.json`, or why the run's ZIP goes without it. DOM-free: `src/shell/run.ts` passes Python's state and
 * its `document_json` call, `test/unit/envelope.test.ts` fakes.
 */

/** What `fmri-qa.json` can be written with: only a Python that started can run `document_json`. */
export type PythonState = { readonly kind: 'starting' | 'ready' } | { readonly kind: 'failed'; readonly reason: string };

export type Envelope = { readonly text: string } | { readonly missing: string };

const message = (e: unknown): string => (e instanceof Error ? e.message : String(e));

/** `document_json(inputs)` verbatim, or why there is none. Never rejects. */
export const envelope = async (state: PythonState, documentJson: (inputs: readonly string[]) => Promise<string>, inputs: readonly string[]): Promise<Envelope> => {
  if (state.kind === 'starting') return { missing: 'Python has not started yet' };
  if (state.kind === 'failed') return { missing: `Python did not start (${state.reason})` };
  try {
    return { text: await documentJson(inputs) };
  } catch (e) {
    return { missing: `Python could not write it (${message(e)})` };
  }
};

/** The outcome line for a run's ZIP that was saved. */
export const savedText = (name: string, document: Envelope): string =>
  'text' in document ? `Saved ${name}, with fmri-qa.json.` : `Saved ${name} without fmri-qa.json: ${document.missing}.`;
