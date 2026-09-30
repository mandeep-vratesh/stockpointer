import { useMemo } from 'react';
import { ColumnDef, FilterFn, flexRender, getCoreRowModel, getFilteredRowModel, useReactTable } from '@tanstack/react-table';
import { ColumnCfg, config, Filter, Handlers, Meta, Scored, Settings } from '../types';
import { ColumnHeader } from './ColumnHeader';
import { GroupHeader } from './GroupHeader';
import s from '../styles.module.css';

const numFilter: FilterFn<Scored> = (row, id, v: Filter) => {
  const x = row.getValue<number | null>(id);
  if (v.min != null && (x == null || x < v.min)) return false;
  if (v.max != null && (x == null || x > v.max)) return false;
  return true;
};
const textFilter: FilterFn<Scored> = (row, id, v: Filter) => {
  if (!v.contains) return true;
  const x = row.getValue<string | null>(id);
  return x != null && String(x).toLowerCase().includes(v.contains.toLowerCase());
};

function fmt(v: unknown, c: ColumnCfg): string {
  if (v == null || v === '') return '—';
  if (typeof v === 'number') {
    const f = c.format ?? {};
    return `${f.prefix ?? ''}${f.decimals != null ? v.toFixed(f.decimals) : v}${f.suffix ?? ''}`;
  }
  return String(v);
}
const metaOf = (t: { options: { meta?: unknown } }) => t.options.meta as Meta;

export function ScoreTable({ rows, settings, handlers }: { rows: Scored[]; settings: Settings; handlers: Handlers }) {
  const columns = useMemo<ColumnDef<Scored>[]>(() => {
    const fx = config.fixedColumns;
    return [
      {
        id: 'symbol', accessorFn: (r) => r.row.symbol, enableColumnFilter: false,
        header: () => <ColumnHeader label={fx.symbol.label} description={fx.symbol.description} />,
        cell: (c) => <strong>{c.getValue<string>()}</strong>,
      },
      ...config.groups.map<ColumnDef<Scored>>((g) => ({
        id: g.id,
        header: ({ table }) => <GroupHeader group={g} meta={metaOf(table)} />,
        columns: [
          ...g.columns.map<ColumnDef<Scored>>((c) => ({
            id: c.id, accessorFn: (r) => r.row.data[c.field] ?? null,
            filterFn: c.type === 'number' ? numFilter : textFilter,
            header: ({ table }) => <ColumnHeader label={c.label} description={c.description} col={c} meta={metaOf(table)} />,
            cell: ({ row, getValue }) => (
              <span className={row.original.colPts[c.id] !== 0 ? s.hit : undefined}>{fmt(getValue(), c)}</span>
            ),
          })),
          {
            id: `${g.id}__pts`, accessorFn: (r) => r.groupPoints[g.id], enableColumnFilter: false,
            header: () => <ColumnHeader label={`${g.label} Pts`} description={`Points from ${g.label} (before group weight).`} />,
            cell: (c) => c.getValue<number>(),
          },
        ],
      })),
      {
        id: 'total', accessorFn: (r) => r.total, enableColumnFilter: false,
        header: () => <ColumnHeader label={fx.totalPoints.label} description={fx.totalPoints.description} />,
        cell: (c) => <strong>{c.getValue<number>()}</strong>,
      },
    ];
  }, []);

  const columnVisibility = useMemo(() => {
    const v: Record<string, boolean> = {};
    for (const g of config.groups) {
      const col = !!settings.collapsedGroups[g.id];
      g.columns.forEach((c) => { v[c.id] = !col; });
      v[`${g.id}__pts`] = col;
    }
    return v;
  }, [settings.collapsedGroups]);

  const columnFilters = useMemo(
    () => Object.entries(settings.columnFilters).map(([id, value]) => ({ id, value })),
    [settings.columnFilters]
  );

  const table = useReactTable({
    data: rows, columns, meta: { settings, h: handlers } as Meta,
    state: { columnVisibility, columnFilters },
    getRowId: (r) => r.row.symbol,
    getCoreRowModel: getCoreRowModel(), getFilteredRowModel: getFilteredRowModel(),
  });
  const pin = (id: string) => (id === 'symbol' ? s.pinL : id === 'total' ? s.pinR : '');
  const visibleRows = table.getRowModel().rows;

  return (
    <div className={s.scroll}>
      <table className={s.table}>
        <thead>
          {table.getHeaderGroups().map((hg, i) => (
            <tr key={hg.id}>
              {hg.headers.map((h) => {
                if (i === 1 && !h.column.parent) return null; // fixed columns span both rows
                const fixed = i === 0 && h.isPlaceholder;
                return (
                  <th key={h.id} colSpan={h.colSpan} rowSpan={fixed ? 2 : 1}
                    className={[i === 0 ? s.th0 : s.th1, pin(h.column.id)].join(' ')}>
                    {fixed || !h.isPlaceholder ? flexRender(h.column.columnDef.header, h.getContext()) : null}
                  </th>
                );
              })}
            </tr>
          ))}
        </thead>
        <tbody>
          {visibleRows.map((r) => (
            <tr key={r.id}>
              {r.getVisibleCells().map((c) => (
                <td key={c.id} className={pin(c.column.id)}>{flexRender(c.column.columnDef.cell, c.getContext())}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {visibleRows.length === 0 && (
        <p className={s.empty}>No stocks match this symbol group and the current filters. Clear a column filter or pick another group.</p>
      )}
    </div>
  );
}
