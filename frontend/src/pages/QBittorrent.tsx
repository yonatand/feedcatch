import { useEffect, useState } from 'react';
import { useQbit, useSaveQbit, useTestQbit } from '../api/hooks';
import type { ConfigSource, QbitConfig, QbitConfigIn, QbitTestResult } from '../api/types';
import { ErrorBanner, Notice } from '../components/ErrorBanner';
import { CheckField, FormField } from '../components/FormField';
import { NumberInput } from '../components/NumberInput';
import { LoadingBlock } from '../components/Spinner';
import { Badge, BoolMark, StatusBadge } from '../components/StatusBadge';
import { Card, PageHeader } from '../components/Table';
import { TimeAgo } from '../components/TimeAgo';

type FormState = {
  url: string;
  username: string;
  password: string; // new password typed by the user; '' = leave unchanged
  clearPassword: boolean;
  category: string;
  timeout_seconds: number | null;
  start_immediately: boolean;
  poll_status: boolean;
};

function fromConfig(c: QbitConfig): FormState {
  return {
    url: c.url,
    username: c.username,
    password: '',
    clearPassword: false,
    category: c.category ?? '',
    timeout_seconds: c.timeout_seconds,
    start_immediately: c.start_immediately,
    poll_status: c.poll_status,
  };
}

function toIn(f: FormState): QbitConfigIn {
  const body: QbitConfigIn = {
    url: f.url.trim(),
    username: f.username,
    category: f.category.trim() === '' ? null : f.category.trim(),
    timeout_seconds: f.timeout_seconds ?? 15,
    start_immediately: f.start_immediately,
    poll_status: f.poll_status,
  };
  if (f.clearPassword) body.password = '';
  else if (f.password !== '') body.password = f.password;
  return body;
}

function EnvBadge({ src }: { src: ConfigSource | undefined }) {
  return src === 'env' ? (
    <Badge tone="purple" title="Set by an environment variable; edit it in the container environment">
      env
    </Badge>
  ) : null;
}

