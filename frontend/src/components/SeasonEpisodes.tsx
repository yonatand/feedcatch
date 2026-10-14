import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useEpisodes, useMetadataDetail, useRefreshEpisodes, useUpdateEpisode, useUpdateSeason } from '../api/hooks';
import type { Episode, MetadataProvider, MetadataProviderName, SearchResult, Season, Series } from '../api/types';
import { formatAirDate, pad2, percent } from '../lib/format';
import { providerLabel, safeUrl } from '../lib/metadata';
import { seasonToIn } from '../lib/series';
import { ConfirmInline } from './ConfirmInline';
import { DeleteDownloadButton } from './DownloadsTable';
import { ErrorBanner, Notice } from './ErrorBanner';
import { MetadataSearch, mediaKey } from './MetadataSearch';
import { Pagination } from './Pagination';
import { SearchDrawer } from './SearchDrawer';
import { Spinner } from './Spinner';
import { Badge, StatusBadge } from './StatusBadge';
import { Card, EmptyRow, TableWrap } from './Table';
import { TimeAgo, absoluteTime } from './TimeAgo';

const PAGE = 50;
const HAVE = new Set(['downloaded', 'downloading', 'pending']);

export function EpisodeStatusBadge({ ep }: { ep: Pick<Episode, 'status' | 'download'> }) {
  if (ep.status === 'downloading' && ep.download?.qbit_progress !== null && ep.download?.qbit_progress !== undefined) {
    return <Badge tone="blue">downloading {percent(ep.download.qbit_progress)}</Badge>;
  }
  return <StatusBadge status={ep.status} />;
}

function TitleEditor({ seasonId, ep, onDone }: { seasonId: number; ep: Episode; onDone: () => void }) {
  const [v, setV] = useState(ep.title ?? '');
  const upd = useUpdateEpisode();
  const save = () =>
    upd.mutate({ seasonId, number: ep.episode_number, body: { title: v.trim() === '' ? null : v.trim() } }, { onSuccess: onDone });
  return (
    <div className="inline-edit">
      <input
        type="text"
        aria-label={`Title of episode ${ep.episode_number}`}
        value={v}
        autoFocus
        onChange={(e) => setV(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            save();
          } else if (e.key === 'Escape') {
            e.preventDefault();
            e.stopPropagation();
            onDone();
          }
        }}
      />
      <button type="button" className="btn btn-sm btn-primary" disabled={upd.isPending} onClick={save}>
        {upd.isPending ? 'Saving…' : 'Save'}
      </button>
      <button type="button" className="btn btn-sm btn-ghost" onClick={onDone}>
        Cancel
      </button>
      <ErrorBanner error={upd.error} title="Could not save title" />
    </div>
  );
}

/** Page containing the newest aired episode, so long shows open near "now". */
function initialOffset(items: readonly Episode[]): number {
  const now = Date.now();
  let idx = -1;
  items.forEach((e, i) => {
    if (e.air_date && Date.parse(e.air_date) <= now) idx = i;
  });
  return idx < 0 ? 0 : Math.floor(idx / PAGE) * PAGE;
}

type SeasonLink = {
  /** PUT /api/seasons/{id} with the full SeasonIn plus the new provider/id (null/null unlinks). */
  link: (provider: MetadataProviderName | null, id: string | null) => void;
  pending: boolean;
  pendingKey: string | null;
  done: number;
};

/** Season link mutation, lifted to the card so warnings/errors survive the field being swapped for the call-to-action. */
function useSeasonLink(season: Season) {
  const update = useUpdateSeason();
  const [warnings, setWarnings] = useState<string[]>([]);
  const [done, setDone] = useState(0);
  const link = (provider: MetadataProviderName | null, mid: string | null) => {
    setWarnings([]);
    update.mutate(
      { id: season.id, body: { ...seasonToIn(season), metadata_provider: provider, metadata_id: mid } },
      {
        onSuccess: (d) => {
          setWarnings(d.warnings ?? []);
          setDone((n) => n + 1);
        },
      },
    );
  };
  const state: SeasonLink = {
    link,
    pending: update.isPending,
    pendingKey: update.isPending && update.variables ? mediaKey(update.variables.body.metadata_provider, update.variables.body.metadata_id) : null,
    done,
  };
  return { state, update, warnings };
}

