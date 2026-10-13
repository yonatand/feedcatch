import { useState } from 'react';
import { Link } from 'react-router-dom';
import { errorMessage } from '../api/client';
import { useDeleteFeed, useFeedPreview, useFeeds, usePollFeed, useSaveFeed, useTestFeedUrl } from '../api/hooks';
import type { FeedIn, FeedSource, FeedTestResult, PollResult } from '../api/types';
import { ConfirmInline } from '../components/ConfirmInline';
import { Drawer } from '../components/Drawer';
import { ErrorBanner, Notice } from '../components/ErrorBanner';
import { FeedPreviewList } from '../components/FeedPreviewList';
import { CheckField, FormField } from '../components/FormField';
import { NumberInput } from '../components/NumberInput';
import { LoadingBlock, Spinner } from '../components/Spinner';
import { StatusBadge } from '../components/StatusBadge';
import { Card, EmptyRow, PageHeader, TableWrap } from '../components/Table';
import { TimeAgo } from '../components/TimeAgo';

const DEFAULT_FEED: FeedIn = {
  name: 'AnimeTosho',
  url: 'https://feed.animetosho.net/rss2',
  enabled: true,
  poll_interval_minutes: 15,
  backfill_mode: 'skip',
};

function toIn(f: FeedSource): FeedIn {
  return {
    name: f.name,
    url: f.url,
    enabled: f.enabled,
    poll_interval_minutes: f.poll_interval_minutes,
    backfill_mode: f.backfill_mode,
  };
}

function TestResultView({ r }: { r: FeedTestResult }) {
  return (
    <div className="stack">
      {r.ok ? (
        <Notice kind="success">
          Feed OK{r.feed_title ? <> — “{r.feed_title}”</> : null}: {r.entry_count} entries.
        </Notice>
      ) : (
        <ErrorBanner error={r.error ?? 'Feed test failed'} title="Feed test failed" />
      )}
      {r.sample.length > 0 ? (
        <>
          <div className="small muted">Sample (first {r.sample.length}, not saved):</div>
          <FeedPreviewList items={r.sample} />
        </>
      ) : null}
    </div>
  );
}

function PollResultView({ r }: { r: PollResult }) {
  const cells: [string, number][] = [
    ['fetched', r.fetched],
    ['new', r.new_entries],
    ['historical', r.historical],
    ['accepted', r.accepted],
    ['duplicate', r.duplicate],
    ['rejected', r.rejected],
    ['no match', r.no_match],
    ['sent to qBit', r.submitted],
  ];
  return (
    <div className="stack">
      <div className="mini-stats">
        {cells.map(([k, v]) => (
          <div key={k} className="mini-stat">
            <div className="mini-stat-value">{v}</div>
            <div className="mini-stat-label">{k}</div>
          </div>
        ))}
      </div>
      {r.errors.length > 0 ? (
        <ErrorBanner error={r.errors.join('\n')} title={`${r.errors.length} error(s)`} />
      ) : null}
      {r.new_entries > 0 ? (
        <p className="small">
          <Link to="/releases">See the new releases →</Link>
        </p>
      ) : null}
    </div>
  );
}

