/** Display formatting: pure string functions. */

/** "Doe^Jane" -> "Doe, Jane"; "A^B^C" -> "A, B C"; "" -> "(no name)". */
export const formatName = (name: string): string => {
  const [family, ...rest] = name.split('^').map((s) => s.trim()).filter(Boolean);
  if (family === undefined) return '(no name)';
  return rest.length ? `${family}, ${rest.join(' ')}` : family;
};

/** DICOM DA "20260101" -> "2026-01-01"; anything else is shown as-is; null -> "no date". */
export const formatDate = (da: string | null): string =>
  da === null || da === '' ? 'no date' : /^\d{8}$/.test(da) ? `${da.slice(0, 4)}-${da.slice(4, 6)}-${da.slice(6)}` : da;

export const formatSize = (bytes: number): string => {
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let v = bytes;
  let i = -1;
  do {
    v /= 1024;
    i++;
  } while (v >= 1024 && i < units.length - 1);
  return `${v >= 100 ? v.toFixed(0) : v.toFixed(1)} ${units[i]}`;
};

export const plural = (n: number, one: string, many = `${one}s`): string => `${n.toLocaleString('en-US')} ${n === 1 ? one : many}`;
