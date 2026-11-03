import type { Instance } from '../../src/core/types';
import { fileSource } from '../../src/shell/source';

export interface Spec {
  name?: string;
  pid?: string;
  pname?: string;
  study?: string;
  date?: string | null;
  time?: string | null;
  sdesc?: string;
  acc?: string;
  series?: string;
  num?: number | null;
  desc?: string;
  mod?: string;
  sop?: string | null;
  inst?: number | null;
  echo?: number | null;
  rel?: string;
  frames?: number;
  size?: number;
  window?: { center: number; width: number } | null;
}

export const mk = (s: Spec = {}): Instance => ({
  source: fileSource(new File([new Uint8Array(s.size ?? 0)], s.name ?? 'f')),
  relPath: s.rel ?? s.name ?? 'f',
  sopInstanceUid: s.sop === undefined ? (s.name ?? 'f') : s.sop,
  transferSyntax: null,
  patient: { id: s.pid ?? 'P1', name: s.pname ?? 'Doe^Jane' },
  study: {
    uid: s.study ?? 'S1',
    date: s.date === undefined ? '20260101' : s.date,
    time: s.time === undefined ? '100000' : s.time,
    description: s.sdesc ?? 'Brain',
    accessionNumber: s.acc ?? '',
  },
  series: {
    uid: s.series ?? 'E1',
    number: s.num === undefined ? 1 : s.num,
    description: s.desc ?? 'T1',
    modality: s.mod ?? 'MR',
  },
  instanceNumber: s.inst === undefined ? null : s.inst,
  echoNumber: s.echo === undefined ? null : s.echo,
  frames: s.frames ?? 1,
  window: s.window ?? null,
});
