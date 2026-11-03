/**
 * Determinate progress shared by scan, ZIP and convert. One operation at a time. `total === 0` is indeterminate.
 * Only start and end are announced to assistive tech (via the status element); updates touch just the bar and text.
 */
export interface Progress {
  /** Show the bar (indeterminate) with `text`; `onCancel` enables the Cancel button. */
  start(text: string, opts?: { readonly onCancel?: () => void }): void;
  update(u: { readonly done: number; readonly total: number; readonly text: string }): void;
  /** Hide the bar and announce `message` if given. */
  end(message?: string): void;
}

export const mountProgress = (bar: HTMLProgressElement, text: HTMLElement, cancel: HTMLButtonElement, status: HTMLElement): Progress => {
  let onCancel: (() => void) | undefined;
  cancel.addEventListener('click', () => onCancel?.());
  const indeterminate = (): void => bar.removeAttribute('value');
  return {
    start(t, opts = {}) {
      onCancel = opts.onCancel;
      cancel.hidden = !onCancel;
      indeterminate();
      text.textContent = t;
      status.textContent = t;
    },
    update({ done, total, text: t }) {
      if (total > 0) {
        bar.max = total;
        bar.value = done;
      } else indeterminate();
      text.textContent = t;
    },
    end(message) {
      onCancel = undefined;
      if (message) status.textContent = message;
    },
  };
};
