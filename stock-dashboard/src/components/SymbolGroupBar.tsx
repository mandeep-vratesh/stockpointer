import { useEffect, useState } from 'react';
import { ALL_ID, groupsConfig } from '../types';
import s from '../styles.module.css';

const segOf = (g: string | null) => groupsConfig.segments.find((x) => x.indices.some((i) => i.id === g))?.id;

export function SymbolGroupBar({ active, onSelect }: { active: string | null; onSelect: (id: string) => void }) {
  const segs = groupsConfig.segments;
  const [seg, setSeg] = useState<string | undefined>(segOf(active) ?? segs[0]?.id);
  useEffect(() => { const o = segOf(active); if (o) setSeg(o); }, [active]);
  const current = segs.find((x) => x.id === seg);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <nav className={s.chips} aria-label="Segments" style={{ alignItems: 'center' }}>
        <button className={active === ALL_ID ? s.chipOn : s.chip} aria-pressed={active === ALL_ID} onClick={() => onSelect(ALL_ID)}>
          All stocks
        </button>
        {segs.map((x) => (
          <button key={x.id} aria-pressed={x.id === seg} onClick={() => setSeg(x.id)}
            style={{ borderRadius: 6, borderColor: x.id === seg ? '#2458d3' : undefined, background: x.id === seg ? '#e9eef7' : undefined, fontWeight: x.id === seg ? 600 : 400 }}>
            {x.label}
          </button>
        ))}
      </nav>
      {current && (
        <nav className={s.chips} aria-label={`${current.label} indices`}>
          {current.indices.map((i) => (
            <button key={i.id} className={i.id === active ? s.chipOn : s.chip} aria-pressed={i.id === active}
              title={`${i.symbols.length} stocks`} onClick={() => onSelect(i.id)}>
              {i.label}
            </button>
          ))}
        </nav>
      )}
    </div>
  );
}
