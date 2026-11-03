import { h } from './h';

const MAX_LINES = 200;

export interface Log {
  (message: string): void;
}

/** A small collapsible message list. The panel stays hidden until the first message. */
/** Each line carries an increasing `data-seq`, so a reader can tell what is new even after old lines were evicted. */
export const mountLog = (panel: HTMLDetailsElement, list: HTMLElement): Log => {
  let seq = 0;
  return (message) => {
    panel.hidden = false;
    list.append(h('li', { data: { seq: ++seq } }, message));
    while (list.childElementCount > MAX_LINES) list.firstElementChild?.remove();
  };
};
