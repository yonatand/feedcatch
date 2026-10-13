import { useState } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { ApiError } from '../api/client';
import { useAuthStatus, useLogin } from '../api/hooks';
import { ErrorBanner } from '../components/ErrorBanner';
import { FormField } from '../components/FormField';
import { LoadingBlock } from '../components/Spinner';

function fromState(state: unknown): string {
  if (typeof state === 'object' && state !== null && 'from' in state) {
    const f = (state as { from: unknown }).from;
    if (typeof f === 'string' && f.startsWith('/') && !f.startsWith('//') && !f.includes('\\') && f !== '/login') return f;
  }
  return '/';
}

export default function Login() {
  const auth = useAuthStatus();
  const login = useLogin();
  const nav = useNavigate();
  const loc = useLocation();
  const [password, setPassword] = useState('');

  if (auth.isLoading) return <LoadingBlock />;
  if (auth.data?.auth_mode === 'disabled' || auth.data?.authenticated) return <Navigate to={fromState(loc.state)} replace />;
  if (auth.data?.setup_required) return <Navigate to="/setup" replace />;

  const err =
    login.error instanceof ApiError && login.error.status === 401
      ? 'Wrong password.'
      : login.error instanceof ApiError && login.error.status === 429
        ? 'Too many failed attempts. Wait a minute and try again.'
        : login.error;

  return (
    <div className="auth-page">
      <form
        className="card auth-card"
        onSubmit={(e) => {
          e.preventDefault();
          login.mutate(password, {
            onSuccess: () => {
              setPassword('');
              nav(fromState(loc.state), { replace: true });
            },
          });
        }}
      >
        <h1>feedcatch</h1>
        <p className="muted">Sign in to manage feeds, rules and qBittorrent submissions.</p>
        <ErrorBanner error={auth.error} title="Cannot reach the server" />
        <FormField label="Password">
          {(id) => (
            <input
              id={id}
              type="password"
              autoComplete="current-password"
              autoFocus
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          )}
        </FormField>
        <ErrorBanner error={err} />
        <button type="submit" className="btn btn-primary btn-block" disabled={login.isPending || password === ''}>
          {login.isPending ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  );
}
