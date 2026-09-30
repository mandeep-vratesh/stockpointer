import { useId, useState } from 'react';
import s from '../styles.module.css';

export function InfoTooltip({ text }: { text: string }) {
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const id = useId();
  const show = (e: { currentTarget: HTMLElement }) => {
    const r = e.currentTarget.getBoundingClientRect();
    setPos({ x: Math.min(Math.max(r.left + r.width / 2, 140), window.innerWidth - 140), y: r.bottom + 6 });
  };
  const hide = () => setPos(null);
  return (
    <span className={s.tipWrap}>
      <button type="button" className={s.info} aria-label="More info" aria-describedby={pos ? id : undefined}
        onMouseEnter={show} onMouseLeave={hide} onFocus={show} onBlur={hide}
        onKeyDown={(e) => e.key === 'Escape' && hide()}>i</button>
      {pos && <span id={id} role="tooltip" className={s.tip} style={{ left: pos.x, top: pos.y }}>{text}</span>}
    </span>
  );
}
