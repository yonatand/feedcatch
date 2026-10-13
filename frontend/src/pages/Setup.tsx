import { useState } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { useAuthStatus, useLogin, useSetup } from '../api/hooks';
import { ErrorBanner, Notice } from '../components/ErrorBanner';
import { FormField } from '../components/FormField';
import { LoadingBlock } from '../components/Spinner';

export default function Setup() {
  const auth = useAuthStatus();
  const setup = useSetup();
  const login = useLogin();
  const nav = useNavigate();
  const [pw, setPw] = useState('');
  const [pw2, setPw2] = useState('');
  const [localErr, setLocalErr] = useState<string | null>(null);

  if (auth.isLoading) return <LoadingBlock />;
  if (auth.data && !auth.data.setup_required) return <Navigate to="/" replace />;

  return (
    <div className="auth-page">
      <form
        className="card auth-card"
        onSubmit={(e) => {
          e.preventDefault();
          if (pw.length < 8) {
            setLocalErr('Password must be at least 8 characters.');
            return;
          }
          if (pw !== pw2) {
            setLocalErr('Passwords do not match.');
            return;
          }
          setLocalErr(null);
          setup.mutate(pw, {
            onSuccess: () => {
              // Setup does not necessarily create a session; sign in with the new password.
              login.mutate(pw, {
                onSettled: () => {
                  setPw('');
                  setPw2('');
                  nav('/', { replace: true });
                },
              });
            },
          });
        }}
      >
        <h1>First-run setup</h1>
        <p className="muted">Choose an admin password for this instance. It is stored as a bcrypt hash.</p>
        <Notice kind="info">
          Keep this UI on a trusted network or behind a reverse proxy. It can send torrents to your qBittorrent.
        </Notice>
        <ErrorBanner error={auth.error} title="Cannot reach the server" />
        <FormField label="Password" help="At least 8 characters.">
          {(id) => (
            <input id={id} type="password" autoComplete="new-password" autoFocus required minLength={8} value={pw} onChange={(e) => setPw(e.target.value)} />
          )}
        </FormField>
        <FormField label="Repeat password">
          {(id) => (
            <input id={id} type="password" autoComplete="new-password" required value={pw2} onChange={(e) => setPw2(e.target.value)} />
          )}
        </FormField>
        <ErrorBanner error={localErr ?? setup.error} />
        <button type="submit" className="btn btn-primary btn-block" disabled={setup.isPending || login.isPending}>
          {setup.isPending || login.isPending ? 'Saving…' : 'Set password'}
        </button>
      </form>
    </div>
  );
}