function FeedForm({ initial, onDone }: { initial: FeedSource | null; onDone: () => void }) {
  const [v, setV] = useState<FeedIn>(initial ? toIn(initial) : DEFAULT_FEED);
  const save = useSaveFeed();
  const test = useTestFeedUrl();
  const set = <K extends keyof FeedIn>(k: K, val: FeedIn[K]) => setV({ ...v, [k]: val });
  const intervalBad = v.poll_interval_minutes < 5 || v.poll_interval_minutes > 1440;

  return (
    <Card title={initial ? `Edit feed: ${initial.name}` : 'Add feed'}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate({ id: initial?.id, body: { ...v, name: v.name.trim(), url: v.url.trim() } }, { onSuccess: onDone });
        }}
      >
        <div className="form-grid">
          <FormField label="Name">
            {(id) => <input id={id} type="text" required value={v.name} onChange={(e) => set('name', e.target.value)} />}
          </FormField>
          <FormField label="RSS2 / Atom URL" help="http(s) only. Private/LAN hosts are rejected unless allowed in Settings." className="span-2">
            {(id) => (
              <input id={id} type="url" required value={v.url} onChange={(e) => set('url', e.target.value)} placeholder="https://feed.animetosho.net/rss2" />
            )}
          </FormField>
          <FormField label="Poll interval (minutes)" error={intervalBad ? 'Must be between 5 and 1440.' : null} help="5–1440, default 15.">
            {(id) => <NumberInput id={id} min={5} max={1440} value={v.poll_interval_minutes} onChange={(n) => set('poll_interval_minutes', n ?? 0)} required />}
          </FormField>
          <FormField
            label="First poll (backfill)"
            help={
              v.backfill_mode === 'skip'
                ? 'Entries already in the feed on the first poll are stored as “historical” and never auto-grabbed. Recommended.'
                : 'Entries already in the feed on the first poll are matched and may be sent to qBittorrent.'
            }
          >
            {(id) => (
              <select id={id} value={v.backfill_mode} onChange={(e) => set('backfill_mode', e.target.value === 'process' ? 'process' : 'skip')}>
                <option value="skip">Skip existing entries (historical)</option>
                <option value="process">Process existing entries</option>
              </select>
            )}
          </FormField>
          <CheckField label="Enabled (polled on schedule)" checked={v.enabled} onChange={(b) => set('enabled', b)} />
        </div>
        {initial && initial.initial_poll_done && v.backfill_mode !== initial.backfill_mode ? (
          <Notice kind="info">This feed already completed its first poll; the backfill setting only affects the first poll.</Notice>
        ) : null}
        <ErrorBanner error={save.error} title="Could not save feed" />
        <div className="form-actions">
          <button type="submit" className="btn btn-primary" disabled={save.isPending || intervalBad}>
            {save.isPending ? 'Saving…' : initial ? 'Save' : 'Add feed'}
          </button>
          <button type="button" className="btn" disabled={test.isPending || !v.url.trim()} onClick={() => test.mutate(v.url.trim())}>
            {test.isPending ? 'Testing…' : 'Test URL'}
          </button>
          <button type="button" className="btn btn-ghost" onClick={onDone}>
            Cancel
          </button>
        </div>
      </form>
      <ErrorBanner error={test.error} title="Test request failed" />
      {test.data ? <TestResultView r={test.data} /> : null}
    </Card>
  );
}

function PreviewDrawer({ feed, onClose }: { feed: FeedSource; onClose: () => void }) {
  const q = useFeedPreview(feed.id, 50);
  return (
    <Drawer title={`Live preview: ${feed.name}`} onClose={onClose} wide>
      <p className="small muted">
        Fetched live from the feed now; nothing is stored or sent. Use it to check how titles are parsed.
      </p>
      {q.isLoading ? <LoadingBlock label="Fetching feed…" /> : null}
      <ErrorBanner error={q.error} title="Preview failed" onRetry={() => void q.refetch()} />
      {q.data ? <FeedPreviewList items={q.data.items} /> : null}
    </Drawer>
  );
}

type RowResult = { kind: 'test'; data: FeedTestResult } | { kind: 'poll'; data: PollResult } | { kind: 'error'; message: string };

