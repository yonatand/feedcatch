import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useEntries, useFeeds } from '../api/hooks';
import type { EntryOutcome } from '../api/types';
import { EntriesTable } from '../components/EntriesTable';
import { ErrorBanner } from '../components/ErrorBanner';
import { Pagination } from '../components/Pagination';
import { LoadingBlock, Spinner } from '../components/Spinner';
import { PageHeader } from '../components/Table';

const OUTCOMES: EntryOutcome[] = ['unprocessed', 'accepted', 'rejected', 'no_match', 'historical', 'duplicate', 'searched'];
const LIMIT = 50;

function asOutcome(v: string | null): EntryOutcome | undefined {
  return OUTCOMES.find((o) => o === v);
}

export default function Releases() {
  const [params, setParams] = useSearchParams();
  const feedId = params.get('feed_id') ? Number(params.get('feed_id')) : undefined;
  const outcome = asOutcome(params.get('outcome'));
  const q = params.get('q') ?? '';
  const offset = Math.max(0, Number(params.get('offset') ?? '0') || 0);
  const [search, setSearch] = useState(q);
  const feeds = useFeeds();

  const update = (patch: Record<string, string | undefined>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v === undefined || v === '') next.delete(k);
      else next.set(k, v);
    }
    if (!('offset' in patch)) next.delete('offset');
    setParams(next, { replace: true });
  };

  // Debounce the search box into the URL.
  useEffect(() => {
    if (search === q) return undefined;
    const t = window.setTimeout(() => update({ q: search.trim() || undefined }), 350);
    return () => window.clearTimeout(t);
  }, [search]);

  const entries = useEntries({ feed_id: feedId, outcome, q: q || undefined, limit: LIMIT, offset });

  return (
    <>
      <PageHeader title="Releases" subtitle="Every feed entry seen, newest first, with the decision taken. Open one to see why." />
      <div className="toolbar">
        <label className="sr-only" htmlFor="rel-q">
          Search titles
        </label>
        <input id="rel-q" type="search" placeholder="Search titles…" value={search} onChange={(e) => setSearch(e.target.value)} className="grow" />
        <label className="sr-only" htmlFor="rel-feed">
          Feed
        </label>
        <select id="rel-feed" value={feedId ?? ''} onChange={(e) => update({ feed_id: e.target.value || undefined })}>
          <option value="">All feeds</option>
          {(feeds.data?.items ?? []).map((f) => (
            <option key={f.id} value={f.id}>
              {f.name}
            </option>
          ))}
        </select>
        <label className="sr-only" htmlFor="rel-outcome">
          Outcome
        </label>
        <select id="rel-outcome" value={outcome ?? ''} onChange={(e) => update({ outcome: e.target.value || undefined })}>
          <option value="">All outcomes</option>
          {OUTCOMES.map((o) => (
            <option key={o} value={o}>
              {o.replace('_', ' ')}
            </option>
          ))}
        </select>
        {entries.isFetching && !entries.isLoading ? <Spinner inline /> : null}
      </div>
      <ErrorBanner error={entries.error} title="Could not load releases" onRetry={() => void entries.refetch()} />
      {entries.isLoading ? (
        <LoadingBlock />
      ) : (
        <>
          <EntriesTable
            items={entries.data?.items ?? []}
            emptyText={q || feedId !== undefined || outcome ? 'No releases match these filters.' : 'No releases yet. Poll a feed from the Feeds page.'}
          />
          <Pagination
            total={entries.data?.total ?? 0}
            limit={LIMIT}
            offset={offset}
            disabled={entries.isFetching}
            onChange={(o) => update({ offset: o === 0 ? undefined : String(o) })}
          />
        </>
      )}
    </>
  );
}
