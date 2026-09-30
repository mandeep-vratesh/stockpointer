import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { get, ref, remove, set } from 'firebase/database';
import { db } from '../firebase';
import { config, Filter, Handlers, NONE, SavedSettings, Settings } from '../types';

const defaults: Settings = {
  groupWeights: Object.fromEntries(config.groups.map((g) => [g.id, g.defaultWeight])),
  columnWeights: Object.fromEntries(config.groups.flatMap((g) => g.columns.map((c) => [c.id, c.defaultWeight]))),
  columnConditions: Object.fromEntries(config.groups.flatMap((g) => g.columns.map((c) => [c.id, c.defaultCondition || NONE]))),
  columnFilters: {},
  collapsedGroups: {},
};
const clean = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
type Overrides = Partial<SavedSettings>;

export function useUserSettings(uid: string) {
  const [group, setGroupState] = useState<string | null>(null);
  const [overrides, setOverrides] = useState<Overrides>({});
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [error, setError] = useState<string>();
  const ovRef = useRef<Overrides>({});
  const timer = useRef<number>();
  const pending = useRef<{ g: string; data: Overrides } | null>(null);

  const flush = useCallback(() => {
    window.clearTimeout(timer.current);
    const p = pending.current;
    pending.current = null;
    if (p) set(ref(db, `users/${uid}/settings/${p.g}`), clean({ ...p.data, updatedAt: Date.now() })).catch((e) => setError(`Save failed: ${e.message}`));
  }, [uid]);

  useEffect(() => flush, [flush]);

  // 1) last used group
  useEffect(() => {
    let off = false;
    get(ref(db, `users/${uid}/lastSymbolGroup`))
      .then((s) => {
        if (off) return;
        const v = s.val();
        setGroupState(config.symbolGroups.some((g) => g.id === v) ? v : config.defaultSymbolGroup);
      })
      .catch((e) => { if (!off) { setError(e.message); setStatus('error'); setGroupState(config.defaultSymbolGroup); } });
    return () => { off = true; };
  }, [uid]);

  // 2) that group's settings
  useEffect(() => {
    if (!group) return;
    let off = false;
    setStatus('loading');
    get(ref(db, `users/${uid}/settings/${group}`))
      .then((s) => {
        if (off) return;
        const v = (s.val() ?? {}) as Overrides;
        ovRef.current = v; setOverrides(v); setError(undefined); setStatus('ready');
      })
      .catch((e) => { if (!off) { setError(e.message); setStatus('error'); } });
    return () => { off = true; };
  }, [uid, group]);

  const mutate = useCallback((fn: (o: Overrides) => Overrides) => {
    if (!group || status !== 'ready') return;
    const next = fn(ovRef.current);
    ovRef.current = next; setOverrides(next);
    pending.current = { g: group, data: next };
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(flush, 500);
  }, [group, status, flush]);

  const setGroup = useCallback((g: string) => {
    flush();
    set(ref(db, `users/${uid}/lastSymbolGroup`), g).catch((e) => setError(`Save failed: ${e.message}`));
    setGroupState(g);
  }, [uid, flush]);

  const reset = useCallback(() => {
    if (!group) return;
    window.clearTimeout(timer.current); pending.current = null;
    ovRef.current = {}; setOverrides({});
    remove(ref(db, `users/${uid}/settings/${group}`)).catch((e) => setError(`Reset failed: ${e.message}`));
  }, [uid, group]);

  const settings = useMemo<Settings>(() => ({
    groupWeights: { ...defaults.groupWeights, ...overrides.groupWeights },
    columnWeights: { ...defaults.columnWeights, ...overrides.columnWeights },
    columnConditions: { ...defaults.columnConditions, ...overrides.columnConditions },
    columnFilters: { ...overrides.columnFilters },
    collapsedGroups: { ...overrides.collapsedGroups },
  }), [overrides]);

  const handlers = useMemo<Handlers>(() => ({
    setGroupWeight: (id, n) => mutate((o) => ({ ...o, groupWeights: { ...o.groupWeights, [id]: n } })),
    setColumnWeight: (id, n) => mutate((o) => ({ ...o, columnWeights: { ...o.columnWeights, [id]: n } })),
    setCondition: (id, c) => mutate((o) => ({ ...o, columnConditions: { ...o.columnConditions, [id]: c } })),
    setFilter: (id, f: Filter) => mutate((o) => {
      const cf = { ...o.columnFilters };
      const empty = f.min == null && f.max == null && !f.contains;
      if (empty) delete cf[id]; else cf[id] = f;
      return { ...o, columnFilters: cf };
    }),
    toggleGroup: (id) => mutate((o) => ({ ...o, collapsedGroups: { ...o.collapsedGroups, [id]: !o.collapsedGroups?.[id] } })),
  }), [mutate]);

  return { group, status, error, settings, handlers, setGroup, reset };
}
