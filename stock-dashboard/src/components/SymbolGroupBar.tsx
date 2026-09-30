import { config } from '../types';
import s from '../styles.module.css';

export function SymbolGroupBar({ active, onSelect }: { active: string | null; onSelect: (id: string) => void }) {
  return (
    <nav className={s.chips} aria-label="Symbol groups">
      {config.symbolGroups.map((g) => (
        <button key={g.id} className={g.id === active ? s.chipOn : s.chip} aria-pressed={g.id === active} onClick={() => onSelect(g.id)}>
          {g.label}
        </button>
      ))}
    </nav>
  );
}
