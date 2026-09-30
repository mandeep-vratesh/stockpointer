import { Condition, DataRow } from '../types';

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);

/** Pure condition check. Null/undefined values never satisfy a condition. */
export function evaluateCondition(cond: Condition, value: unknown, row: DataRow): boolean {
  if (value == null) return false;
  switch (cond.op) {
    case 'in': return (cond.values ?? []).includes(value as never);
    case 'eq': return value === cond.value;
    case 'neq': return value !== cond.value;
  }
  const x = num(value);
  if (x == null) return false;
  switch (cond.op) {
    case 'lt': return cond.value != null && x < Number(cond.value);
    case 'lte': return cond.value != null && x <= Number(cond.value);
    case 'gt': return cond.value != null && x > Number(cond.value);
    case 'gte': return cond.value != null && x >= Number(cond.value);
    case 'between': return cond.min != null && cond.max != null && x >= cond.min && x <= cond.max;
    case 'ltField': { const o = num(cond.field ? row[cond.field] : null); return o != null && x < o; }
    case 'gtField': { const o = num(cond.field ? row[cond.field] : null); return o != null && x > o; }
    default: return false;
  }
}
