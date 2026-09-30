import { useCallback, useEffect, useMemo, useState } from 'react';
import { signOut, User } from 'firebase/auth';
import { auth } from './firebase';
import { AuthGate } from './auth/AuthGate';
import { DataError, loadLatestFile } from './data/loadLatestFile';
import { rank, scoreRow } from './scoring/score';
import { useUserSettings } from './settings/useUserSettings';
import { SymbolGroupBar } from './components/SymbolGroupBar';
import { ScoreTable } from './components/ScoreTable';
import { config, Row } from './types';
import s from './styles.module.css';

type DataState =
  | { status: 'loading' }
  | { status: 'ready'; date: string; rows: Row[] }
  | { status: 'error'; kind: string; message: string };

function Dashboard({ user }: { user: User }) {
  const st = useUserSettings(user.uid);
  const [data, setData] = useState<DataState>({ status: 'loading' });
  const [picked, setPicked] = useState<string>();
  const [dates, setDates] = useState<string[]>([]);

  const load = useCallback(() => {
    setData({ status: 'loading' });
    loadLatestFile(config, picked)
      .then((d) => { setDates(d.dates); setData({ status: 'ready', date: d.date, rows: d.rows }); })
      .catch((e) => setData({ status: 'error', kind: e instanceof DataError ? e.kind : 'fetch', message: e.message }));
  }, [picked]);
  useEffect(load, [load]);

  const { groupWeights, columnWeights, columnConditions } = st.settings;
  const scored = useMemo(() => {
    if (data.status !== 'ready' || !st.group) return [];
    return data.rows
      .filter((r) => r.groups.includes(st.group!))
      .map((r) => scoreRow(r, config.groups, { groupWeights, columnWeights, columnConditions }))
      .sort(rank);
  }, [data, st.group, groupWeights, columnWeights, columnConditions]);

  let body;
  if (data.status === 'loading') body = <div className={s.center}>Loading latest data file…</div>;
  else if (data.status === 'error')
    body = (
      <div className={s.center} role="alert">
        <p className={s.error}>{data.kind === 'no-files' ? 'No data files found.' : data.kind === 'parse' ? 'Data file could not be parsed.' : 'Data file could not be loaded.'}</p>
        <p className={s.muted}>{data.message}</p>
        <button className={s.primary} onClick={load}>Try again</button>
      </div>
    );
  else if (st.status === 'loading' || !st.group) body = <div className={s.center}>Loading settings…</div>;
  else if (st.status === 'error') body = <div className={s.center} role="alert"><p className={s.error}>Settings could not be read.</p><p className={s.muted}>{st.error}</p></div>;
  else body = <ScoreTable rows={scored} settings={st.settings} handlers={st.handlers} />;

  return (
    <div className={s.app}>
      <header className={s.header}>
        <h1>Stock Scoring Dashboard</h1>
        {data.status === 'ready' && <span className={s.muted}>Data as of {data.date}</span>}
        <span className={s.spacer} />
        {user.photoURL && <img className={s.avatar} src={user.photoURL} alt="" referrerPolicy="no-referrer" />}
        <span>{user.email}</span>
        <button onClick={() => signOut(auth)}>Sign out</button>
      </header>
      <div className={s.toolbar}>
        <SymbolGroupBar active={st.group} onSelect={st.setGroup} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            Data date
            <input type="date" disabled={!dates.length} min={dates[dates.length - 1]} max={dates[0]}
              value={picked ?? (data.status === 'ready' ? data.date : '')}
              onChange={(e) => e.target.value && setPicked(e.target.value)} />
          </label>
          <button onClick={st.reset} disabled={st.status !== 'ready'}>Reset to defaults</button>
        </div>
      </div>
      {st.error && st.status === 'ready' && <p role="alert" className={s.error}>{st.error}</p>}
      <main className={s.main}>{body}</main>
    </div>
  );
}

export default function App() {
  return <AuthGate>{(user) => <Dashboard user={user} />}</AuthGate>;
}
