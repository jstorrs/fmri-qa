/** Hand `blob` to the browser as a download named `name` (anchor-click path used where there is no save picker). */
export const saveBlob = (name: string, blob: Blob): void => {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.hidden = true;
  document.body.append(a);
  a.click();
  a.remove();
  // Revoking too early cancels the download in Firefox; the page keeps the Blob alive until then.
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
};
