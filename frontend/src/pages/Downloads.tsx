import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useDownloads, useRefreshStatus, useRetryDownload, useRetryFailed, useSeriesList } from '../api/hooks';
import type { DownloadStatus } from '../api/types';
import { DownloadsTable } from '../components/DownloadsTable';
import { ErrorBanner, Notice } from '../components/ErrorBanner';
import { Pagination } from '../components/Pagination';
import { LoadingBlock, Spinner } from '../components/Spinner';
import { PageHeader } from '../components/Table';

const STATUSES: DownloadStatus[] = ['pending', 'submitted', 'failed', 'exists', 'path_mismatch'];
const LIMIT = 50;

export default function Downloads() {
  const [params, setParams] = useSearchParams();
  const status = STATUSES.find((s) => s === params.get('status'));
  const seriesId = params.get('series_id') ? Number(params.get('series_id')) : undefined;
  const offset = Math.max(0, Number(params.get('offset') ?? '0') || 0);
  const series = useSeriesList();
  const list = useDownloads({ status, series_id: seriesId, limit: LIMIT, offset });
  const retry = useRetryDownload();
  const retryFailed = useRetryFailed();
  const refresh = useRefreshStatus();
  const [message, setMessage] = useState<string | null>(null);

  const update = (patch: Record<string, string | undefined>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v === undefined || v === '') next.delete(k);
      else next.set(k, v);
    }
    if (!('offset' in patch)) next.delete('offset');
    setParams(next, { replace: true });
  };

  return (
    <>
      <PageHeader
        title="Downloads"
        subtitle="Torrents sent (or queued) to qBittorrent. qBittorrent owns them after submission; this app never pauses, moves or deletes torrents. Refreshes every 15 s."
        actions={
          <>
            <button
              type="button"
              className="btn"
              disabled={refresh.isPending}
              onClick={() => refresh.mutate(undefined, { onSuccess: (r) => setMessage(`Refreshed qBittorrent state for ${r.updated} download(s).`) })}
            >
              {refresh.isPending ? 'Refreshing…' : 'Refresh status from qBittorrent'}
            </button>
            <button
              type="button"
              className="btn"
              disabled={retryFailed.isPending}
              onClick={() => retryFailed.mutate(undefined, { onSuccess: (r) => setMessage(`Retried ${r.retried} failed download(s).`) })}
            >
              {retryFailed.isPending ? 'Retrying…' : 'Retry all failed'}
            </button>
          </>
        }
      />
      {message ? (
        <Notice kind="success">
          {message}{' '}
          <button type="button" className="btn btn-sm btn-ghost" onClick={() => setMessage(null)}>
            Dismiss
          </button>
        </Notice>
      ) : null}
      <ErrorBanner error={refresh.error ?? retryFailed.error ?? retry.error} onDismiss={() => { refresh.reset(); retryFailed.reset(); retry.reset(); }} />
      <div className="toolbar">
        <label className="sr-only" htmlFor="dl-status">
          Status
        </label>
        <select id="dl-status" value={status ?? ''} onChange={(e) => update({ status: e.target.value || undefined })}>
          <option value="">All statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s.replace('_', ' ')}
            </option>
          ))}
        </select>
        <label className="sr-only" htmlFor="dl-series">
          Series
        </label>
        <select id="dl-series" value={seriesId ?? ''} onChange={(e) => update({ series_id: e.target.value || undefined })}>
          <option value="">All series</option>
          {(series.data?.items ?? []).map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
        {list.isFetching && !list.isLoading ? <Spinner inline /> : null}
      </div>
      <ErrorBanner error={list.error} title="Could not load downloads" onRetry={() => void list.refetch()} />
      {list.isLoading ? (
        <LoadingBlock />
      ) : (
        <>
          <DownloadsTable
            items={list.data?.items ?? []}
            emptyText={status || seriesId !== undefined ? 'No downloads match these filters.' : 'Nothing has been sent to qBittorrent yet.'}
            renderActions={(d) =>
              d.status === 'failed' || d.status === 'pending' ? (
                <button
                  type="button"
                  className="btn btn-sm"
                  disabled={retry.isPending && retry.variables === d.id}
                  onClick={() => retry.mutate(d.id)}
                >
                  {retry.isPending && retry.variables === d.id ? 'Retrying…' : 'Retry now'}
                </button>
              ) : (
                <span className="muted small">—</span>
              )
            }
          />
          <Pagination total={list.data?.total ?? 0} limit={LIMIT} offset={offset} disabled={list.isFetching} onChange={(o) => update({ offset: o === 0 ? undefined : String(o) })} />
        </>
      )}
    </>
  );
}