function QbitTestView({ r }: { r: QbitTestResult }) {
  return (
    <div className="stack">
      {r.ok ? (
        <Notice kind="success">
          Connected <TimeAgo iso={r.at} />.
        </Notice>
      ) : (
        <ErrorBanner error={r.error ?? 'Connection failed'} title="Connection failed" />
      )}
      <dl className="kv">
        <div className="kv-row">
          <dt>qBittorrent version</dt>
          <dd>{r.version ?? '—'}</dd>
        </div>
        <div className="kv-row">
          <dt>Web API version</dt>
          <dd>{r.api_version ?? '—'}</dd>
        </div>
        <div className="kv-row">
          <dt>Automatic Torrent Management default</dt>
          <dd>
            {r.auto_tmm_enabled === null ? (
              <span className="muted">unknown</span>
            ) : r.auto_tmm_enabled ? (
              <Badge tone="orange">enabled</Badge>
            ) : (
              <Badge tone="green">disabled</Badge>
            )}
          </dd>
        </div>
        <div className="kv-row">
          <dt>Default save path</dt>
          <dd>{r.default_save_path ? <code className="path-sm">{r.default_save_path}</code> : '—'}</dd>
        </div>
        <div className="kv-row">
          <dt>Category exists</dt>
          <dd>
            <BoolMark value={r.category_exists} />
          </dd>
        </div>
      </dl>
      {r.auto_tmm_enabled ? (
        <Notice kind="warning">
          Automatic Torrent Management is the default in qBittorrent. This app always adds torrents with <code>autoTMM=false</code> and an explicit{' '}
          <code>savepath</code>, but a category with its own save path or later manual changes in qBittorrent can still move them. Check the Downloads page
          for path mismatches.
        </Notice>
      ) : null}
      {r.warnings.length > 0 ? (
        <Notice kind="warning">
          <ul className="plain-list">
            {r.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </Notice>
      ) : null}
    </div>
  );
}

export default function QBittorrent() {
  const cfg = useQbit();
  const save = useSaveQbit();
  const test = useTestQbit();
  const [f, setF] = useState<FormState | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (cfg.data && f === null) setF(fromConfig(cfg.data));
  }, [cfg.data, f]);

  if (cfg.isLoading) return <LoadingBlock />;
  if (!cfg.data || !f) return <ErrorBanner error={cfg.error ?? 'No data'} title="Could not load qBittorrent settings" onRetry={() => void cfg.refetch()} />;
  const c = cfg.data;
  const src = (k: string) => c.sources[k];
  const isEnv = (k: string) => src(k) === 'env';
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => {
    setSaved(false);
    setF({ ...f, [k]: v });
  };
  const shownTest = test.data ?? c.last_test;

  return (
    <>
      <PageHeader
        title="qBittorrent"
        subtitle="Connection to your existing qBittorrent-nox Web API. Torrents are added with an explicit save path and are then owned by qBittorrent."
      />
      <div className="grid-2">
        <Card title="Connection">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate(toIn(f), {
                onSuccess: (data) => {
                  setF(fromConfig(data));
                  setSaved(true);
                },
              });
            }}
          >
            <FormField label="Web UI URL" badge={<EnvBadge src={src('url')} />} help="e.g. http://host.docker.internal:8080 (reachable from this container).">
              {(id) => (
                <input
                  id={id}
                  type="url"
                  inputMode="url"
                  autoCapitalize="off"
                  autoCorrect="off"
                  spellCheck={false}
                  required
                  value={f.url} disabled={isEnv('url')} onChange={(e) => set('url', e.target.value)} placeholder="http://host.docker.internal:8080" />
              )}
            </FormField>
            <FormField label="Username" badge={<EnvBadge src={src('username')} />}>
              {(id) => (
                <input id={id} type="text" autoComplete="username" autoCapitalize="off" autoCorrect="off" spellCheck={false} value={f.username} disabled={isEnv('username')} onChange={(e) => set('username', e.target.value)} />
              )}
            </FormField>
            <FormField
              label="Password"
              badge={
                <>
                  <EnvBadge src={src('password')} /> {c.password_set ? <Badge tone="green">password set</Badge> : <Badge>no password</Badge>}
                </>
              }
              help={
                isEnv('password')
                  ? 'Controlled by QBIT_PASSWORD.'
                  : c.password_set
                    ? 'Leave empty to keep the stored password. It is stored encrypted and never shown again.'
                    : 'Stored encrypted; never returned to the browser.'
              }
            >
              {(id) => (
                <input
                  id={id}
                  type="password"
                  autoComplete="new-password"
                  value={f.password}
                  disabled={isEnv('password') || f.clearPassword}
                  placeholder={c.password_set ? '•••••••• (unchanged)' : ''}
                  onChange={(e) => set('password', e.target.value)}
                />
              )}
            </FormField>
            {c.password_set && !isEnv('password') ? (
              <CheckField
                label="Clear the stored password on save"
                checked={f.clearPassword}
                onChange={(b) => setF({ ...f, clearPassword: b, password: b ? '' : f.password })}
              />
            ) : null}
            <FormField label="Category" badge={<EnvBadge src={src('category')} />} help="Optional, e.g. anime. Avoid categories with their own save path.">
              {(id) => <input id={id} type="text" autoCapitalize="off" autoCorrect="off" value={f.category} disabled={isEnv('category')} onChange={(e) => set('category', e.target.value)} />}
            </FormField>
            <FormField label="Timeout (seconds)" badge={<EnvBadge src={src('timeout_seconds')} />}>
              {(id) => (
                <NumberInput id={id} min={1} max={300} value={f.timeout_seconds} disabled={isEnv('timeout_seconds')} onChange={(n) => set('timeout_seconds', n)} />
              )}
            </FormField>
            <CheckField
              label="Start torrents immediately"
              checked={f.start_immediately}
              disabled={isEnv('start_immediately')}
              badge={<EnvBadge src={src('start_immediately')} />}
              onChange={(b) => set('start_immediately', b)}
              help="When off, torrents are added paused (stopped)."
            />
            <CheckField
              label="Poll torrent state and progress"
              checked={f.poll_status}
              disabled={isEnv('poll_status')}
              badge={<EnvBadge src={src('poll_status')} />}
              onChange={(b) => set('poll_status', b)}
              help="Read-only status polling; never pauses, moves or deletes torrents."
            />
            <ErrorBanner error={save.error} title="Could not save" />
            {saved ? <Notice kind="success">Saved.</Notice> : null}
            <div className="form-actions">
              <button type="submit" className="btn btn-primary" disabled={save.isPending}>
                {save.isPending ? 'Saving…' : 'Save'}
              </button>
              <button type="button" className="btn" disabled={test.isPending || f.url.trim() === ''} onClick={() => test.mutate(toIn(f))}>
                {test.isPending ? 'Testing…' : 'Test connection (unsaved values)'}
              </button>
            </div>
            <p className="small muted">The test uses the values in this form without saving; an empty password field uses the stored password.</p>
          </form>
        </Card>
        <Card
          title="Connection test"
          actions={shownTest ? <StatusBadge status={shownTest.ok ? 'ok' : 'failed'} /> : null}
        >
          <ErrorBanner error={test.error} title="Test request failed" />
          {shownTest ? (
            <>
              {!test.data ? <p className="small muted">Last stored test result.</p> : null}
              <QbitTestView r={shownTest} />
            </>
          ) : (
            <p className="muted">Not tested yet. Fill in the connection and press “Test connection”.</p>
          )}
        </Card>
      </div>
    </>
  );
}
