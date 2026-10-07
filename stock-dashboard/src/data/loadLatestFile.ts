import { getBytes, listAll, ref } from 'firebase/storage';
import { storage } from '../firebase';
import { DashboardConfig, DataRow, Row } from '../types';

export class DataError extends Error {
  constructor(public kind: 'no-files' | 'fetch' | 'parse', message: string) { super(message); }
}

const toNum = (v: unknown): number | null => {
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  if (typeof v === 'string' && v.trim() !== '') { const n = Number(v.replace(/,/g, '')); return Number.isFinite(n) ? n : null; }
  return null;
};

/** Minimal RFC 4180 CSV parser (quoted fields, escaped quotes, CRLF, BOM). */
function parseCsv(text: string): string[][] {
  if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
  const rows: string[][] = [];
  let row: string[] = [];
  let f = '';
  let q = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (q) {
      if (ch === '"') { if (text[i + 1] === '"') { f += '"'; i++; } else q = false; }
      else f += ch;
    } else if (ch === '"') q = true;
    else if (ch === ',') { row.push(f); f = ''; }
    else if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && text[i + 1] === '\n') i++;
      row.push(f); f = ''; rows.push(row); row = [];
    } else f += ch;
  }
  if (f !== '' || row.length) { row.push(f); rows.push(row); }
  return rows.filter((r) => r.some((c) => c.trim() !== ''));
}

function csvToObjects(text: string): DataRow[] {
  const [head, ...body] = parseCsv(text);
  if (!head) throw new Error('CSV file is empty.');
  const cols = head.map((h) => h.trim());
  return body.map((r) =>
    Object.fromEntries(cols.map((h, i) => { const v = (r[i] ?? '').trim(); return [h, v === '' ? null : v]; }))
  );
}

function normalize(raw: DataRow[], cfg: DashboardConfig): Row[] {
  if (raw.length && !(cfg.symbolField in raw[0]))
    throw new Error(`Column "${cfg.symbolField}" not found. CSV columns: ${Object.keys(raw[0]).join(', ')}`);
  const numeric = new Set<string>();
  for (const g of cfg.groups) for (const c of g.columns) {
    if (c.type === 'number') numeric.add(c.field);
    for (const k of c.conditions) if (k.field) numeric.add(k.field);
  }
  const rows: Row[] = [];
  for (const r of raw) {
    const sym = r[cfg.symbolField];
    if (sym == null || sym === '') continue;
    const data: DataRow = { ...r };
    numeric.forEach((f) => { data[f] = toNum(r[f]); });
    rows.push({ symbol: String(sym), data });
  }
  return rows;
}

/**
 * Files live at `<dataPath>/<YYYY-MM-DD>/<fileName with {date}>` (e.g. reports/2026-09-29/stock_data_2026-09-29.csv).
 * Loads the file for `wanted`, or the latest date folder when omitted. `dates` lists all available dates, newest first.
 */
export async function loadLatestFile(cfg: DashboardConfig, wanted?: string): Promise<{ date: string; rows: Row[]; dates: string[] }> {
  const re = new RegExp(cfg.folderRegex);
  let dates: string[];
  try {
    const { prefixes } = await listAll(ref(storage, cfg.dataPath));
    dates = prefixes.map((p) => re.exec(p.name)?.[1]).filter((d): d is string => !!d).sort().reverse();
  } catch (e) { throw new DataError('fetch', `Could not list ${cfg.dataPath}/: ${(e as Error).message}`); }
  if (!dates.length) throw new DataError('no-files', `No date folders matching ${cfg.folderRegex} in ${cfg.dataPath}/.`);

  const date = wanted ?? dates[0];
  if (!dates.includes(date)) throw new DataError('no-files', `No data file for ${date}. Available: ${dates[dates.length - 1]} to ${dates[0]}.`);

  const path = `${cfg.dataPath}/${date}/${cfg.fileName.replace('{date}', date)}`;
  let text: string;
  try { text = new TextDecoder().decode(await getBytes(ref(storage, path))); }
  catch (e) { throw new DataError('fetch', `Could not download ${path}: ${(e as Error).message}`); }
  try { return { date, rows: normalize(csvToObjects(text), cfg), dates }; }
  catch (e) { throw new DataError('parse', `Could not parse ${path}: ${(e as Error).message}`); }
}