function seasonQuery(series: Series, season: Season, provider: MetadataProviderName | null): string {
  // TMDB entries are whole shows (the season number selects the season); AniList has one entry per season.
  return season.season_number > 1 && provider !== 'tmdb' ? `${series.name} Season ${season.season_number}` : series.name;
}

function SeasonMetadataField({ series, season, providers, sl }: { series: Series; season: Season; providers: MetadataProvider[]; sl: SeasonLink }) {
  const [linking, setLinking] = useState(false);
  const prov = season.metadata_provider;
  const id = season.metadata_id;
  const linked = prov !== null && id !== null;
  const sameAsSeries = linked && prov === series.metadata_provider && id === series.metadata_id;
  // Different entry from the series (e.g. an AniList sequel): look up its title (cached for 30 min).
  const detail = useMetadataDetail(linked && !sameAsSeries ? prov : null, linked && !sameAsSeries ? id : null);
  const title = sameAsSeries ? series.metadata?.title : detail.data?.title;
  const site = sameAsSeries ? series.metadata?.site_url : detail.data?.site_url;
  const label = providerLabel(prov, providers);

  useEffect(() => {
    setLinking(false);
  }, [sl.done]);

  return (
    <div className="season-meta">
      <div className="season-meta-line">
        <span className="muted small">Episode metadata:</span>{' '}
        <span>
          <Badge tone="blue">{label}</Badge> <code className="path-sm">#{id}</code>
          {title ? <strong> {title}</strong> : detail.isLoading ? <span className="muted small"> loading title…</span> : null}
          {prov === 'tmdb' ? <span className="muted small"> · season {season.season_number}</span> : null}
          {safeUrl(site) ? (
            <>
              {' '}
              ·{' '}
              <a href={safeUrl(site) ?? undefined} target="_blank" rel="noopener noreferrer" className="small">
                View on {label}
              </a>
            </>
          ) : null}
          {season.metadata_refreshed_at ? (
            <span className="muted small">
              {' '}
              · refreshed <TimeAgo iso={season.metadata_refreshed_at} />
            </span>
          ) : null}
        </span>
        <span className="actions">
          <button type="button" className="btn btn-sm" disabled={sl.pending} onClick={() => setLinking((x) => !x)}>
            {linking ? 'Cancel' : 'Change'}
          </button>
          {!linking ? (
            <ConfirmInline
              label="Unlink"
              confirmLabel="Unlink"
              message="Episodes already fetched are kept."
              pending={sl.pending}
              onConfirm={() => sl.link(null, null)}
            />
          ) : null}
        </span>
      </div>
      {linking ? (
        <div className="subcard">
          <p className="small muted">
            Pick the entry for <strong>season {season.season_number}</strong>. For AniList choose the entry of this season (sequels are separate entries); for
            TMDB choose the show (the season number selects the season).
          </p>
          <MetadataSearch
            onPick={(m) => sl.link(m.provider, m.id)}
            pendingKey={sl.pendingKey}
            selectedKey={mediaKey(prov, id)}
            pickLabel="Link"
            initialQuery={seasonQuery(series, season, prov ?? series.metadata_provider)}
            defaultProvider={prov ?? series.metadata_provider}
            autoFocus
          />
        </div>
      ) : null}
    </div>
  );
}

