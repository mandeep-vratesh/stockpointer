import { useEffect, useState } from 'react';
import { ColumnCfg, Meta, NONE } from '../types';
import { InfoTooltip } from './InfoTooltip';
import s from '../styles.module.css';

export function NumInput({ value, onChange, label }: { value?: number; onChange: (v?: number) => void; label: string }) {
  const [t, setT] = useState(value == null ? '' : String(value));
  useEffect(() => {
    if ((t === '' ? undefined : Number(t)) !== value) setT(value == null ? '' : String(value));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  return (
    <input className={s.num} type="number" step="any" aria-label={label} value={t}
      onChange={(e) => {
        setT(e.target.value);
        const n = e.target.value === '' ? undefined : Number(e.target.value);
        onChange(n != null && Number.isFinite(n) ? n : undefined);
      }} />
  );
}

export function ColumnHeader({ label, description, col, meta }: { label: string; description: string; col?: ColumnCfg; meta?: Meta }) {
  const title = (
    <div className={s.colTitle}><span>{label}</span><InfoTooltip text={description} /></div>
  );
  if (!col || !meta) return title;
  const { settings: st, h } = meta;
  const f = st.columnFilters[col.id] ?? {};
  return (
    <div className={s.colHead}>
      {title}
      <div className={s.give}>
        Give
        <NumInput label={`${col.label} weight`} value={st.columnWeights[col.id]} onChange={(n) => h.setColumnWeight(col.id, n ?? 0)} />
        when
        <select aria-label={`${col.label} condition`} value={st.columnConditions[col.id] ?? NONE} onChange={(e) => h.setCondition(col.id, e.target.value)}>
          <option value={NONE}>{NONE}</option>
          {col.conditions.map((k) => <option key={k.id} value={k.id}>{k.label}</option>)}
        </select>
      </div>
      <div className={s.filter}>
        {col.type === 'number' ? (
          <>
            <NumInput label={`${col.label} minimum`} value={f.min} onChange={(v) => h.setFilter(col.id, { ...f, min: v })} />
            <span>–</span>
            <NumInput label={`${col.label} maximum`} value={f.max} onChange={(v) => h.setFilter(col.id, { ...f, max: v })} />
          </>
        ) : (
          <input type="text" placeholder="contains…" aria-label={`${col.label} contains`} value={f.contains ?? ''}
            onChange={(e) => h.setFilter(col.id, { ...f, contains: e.target.value || undefined })} />
        )}
      </div>
    </div>
  );
}
