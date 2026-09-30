import { ReactNode, useEffect, useState } from 'react';
import { GoogleAuthProvider, onAuthStateChanged, signInWithPopup, User } from 'firebase/auth';
import { auth } from '../firebase';
import s from '../styles.module.css';

export function AuthGate({ children }: { children: (user: User) => ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();

  useEffect(
    () => onAuthStateChanged(auth, (u) => { setUser(u); setLoading(false); }, (e) => { setError(e.message); setLoading(false); }),
    []
  );

  if (loading) return <div className={s.center}>Loading user…</div>;
  if (!user)
    return (
      <div className={s.center}>
        <h1>Stock Scoring Dashboard</h1>
        <p>Sign in to see your ranked stocks.</p>
        <button className={s.primary} onClick={() => signInWithPopup(auth, new GoogleAuthProvider()).catch((e) => setError(e.message))}>
          Sign in with Google
        </button>
        {error && <p role="alert" className={s.error}>Sign-in failed: {error}</p>}
      </div>
    );
  return <>{children(user)}</>;
}
