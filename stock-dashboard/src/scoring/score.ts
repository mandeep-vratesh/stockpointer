import { GroupCfg, NONE, Row, Scored, Settings } from '../types';
import { evaluateCondition } from './evaluate';

const w = (n: unknown) => (typeof n === 'number' && Number.isFinite(n) ? n : 0);

export function scoreRow(row: Row, groups: GroupCfg[], s: Pick<Settings, 'groupWeights' | 'columnWeights' | 'columnConditions'>): Scored {
  const colPts: Record<string, number> = {};
  const groupPoints: Record<string, number> = {};
  let total = 0;
  for (const g of groups) {
    let gp = 0;
    for (const c of g.columns) {
      const cid = s.columnConditions[c.id];
      const cond = cid && cid !== NONE ? c.conditions.find((k) => k.id === cid) : undefined;
      const pts = cond && evaluateCondition(cond, row.data[c.field], row.data) ? w(s.columnWeights[c.id]) : 0;
      colPts[c.id] = pts;
      gp += pts;
    }
    groupPoints[g.id] = gp;
    total += w(s.groupWeights[g.id]) * gp; // collapsed groups still count
  }
  return { row, colPts, groupPoints, total };
}

/** Total desc, ties by symbol asc. */
export const rank = (a: Scored, b: Scored) => b.total - a.total || a.row.symbol.localeCompare(b.row.symbol);