/** Shown instead of an empty episode table while the season has no metadata link. */
function UnlinkedSeasonCta({
  series,
  season,
  providers,
  sl,
  hasEpisodes,
}: {
  series: Series;
  season: Season;
  providers: MetadataProvider[];
  sl: SeasonLink;
  hasEpisodes: boolean;
}) {
  const sp = series.metadata_provider;
  const sid = series.metadata_id;
  // AniList has one entry per season, so the series' entry only fits season 1; a TMDB show covers every season.
  const canUseSeries = sp !== null && sid !== null && (season.season_number === 1 || sp === 'tmdb');
  const seriesKey = mediaKey(sp, sid);
  return (
    <section className="cta-card" aria-label={`Link season ${season.season_number} to episode metadata`}>
      <h3>{hasEpisodes ? 'This season is not linked to an episode list' : 'No episode list yet'}</h3>
      <p>Link this season to AniList or TMDB to see its episodes, air dates and what is missing.</p>
      {canUseSeries ? (
        <div className="cta-actions">
          <button type="button" className="btn" disabled={sl.pending} onClick={() => sl.link(sp, sid)}>
            {sl.pendingKey !== null && sl.pendingKey === seriesKey ? 'Linking…' : "Use the series' entry"}
          </button>
          <span className="small muted">
            {providerLabel(sp, providers)} #{sid}
            {series.metadata?.title ? ` · ${series.metadata.title}` : ''}
            {sp === 'tmdb' ? ` · season ${season.season_number}` : ''}
          </span>
        </div>
      ) : null}
      <MetadataSearch
        onPick={(m) => sl.link(m.provider, m.id)}
        pendingKey={sl.pendingKey}
        pickLabel="Link"
        initialQuery={seasonQuery(series, season, sp)}
        defaultProvider={sp}
      />
    </section>
  );
}

