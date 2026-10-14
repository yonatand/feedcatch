import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ApiError } from '../api/client';
import { useSearchAllWanted, useWanted } from '../api/hooks';
import type { CalendarItem, SearchAllSeason } from '../api/types';
import { ConfirmInline } from '../components/ConfirmInline';
import { Cover } from '../components/Cover';
import { ErrorBanner, Notice } from '../components/ErrorBanner';
import { Pagination } from '../components/Pagination';
import { SearchDrawer } from '../components/SearchDrawer';
import { MobileActionBar } from '../components/MobileActionBar';
import { LoadingBlock, Spinner } from '../components/Spinner';
import { StatusBadge } from '../components/StatusBadge';
import { EmptyRow, PageHeader, TableWrap } from '../components/Table';
import { TimeAgo } from '../components/TimeAgo';
import { formatAirDate, seasonEpisode } from '../lib/format';
import { useIsMobile } from '../lib/useMedia';

const LIMIT = 50;

function SearchAllSummary({ seasons }: { seasons: SearchAllSeason[] }) {
  const grabbed = seasons.reduce((n, s) => n + s.grabbed, 0);
  return (
    <div className="stack">
      <Notice kind={grabbed > 0 ? 'success' : 'info'}>
        Searched {seasons.length} season{seasons.length === 1 ? '' : 's'}; sent {grabbed} release{grabbed === 1 ? '' : 's'} to qBittorrent.{' '}
        {grabbed > 0 ? <Link to="/downloads">View downloads →</Link> : null}
      </Notice>
      {seasons.length > 0 ? (
        <TableWrap>
          <table className="table table-compact">
            <thead>
              <tr>
                <th>Season</th>
                <th className="num">Grabbed</th>
                <th className="num">Skipped</th>
                <th>Errors</th>
              </tr>
            </thead>
            <tbody>
              {seasons.map((s) => (
                <tr key={s.season_id}>
                  <td className="title-cell cell-main">
                    {s.series_name} <span className="mono small">{seasonEpisode(s.season_number, null)}</span>
                  </td>
                  <td className="num" data-label="Grabbed">
                    {s.grabbed}
                  </td>
                  <td className="num" data-label="Skipped">
                    {s.skipped}
                  </td>
                  <td className="break cell-grow" data-label="Errors">{s.errors.length ? <span className="err-text small">{s.errors.join('; ')}</span> : <span className="muted">—</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      ) : null}
    </div>
  );
}

/** Mobile card list: cover + series/episode on top, air date and status, a full-width Search button. */
function WantedCards({ items, onSearch }: { items: CalendarItem[]; onSearch: (it: CalendarItem) => void }) {
  if (items.length === 0) {
    return (
      <p className="mcards-empty muted">
        Nothing wanted. Missing episodes show up here once monitored seasons are linked to metadata and an aired episode has no download.
      </p>
    );
  }
  return (
    <ul className="mcards wanted-cards">
      {items.map((it) => (
        <li key={`${it.season_id}-${it.episode_number}`} className="mcard">
          <div className="mcard-head">
            <Cover url={it.cover_url} alt={it.series_name} size="xs" />
            <div className="mcard-head-main">
              <div className="mcard-title">
                <Link to={`/series/${it.series_id}`}>{it.series_name}</Link>{' '}
                <span className="mono small">{seasonEpisode(it.season_number, it.episode_number)}</span>
              </div>
              <div className="small muted break">{it.title ?? `Episode ${it.episode_number}`}</div>
            </div>
          </div>
          <div className="mcard-meta">
            <StatusBadge status={it.status} />
            <span className="small">
              aired {formatAirDate(it.air_date)} · <TimeAgo iso={it.air_date} />
            </span>
          </div>
          <div className="mcard-actions">
            <button
              type="button"
              className="btn btn-primary"
              aria-label={`Search releases for ${it.series_name} ${seasonEpisode(it.season_number, it.episode_number)}`}
              onClick={() => onSearch(it)}
            >
              Search
            </button>
          </div>
        </li>
      ))}
    </ul>
  );
}

export default function Wanted() {
  const [offset, setOffset] = useState(0);
  const wanted = useWanted(LIMIT, offset);
  const searchAll = useSearchAllWanted();
  const [drawer, setDrawer] = useState<CalendarItem | null>(null);
  const items = wanted.data?.items ?? [];
  const total = wanted.data?.total ?? 0;
  const running = searchAll.error instanceof ApiError && searchAll.error.status === 409;
  const mobile = useIsMobile();
  const searchAllButton = (
    <ConfirmInline
      label="Search all"
      confirmLabel="Search & grab"
      message="Search every season with missing episodes (up to 10) and send the best match per missing episode to qBittorrent?"
      danger={false}
      size="md"
      disabled={total === 0}
      pending={searchAll.isPending}
      onConfirm={() => searchAll.mutate()}
    />
  );

  return (
    <>
      <PageHeader
        title="Wanted"
        subtitle="Aired episodes of monitored seasons with nothing downloaded, newest first. Search finds them through the feeds’ search URL templates."
        actionsInBar
        actions={searchAllButton}
      />
      {searchAll.isPending ? <Spinner label="Searching… this can take a while (the server pauses between feed fetches)." /> : null}
      <ErrorBanner
        error={running ? 'A search-all run is already in progress. Try again when it has finished.' : searchAll.error}
        title="Search all failed"
        onDismiss={() => searchAll.reset()}
      />
      {searchAll.data ? <SearchAllSummary seasons={searchAll.data.seasons} /> : null}
      <ErrorBanner error={wanted.error} title="Could not load wanted episodes" onRetry={() => void wanted.refetch()} />
      {wanted.isLoading ? (
        <LoadingBlock />
      ) : (
        <>
          {mobile ? (
            <WantedCards items={items} onSearch={setDrawer} />
          ) : (
          <TableWrap>
            <table className="table">
              <thead>
                <tr>
                  <th className="cover-col">
                    <span className="sr-only">Cover</span>
                  </th>
                  <th>Series</th>
                  <th>Episode</th>
                  <th>Aired</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {items.length === 0 ? (
                  <EmptyRow colSpan={6}>
                    Nothing wanted. Missing episodes show up here once monitored seasons are linked to metadata and an aired episode has no download.
                  </EmptyRow>
                ) : null}
                {items.map((it) => (
                  <tr key={`${it.season_id}-${it.episode_number}`}>
                    <td className="cover-col">
                      <Cover url={it.cover_url} alt={it.series_name} size="xs" />
                    </td>
                    <td className="title-cell">
                      <Link to={`/series/${it.series_id}`}>
                        <strong>{it.series_name}</strong>
                      </Link>
                    </td>
                    <td>
                      <span className="mono nowrap">{seasonEpisode(it.season_number, it.episode_number)}</span>
                      <div className="small muted">{it.title ?? `Episode ${it.episode_number}`}</div>
                    </td>
                    <td className="nowrap">
                      {formatAirDate(it.air_date)}
                      <div className="small muted">
                        <TimeAgo iso={it.air_date} />
                      </div>
                    </td>
                    <td>
                      <StatusBadge status={it.status} />
                    </td>
                    <td>
                      <div className="actions">
                        <button
                          type="button"
                          className="btn btn-sm btn-primary"
                          aria-label={`Search releases for ${it.series_name} ${seasonEpisode(it.season_number, it.episode_number)}`}
                          onClick={() => setDrawer(it)}
                        >
                          Search
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
          )}
          <Pagination total={total} limit={LIMIT} offset={offset} onChange={setOffset} disabled={wanted.isFetching} />
        </>
      )}
      {drawer ? (
        <SearchDrawer
          seasonId={drawer.season_id}
          title={`${drawer.series_name} — Season ${drawer.season_number}`}
          episode={drawer.episode_number}
          onClose={() => setDrawer(null)}
        />
      ) : null}
      <MobileActionBar>{searchAllButton}</MobileActionBar>
    </>
  );
}
