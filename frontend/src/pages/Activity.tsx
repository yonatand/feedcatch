import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useActivity } from '../api/hooks';
import type { ActivityEvent } from '../api/types';
import { ErrorBanner } from '../components/ErrorBanner';
import { Pagination } from '../components/Pagination';
import { LoadingBlock, Spinner } from '../components/Spinner';
import { StatusBadge } from '../components/StatusBadge';
import { EmptyRow, PageHeader, TableWrap } from '../components/Table';
import { TimeAgo } from '../components/TimeAgo';

const LIMIT = 50;
const LEVELS = ['info', 'warning', 'error'] as const;

function Details({ ev }: { ev: ActivityEvent }) {
  if (!ev.details || Object.keys(ev.details).length === 0) return null;
  return (
    <details className="json-details">
      <summary className="small">details</summary>
      <pre className="json">{JSON.stringify(ev.details, null, 2)}</pre>
    </details>
  );
}

export default function Activity() {
  const [params, setParams] = useSearchParams();
  const level = LEVELS.find((l) => l === params.get('level'));
  const eventType = params.get('event_type') ?? '';
  const offset = Math.max(0, Number(params.get('offset') ?? '0') || 0);
  const [typeText, setTypeText] = useState(eventType);

  const update = (patch: Record<string, string | undefined>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v === undefined || v === '') next.delete(k);
      else next.set(k, v);
    }
    if (!('offset' in patch)) next.delete('offset');
    setParams(next, { replace: true });
  };

  useEffect(() => {
    if (typeText === eventType) return undefined;
    const t = window.setTimeout(() => update({ event_type: typeText.trim() || undefined }), 350);
    return () => window.clearTimeout(t);
  }, [typeText]);

  const list = useActivity({ level, event_type: eventType || undefined, limit: LIMIT, offset });
  const items = list.data?.items ?? [];

  return (
    <>
      <PageHeader title="Activity" subtitle="History of polls, matches, submissions and errors, newest first." />
      <div className="toolbar">
        <label className="sr-only" htmlFor="act-level">
          Level
        </label>
        <select id="act-level" value={level ?? ''} onChange={(e) => update({ level: e.target.value || undefined })}>
          <option value="">All levels</option>
          {LEVELS.map((l) => (
            <option key={l} value={l}>
              {l}
            </option>
          ))}
        </select>
        <label className="sr-only" htmlFor="act-type">
          Event type
        </label>
        <input
          id="act-type"
          type="search"
          placeholder="Event type (exact), e.g. feed_poll"
          value={typeText}
          onChange={(e) => setTypeText(e.target.value)}
        />
        {list.isFetching && !list.isLoading ? <Spinner inline /> : null}
      </div>
      <ErrorBanner error={list.error} title="Could not load activity" onRetry={() => void list.refetch()} />
      {list.isLoading ? (
        <LoadingBlock />
      ) : (
        <>
          <TableWrap>
            <table className="table">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Level</th>
                  <th>Type</th>
                  <th>Message</th>
                </tr>
              </thead>
              <tbody>
                {items.length === 0 ? <EmptyRow colSpan={4}>No activity{level || eventType ? ' matches these filters' : ' yet'}.</EmptyRow> : null}
                {items.map((ev) => (
                  <tr key={ev.id}>
                    <td>
                      <TimeAgo iso={ev.ts} />
                    </td>
                    <td>
                      <StatusBadge status={ev.level} />
                    </td>
                    <td className="nowrap">
                      <button type="button" className="link-btn mono small" onClick={() => setTypeText(ev.event_type)} title="Filter by this type">
                        {ev.event_type}
                      </button>
                    </td>
                    <td className="title-cell">
                      <div className="break">{ev.message}</div>
                      <div className="small">
                        {ev.entry_id !== null ? <Link to={`/releases/${ev.entry_id}`}>release #{ev.entry_id}</Link> : null}
                        {ev.entry_id !== null && ev.download_id !== null ? ' · ' : null}
                        {ev.download_id !== null ? <span className="muted">download #{ev.download_id}</span> : null}
                      </div>
                      <Details ev={ev} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
          <Pagination total={list.data?.total ?? 0} limit={LIMIT} offset={offset} disabled={list.isFetching} onChange={(o) => update({ offset: o === 0 ? undefined : String(o) })} />
        </>
      )}
    </>
  );
}
