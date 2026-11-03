/** Tiny DOM builder. Strings become text nodes (textContent), never HTML. */
export type Child = Node | string | number | null | undefined | false;

export interface Props {
  readonly class?: string;
  readonly data?: Readonly<Record<string, string | number | undefined>>;
  readonly attrs?: Readonly<Record<string, string | number | boolean | undefined>>;
  readonly on?: { readonly [K in keyof HTMLElementEventMap]?: (e: HTMLElementEventMap[K]) => void };
}

export const h = <K extends keyof HTMLElementTagNameMap>(
  tag: K,
  props: Props = {},
  ...children: Child[]
): HTMLElementTagNameMap[K] => {
  const el = document.createElement(tag);
  if (props.class) el.className = props.class;
  for (const [k, v] of Object.entries(props.data ?? {})) if (v !== undefined) el.dataset[k] = String(v);
  for (const [k, v] of Object.entries(props.attrs ?? {})) {
    if (v === undefined || v === false) continue;
    el.setAttribute(k, v === true ? '' : String(v));
  }
  for (const [k, fn] of Object.entries(props.on ?? {})) el.addEventListener(k, fn as EventListener);
  for (const c of children) if (c !== null && c !== undefined && c !== false) el.append(typeof c === 'number' ? String(c) : c);
  return el;
};