export default function Feeds() {
  const feeds = useFeeds();
  const save = useSaveFeed();
  const del = useDeleteFeed();
  const poll = usePollFeed();
  const test = useTestFeedUrl();
  const [editing, setEditing] = useState<FeedSource | 'new' | null>(null);
  const [preview, setPreview] = useState<FeedSource | null>(null);
  const [results, setResults] = useState<Record<number, RowResult>>({});
  const [busy, setBusy] = useState<Record<number, string>>({});

  const setResult = (id: number, r: RowResult) => setResults((m) => ({ ...m, [id]: r }));
  const setBusyFor = (id: number, what: string | null) =>
    setBusy((m) => {
      const n = { ...m };
      if (what) n[id] = what;
      else delete n[id];
      return n;
    });

  const items = feeds.data?.items ?? [];

  return (
    <>
      <PageHeader
        title="Feeds"
        subtitle="RSS2/Atom sources polled on a schedule. Only magnet and .torrent links are ever sent to qBittorrent; NZB links are ignored."
        actions={
          editing === null ? (
            <button type="button" className="btn btn-primary" onClick={() => setEditing('new')}>
              Add feed
            </button>
          ) : null
        }
      />
      {editing !== null ? (
        <FeedForm key={editing === 'new' ? 'new' : editing.id} initial={editing === 'new' ? null : editing} onDone={() => setEditing(null)} />
      ) : null}
      <ErrorBanner error={feeds.error} title="Could not load feeds" onRetry={() => void feeds.refetch()} />
      <ErrorBanner error={save.error ?? del.error} onDismiss={() => { save.reset(); del.reset(); }} />
      {feeds.isLoading ? (
        <LoadingBlock />
      ) : (
        <TableWrap>
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Status</th>
                <th>Last check</th>
                <th className="num">Interval</th>
                <th className="num">Entries</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 ? (
                <EmptyRow colSpan={6}>No feeds configured. Add the AnimeTosho RSS feed to get started.</EmptyRow>
              ) : null}
              {items.map((f) => {
                const r = results[f.id];
                const b = busy[f.id];
                return (
                  <FeedRow key={f.id}>
                    <tr>
                      <td className="title-cell">
                        <strong>{f.name}</strong>
                        <div className="small muted break">{f.url}</div>
                        <div className="small muted">
                          backfill: {f.backfill_mode === 'skip' ? 'skip existing' : 'process existing'}
                          {f.initial_poll_done ? '' : ' · first poll pending'}
                        </div>
                      </td>
                      <td>
                        {f.enabled ? <StatusBadge status={f.last_status} /> : <StatusBadge status="disabled" />}
                        {f.consecutive_failures > 0 ? <div className="small err-text">{f.consecutive_failures} consecutive failures</div> : null}
                        {f.last_error ? (
                          <div className="small err-text" title={f.last_error}>
                            {f.last_error}
                          </div>
                        ) : null}
                      </td>
                      <td>
                        <TimeAgo iso={f.last_checked_at} fallback="never" />
                        <div className="small muted">
                          last ok <TimeAgo iso={f.last_success_at} fallback="never" />
                        </div>
                      </td>
                      <td className="num nowrap">{f.poll_interval_minutes} min</td>
                      <td className="num">{f.entry_count}</td>
                      <td>
                        <div className="actions">
                          <button
                            type="button"
                            className="btn btn-sm"
                            disabled={!!b}
                            onClick={() => {
                              setBusyFor(f.id, 'test');
                              test.mutate(f.url, {
                                onSuccess: (d) => setResult(f.id, { kind: 'test', data: d }),
                                onError: (e) => setResult(f.id, { kind: 'error', message: errorMessage(e) }),
                                onSettled: () => setBusyFor(f.id, null),
                              });
                            }}
                          >
                            {b === 'test' ? 'Testing…' : 'Test URL'}
                          </button>
                          <button type="button" className="btn btn-sm" onClick={() => setPreview(f)}>
                            Preview entries
                          </button>
                          <button
                            type="button"
                            className="btn btn-sm"
                            disabled={!!b}
                            onClick={() => {
                              setBusyFor(f.id, 'poll');
                              poll.mutate(f.id, {
                                onSuccess: (d) => setResult(f.id, { kind: 'poll', data: d }),
                                onError: (e) => setResult(f.id, { kind: 'error', message: errorMessage(e) }),
                                onSettled: () => setBusyFor(f.id, null),
                              });
                            }}
                          >
                            {b === 'poll' ? 'Polling…' : 'Poll now'}
                          </button>
                          <button
                            type="button"
                            className="btn btn-sm"
                            disabled={save.isPending}
                            onClick={() => save.mutate({ id: f.id, body: { ...toIn(f), enabled: !f.enabled } })}
                          >
                            {f.enabled ? 'Disable' : 'Enable'}
                          </button>
                          <button type="button" className="btn btn-sm" onClick={() => setEditing(f)}>
                            Edit
                          </button>
                          <ConfirmInline
                            label="Delete"
                            confirmLabel="Delete feed"
                            message={`Delete “${f.name}”?`}
                            pending={del.isPending && del.variables === f.id}
                            onConfirm={() => del.mutate(f.id)}
                          />
                        </div>
                      </td>
                    </tr>
                    {b ? (
                      <tr className="detail-row">
                        <td colSpan={6}>
                          <Spinner label={b === 'poll' ? 'Polling feed (synchronous)…' : 'Testing feed URL…'} />
                        </td>
                      </tr>
                    ) : r ? (
                      <tr className="detail-row">
                        <td colSpan={6}>
                          <div className="detail-head">
                            <strong className="small">{r.kind === 'poll' ? 'Poll result' : r.kind === 'test' ? 'Test result' : 'Error'}</strong>
                            <button
                              type="button"
                              className="btn btn-sm btn-ghost"
                              onClick={() =>
                                setResults((m) => {
                                  const n = { ...m };
                                  delete n[f.id];
                                  return n;
                                })
                              }
                            >
                              Hide
                            </button>
                          </div>
                          {r.kind === 'poll' ? <PollResultView r={r.data} /> : r.kind === 'test' ? <TestResultView r={r.data} /> : <ErrorBanner error={r.message} />}
                        </td>
                      </tr>
                    ) : null}
                  </FeedRow>
                );
              })}
            </tbody>
          </table>
        </TableWrap>
      )}
      {preview ? <PreviewDrawer feed={preview} onClose={() => setPreview(null)} /> : null}
    </>
  );
}

function FeedRow({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