/** Episodes of one season: status per episode, progress line, metadata link, refresh and release search. */
export function SeasonEpisodesCard({ series, season, providers }: { series: Series; season: Season; providers: MetadataProvider[] }) {
  const eps = useEpisodes(season.id);
  const refresh = useRefreshEpisodes();
  const { state: sl, update, warnings } = useSeasonLink(season);
  const [drawer, setDrawer] = useState<{ episode: number | null; reuse: boolean } | null>(null);
  const [lastResult, setLastResult] = useState<SearchResult | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [offset, setOffset] = useState<number | null>(null);

  const items = eps.data?.items ?? [];
  const summary = eps.data?.summary;
  const linked = season.metadata_provider !== null && season.metadata_id !== null;
  const sLabel = `S${pad2(season.season_number)}`;

  useEffect(() => {
    if (offset === null && eps.data) setOffset(initialOffset(eps.data.items));
  }, [eps.data, offset]);

  const known = useMemo(() => {
    const m = new Map<number, number>();
    for (const c of lastResult?.candidates ?? []) m.set(c.episode_number, (m.get(c.episode_number) ?? 0) + 1);
    return m;
  }, [lastResult]);

  const off = offset ?? 0;
  const page = items.slice(off, off + PAGE);
  const total = summary?.episode_count ?? season.episode_count ?? items.length;
  const downloaded = summary?.downloaded_count ?? season.downloaded_count ?? 0;
  const missing = summary?.missing_count ?? season.missing_count ?? 0;
  const unaired = summary?.unaired_count ?? 0;
  const hasEpisodes = items.length > 0;

  return (
    <Card
      title={
        <>
          {sLabel} episodes {!season.monitored ? <StatusBadge status="unmonitored" /> : null}
        </>
      }
      actions={
        <>
          {linked ? (
            <button
              type="button"
              className="btn btn-sm"
              disabled={refresh.isPending}
              title="Fetch episode titles and air dates now"
              onClick={() => refresh.mutate(season.id)}
            >
              {refresh.isPending ? 'Refreshing…' : 'Refresh metadata'}
            </button>
          ) : null}
          <button type="button" className="btn btn-sm btn-primary" onClick={() => setDrawer({ episode: null, reuse: false })}>
            Search releases
          </button>
        </>
      }
    >
      {linked ? (
        <SeasonMetadataField series={series} season={season} providers={providers} sl={sl} />
      ) : (
        <UnlinkedSeasonCta series={series} season={season} providers={providers} sl={sl} hasEpisodes={hasEpisodes} />
      )}
      <ErrorBanner error={update.error} title="Could not link the season" onDismiss={() => update.reset()} />
      {warnings.length > 0 ? <Notice kind="warning">Linked, but the metadata refresh reported: {warnings.join('; ')}</Notice> : null}
      {linked || hasEpisodes ? (
        <p className="progress-line">
          <strong>
            {downloaded} of {total} downloaded
          </strong>
          {' · '}
          <span className={missing > 0 ? 'warn-text' : undefined}>{missing} missing</span>
          {unaired > 0 ? ` · ${unaired} unaired` : null}
        </p>
      ) : null}
      {total > 0 ? (
        <div
          className="progress-bar"
          role="progressbar"
          aria-label={`${sLabel} downloaded`}
          aria-valuemin={0}
          aria-valuemax={total}
          aria-valuenow={downloaded}
        >
          <span style={{ width: `${Math.min(100, (downloaded / total) * 100)}%` }} />
        </div>
      ) : null}
      <ErrorBanner error={refresh.error} title="Metadata refresh failed" onDismiss={() => refresh.reset()} />
      <ErrorBanner error={eps.error} title="Could not load episodes" onRetry={() => void eps.refetch()} />
      {eps.isLoading ? (
        <Spinner />
      ) : !linked && !hasEpisodes ? null : (
        <>
          <TableWrap>
            <table className="table table-compact episodes-table">
              <thead>
                <tr>
                  <th className="num">#</th>
                  <th>Title</th>
                  <th>Air date</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {items.length === 0 ? (
                  <EmptyRow colSpan={5}>
                    No episodes known yet. Use “Refresh metadata” to fetch them.
                  </EmptyRow>
                ) : null}
                {page.map((ep) => {
                  const cands = known.get(ep.episode_number) ?? 0;
                  return (
                    <tr key={ep.episode_number}>
                      <td className="num nowrap">E{pad2(ep.episode_number)}</td>
                      <td className="title-cell">
                        {editing === ep.episode_number ? (
                          <TitleEditor seasonId={season.id} ep={ep} onDone={() => setEditing(null)} />
                        ) : (
                          <>
                            {ep.title ? ep.title : <span className="muted">Episode {ep.episode_number}</span>}
                            {ep.source === 'manual' ? (
                              <>
                                {' '}
                                <Badge tone="grey" title="Edited by hand; metadata refreshes never overwrite it">
                                  manual
                                </Badge>
                              </>
                            ) : null}
                            {ep.download ? (
                              <div className="small muted truncate" title={ep.download.entry_title}>
                                <Link to={`/releases/${ep.download.entry_id}`}>{ep.download.entry_title}</Link>
                                {ep.download.status === 'failed' ? (
                                  <>
                                    {' '}
                                    <StatusBadge status="failed" />
                                  </>
                                ) : null}
                              </div>
                            ) : null}
                          </>
                        )}
                      </td>
                      <td className="nowrap">
                        {ep.air_date ? (
                          <>
                            <span title={absoluteTime(ep.air_date)}>{formatAirDate(ep.air_date)}</span>
                            <div className="small muted">
                              <TimeAgo iso={ep.air_date} />
                            </div>
                          </>
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                      <td>
                        <EpisodeStatusBadge ep={ep} />
                      </td>
                      <td>
                        <div className="actions">
                          <button
                            type="button"
                            className="btn btn-sm"
                            aria-label={`Search releases for episode ${ep.episode_number}`}
                            onClick={() => setDrawer({ episode: ep.episode_number, reuse: false })}
                          >
                            Search
                          </button>
                          {cands > 0 && !HAVE.has(ep.status) ? (
                            <button
                              type="button"
                              className="btn btn-sm btn-primary"
                              aria-label={`Grab episode ${ep.episode_number} (${cands} candidate${cands === 1 ? '' : 's'} from the last search)`}
                              onClick={() => setDrawer({ episode: ep.episode_number, reuse: true })}
                            >
                              Grab
                            </button>
                          ) : null}
                          {editing !== ep.episode_number ? (
                            <button
                              type="button"
                              className="btn btn-sm btn-ghost"
                              aria-label={`Edit title of episode ${ep.episode_number}`}
                              onClick={() => setEditing(ep.episode_number)}
                            >
                              Edit title
                            </button>
                          ) : null}
                          {ep.download ? (
                            <DeleteDownloadButton id={ep.download.id} what={`${sLabel}E${pad2(ep.episode_number)}`} />
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </TableWrap>
          {items.length > PAGE ? <Pagination total={items.length} limit={PAGE} offset={off} onChange={setOffset} /> : null}
        </>
      )}
      {drawer ? (
        <SearchDrawer
          seasonId={season.id}
          title={`${series.name} — Season ${season.season_number}`}
          episode={drawer.episode}
          initialResult={drawer.reuse ? lastResult : null}
          onResult={setLastResult}
          onClose={() => setDrawer(null)}
        />
      ) : null}
    </Card>
  );
}
