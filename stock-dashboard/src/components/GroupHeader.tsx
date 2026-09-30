import { GroupCfg, Meta, NONE } from '../types';
import { InfoTooltip } from './InfoTooltip';
import { NumInput } from './ColumnHeader';
import s from '../styles.module.css';

export function GroupHeader({ group, meta }: { group: GroupCfg; meta: Meta }) {
  const { settings: st, h } = meta;
  const collapsed = !!st.collapsedGroups[group.id];
  const max = group.columns.reduce(
    (a, c) => (st.columnConditions[c.id] !== NONE ? a + Math.max(0, st.columnWeights[c.id] ?? 0) : a), 0);
  return (
    <div className={s.groupHead}>
      <button className={s.groupToggle} aria-expanded={!collapsed} onClick={() => h.toggleGroup(group.id)}>
        <span aria-hidden>{collapsed ? '▸' : '▾'}</span> {group.label}
      </button>
      <InfoTooltip text={group.description} />
      <label className={s.inline}>Weight
        <NumInput label={`${group.label} group weight`} value={st.groupWeights[group.id]} onChange={(n) => h.setGroupWeight(group.id, n ?? 0)} />
      </label>
      <span className={s.muted}>max {max}</span>
    </div>
  );
}
