import { Fragment, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  useCreateSeason,
  useDeleteRule,
  useDeleteSeason,
  useDeleteSeries,
  useLinkMetadata,
  useMetadataProviders,
  useRules,
  useSaveRule,
  useSeries,
  useSeriesPaths,
  useTestRecent,
  useUpdateSeason,
  useUpdateSeries,
} from '../api/hooks';
import type { MediaResult, MetadataProvider, Rule, SeasonIn, Series, SeriesIn } from '../api/types';
import { ConfirmInline } from '../components/ConfirmInline';
import { Cover } from '../components/Cover';
import { ErrorBanner, Notice } from '../components/ErrorBanner';
import { CheckField, FormField } from '../components/FormField';
import { ListInput } from '../components/ListInput';
import { MetadataSearch, mediaKey } from '../components/MetadataSearch';
import { RuleForm, ruleToIn } from '../components/RuleForm';
import { SeasonEpisodesCard } from '../components/SeasonEpisodes';
import { SeasonFields } from '../components/SeasonFields';
import { SimulationTable } from '../components/SimulationTable';
import { LoadingBlock, Spinner } from '../components/Spinner';
import { Badge, StatusBadge } from '../components/StatusBadge';
import { Card, EmptyRow, PageHeader, TableWrap } from '../components/Table';
import { mediaStatus, mediaSubtitle, mediaTitle, metaLine, providerLabel, safeUrl } from '../lib/metadata';
import { emptySeason, rangeText, seasonToIn, seriesToIn, sortSeasons } from '../lib/series';

function SeriesForm({ series, onDone }: { series: Series; onDone: () => void }) {
  const [v, setV] = useState<SeriesIn>(seriesToIn(series));
  const update = useUpdateSeries();
  const set = <K extends keyof SeriesIn>(k: K, val: SeriesIn[K]) => setV({ ...v, [k]: val });
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        update.mutate(
          {
            id: series.id,
            body: {
              ...v,
              name: v.name.trim(),
              path_override: v.path_override?.trim() ? v.path_override.trim() : null,
              category_override: v.category_override?.trim() ? v.category_override.trim() : null,
              metadata_provider: series.metadata_provider,
              metadata_id: series.metadata_id,
              cover_url: series.cover_url,
              metadata: series.metadata,
            },
          },
          { onSuccess: onDone },
        );
      }}
    >
      <div className="form-grid">
        <FormField label="Name" help="Changing it changes the computed folder for future grabs only.">
          {(id) => <input id={id} type="text" required value={v.name} onChange={(e) => set('name', e.target.value)} />}
        </FormField>
        <FormField label="Aliases" help="Comma-separated.">
          {(id) => <ListInput id={id} value={v.aliases} onChange={(a) => set('aliases', a)} />}
        </FormField>
        <FormField label="Season folder format" help="Tokens: {season}, {season:02d}, {season:03d}, {series}.">
          {(id) => (
            <input id={id} type="text" className="mono" value={v.season_folder_format ?? ''} onChange={(e) => set('season_folder_format', e.target.value)} />
          )}
        </FormField>
        <FormField label="Category override">
          {(id) => (
            <input id={id} type="text" value={v.category_override ?? ''} onChange={(e) => set('category_override', e.target.value === '' ? null : e.target.value)} />
          )}
        </FormField>
        <FormField label="Series path override" help="Optional absolute path as seen by qBittorrent." className="span-2">
          {(id) => (
            <input
              id={id}
              type="text"
              className="mono"
              value={v.path_override ?? ''}
              onChange={(e) => set('path_override', e.target.value === '' ? null : e.target.value)}
            />
          )}
        </FormField>
        <CheckField
          label="Monitored (automatic grabs enabled)"
          checked={v.monitored}
          onChange={(b) => set('monitored', b)}
          help="When off, rules are still evaluated for inspection but nothing is sent automatically."
        />
      </div>
      <ErrorBanner error={update.error} title="Could not save series" />
      <div className="form-actions">
        <button type="submit" className="btn btn-primary" disabled={update.isPending}>
          {update.isPending ? 'Saving…' : 'Save series'}
        </button>
        <button type="button" className="btn btn-ghost" onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function MetadataCard({ series, providers }: { series: Series; providers: MetadataProvider[] }) {
  const link = useLinkMetadata(series.id);
  const [searching, setSearching] = useState(false);
  const info = series.metadata;
  const linked = series.metadata_provider !== null && series.metadata_id !== null;
  const href = safeUrl(info?.site_url);
  const label = providerLabel(series.metadata_provider, providers);
  const pick = (m: MediaResult) => {
    link.mutate(
      { provider: m.provider, id: m.id },
      {
        onSuccess: () => setSearching(false),
      },
    );
  };
  const pendingKey = link.isPending && link.variables ? mediaKey(link.variables.provider, link.variables.id) : null;
  return (
    <Card
      title={linked ? `Metadata (${label})` : 'Metadata'}
      actions={
        <>
          {searching ? (
            <button type="button" className="btn btn-sm btn-ghost" onClick={() => setSearching(false)}>
              Cancel
            </button>
          ) : (
            <button type="button" className="btn btn-sm" disabled={link.isPending} onClick={() => { link.reset(); setSearching(true); }}>
              {linked ? 'Change link' : 'Link to metadata'}
            </button>
          )}
          {linked && !searching ? (
            <ConfirmInline
              label="Unlink"
              confirmLabel="Unlink"
              message={`Clears the cover and ${label} info. Aliases and season links are kept.`}
              pending={link.isPending && link.variables?.provider === null}
              onConfirm={() => link.mutate({ provider: null, id: null })}
            />
          ) : null}
        </>
      }
    >
      <ErrorBanner error={link.error} title={linked ? `${label} update failed` : 'Could not link'} onDismiss={() => link.reset()} />
      {linked ? (
        <div className="media-linked">
          <Cover url={series.cover_url} alt={series.name} size="lg" />
          <div className="media-row-main">
            {info ? (
              <>
                <div>
                  <strong>{mediaTitle(info)}</strong> {info.kind ? <Badge tone="grey">{info.kind === 'tv' ? 'TV' : info.kind}</Badge> : null}
                </div>
                {mediaSubtitle(info) ? <div className="small muted">{mediaSubtitle(info)}</div> : null}
                {info.alt_titles.length > 0 ? <div className="small muted">also: {info.alt_titles.slice(0, 5).join(', ')}</div> : null}
                <div className="small">
                  <span className="muted">{metaLine(info)}</span> <Badge tone={mediaStatus(info.status).tone}>{mediaStatus(info.status).label}</Badge>
                </div>
              </>
            ) : (
              <div className="small muted">
                {label} id {series.metadata_id}
              </div>
            )}
            {href ? (
              <div className="small">
                <a href={href} target="_blank" rel="noopener noreferrer">
                  View on {label}
                </a>
              </div>
            ) : null}
            <p className="small muted">Metadata only: matching uses the series name and aliases, never {label} directly.</p>
          </div>
        </div>
      ) : !searching ? (
        <p className="small muted">
          Not linked. Link it to AniList (anime) or TMDB (TV) to show a cover, pull extra title aliases (existing aliases are kept) and link season 1 for
          episode metadata.
        </p>
      ) : null}
      {searching ? (
        <div className="subcard">
          <MetadataSearch
            onPick={pick}
            pendingKey={pendingKey}
            selectedKey={mediaKey(series.metadata_provider, series.metadata_id)}
            pickLabel="Link"
            initialQuery={series.name}
            defaultProvider={series.metadata_provider}
            autoFocus
          />
        </div>
      ) : null}
    </Card>
  );
}

function SeasonEditor({
  series,
  initial,
  seasonId,
  onDone,
}: {
  series: Series;
  initial: SeasonIn;
  seasonId: number | null;
  onDone: () => void;
}) {
  const [v, setV] = useState<SeasonIn>(initial);
  const create = useCreateSeason();
  const update = useUpdateSeason();
  const pending = create.isPending || update.isPending;
  const body: SeasonIn = { ...v, path_override: v.path_override?.trim() ? v.path_override.trim() : null };
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (seasonId === null) create.mutate({ seriesId: series.id, body }, { onSuccess: onDone });
        else update.mutate({ id: seasonId, body }, { onSuccess: onDone });
      }}
    >
      <SeasonFields
        value={v}
        onChange={setV}
        seriesName={series.name}
        seasonFolderFormat={series.season_folder_format}
        seriesPathOverride={series.path_override}
      />
      <ErrorBanner error={create.error ?? update.error} title="Could not save season" />
      <div className="form-actions">
        <button type="submit" className="btn btn-primary btn-sm" disabled={pending}>
          {pending ? 'Saving…' : seasonId === null ? 'Add season' : 'Save season'}
        </button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function SeasonsCard({ series }: { series: Series }) {
  const [editing, setEditing] = useState<number | 'new' | null>(null);
  const del = useDeleteSeason();
  const seasons = sortSeasons(series.seasons);
  const nextNum = seasons.length ? Math.max(...seasons.map((s) => s.season_number)) + 1 : 1;
  return (
    <Card
      title="Seasons"
      actions={
        editing === null ? (
          <button type="button" className="btn btn-sm" onClick={() => setEditing('new')}>
            Add season
          </button>
        ) : null
      }
    >
      <ErrorBanner error={del.error} onDismiss={() => del.reset()} />
      {editing === 'new' ? (
        <div className="subcard">
          <SeasonEditor series={series} initial={emptySeason(nextNum)} seasonId={null} onDone={() => setEditing(null)} />
        </div>
      ) : null}
      <TableWrap>
        <table className="table">
          <thead>
            <tr>
              <th>Season</th>
              <th>Monitored</th>
              <th>Episodes</th>
              <th>Absolute</th>
              <th>Computed save path</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {seasons.length === 0 ? <EmptyRow colSpan={6}>No seasons. Add one so rules can map releases to a folder.</EmptyRow> : null}
            {seasons.map((s) => (
              <Fragment key={s.id}>
                <tr>
                  <td className="nowrap">
                    <strong>S{String(s.season_number).padStart(2, '0')}</strong>
                  </td>
                  <td>
                    <StatusBadge status={s.monitored ? 'monitored' : 'unmonitored'} />
                  </td>
                  <td className="nowrap">{rangeText(s.episode_min, s.episode_max)}</td>
                  <td className="nowrap">{rangeText(s.absolute_min, s.absolute_max)}</td>
                  <td>
                    <code className="path-sm">{s.computed_save_path}</code>
                    {s.path_override ? (
                      <>
                        {' '}
                        <Badge tone="purple">override</Badge>
                      </>
                    ) : null}
                  </td>
                  <td>
                    <div className="actions">
                      <button type="button" className="btn btn-sm" onClick={() => setEditing(editing === s.id ? null : s.id)}>
                        {editing === s.id ? 'Close' : 'Edit'}
                      </button>
                      <ConfirmInline
                        label="Delete"
                        confirmLabel="Delete season"
                        message="Rules bound to it are removed too."
                        pending={del.isPending && del.variables === s.id}
                        onConfirm={() => del.mutate(s.id)}
                      />
                    </div>
                  </td>
                </tr>
                {editing === s.id ? (
                  <tr className="detail-row">
                    <td colSpan={6}>
                      <SeasonEditor series={series} initial={seasonToIn(s)} seasonId={s.id} onDone={() => setEditing(null)} />
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            ))}
          </tbody>
        </table>
      </TableWrap>
    </Card>
  );
}

function RuleSummary({ r }: { r: Rule }) {
  const parts: string[] = [];
  if (r.release_group) parts.push(`group ${r.release_group}${r.require_group_prefix ? ' (prefix)' : ''}`);
  if (r.resolutions.length) parts.push(r.resolutions.join('/'));
  if (r.sources.length) parts.push(`src ${r.sources.join('/')}`);
  if (r.codecs.length) parts.push(`codec ${r.codecs.join('/')}`);
  if (r.include_keywords.length) parts.push(`+${r.include_keywords.join(', +')}`);
  if (r.exclude_keywords.length) parts.push(`-${r.exclude_keywords.join(', -')}`);
  if (r.language_keywords.length) parts.push(`lang ${r.language_keywords.join('/')}`);
  if (r.min_size_mb !== null || r.max_size_mb !== null) parts.push(`size ${r.min_size_mb ?? 0}–${r.max_size_mb ?? '∞'} MB`);
  if (r.regex) parts.push(`regex /${r.regex}/`);
  return <span className="small muted break">{parts.join(' · ') || 'no extra filters'}</span>;
}

function RulesCard({ series }: { series: Series }) {
  const rules = useRules(series.id);
  const del = useDeleteRule();
  const save = useSaveRule();
  const testRecent = useTestRecent();
  const [editing, setEditing] = useState<number | 'new' | null>(null);
  const [tested, setTested] = useState<number | null>(null);
  const items = rules.data?.items ?? [];
  const seasonsFor = () => sortSeasons(series.seasons);

  return (
    <Card
      title="Rules"
      actions={
        editing === null ? (
          <button type="button" className="btn btn-sm" onClick={() => setEditing('new')} disabled={series.seasons.length === 0}>
            Add rule
          </button>
        ) : null
      }
    >
      {series.seasons.length === 0 ? <Notice kind="info">Add a season before adding rules.</Notice> : null}
      <ErrorBanner error={rules.error} title="Could not load rules" />
      <ErrorBanner error={del.error ?? save.error} onDismiss={() => { del.reset(); save.reset(); }} />
      {editing === 'new' ? (
        <div className="subcard">
          <RuleForm initial={null} defaultSeriesId={series.id} seasonsFor={seasonsFor} onDone={() => setEditing(null)} />
        </div>
      ) : null}
      {rules.isLoading ? (
        <Spinner />
      ) : (
        <TableWrap>
          <table className="table">
            <thead>
              <tr>
                <th>Rule</th>
                <th>Season</th>
                <th className="num">Priority</th>
                <th>Enabled</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 ? <EmptyRow colSpan={5}>No rules for this series.</EmptyRow> : null}
              {items.map((r) => (
                <Fragment key={r.id}>
                  <tr>
                    <td className="title-cell">
                      <strong>{r.name}</strong>
                      <div>
                        <RuleSummary r={r} />
                      </div>
                    </td>
                    <td className="nowrap">{r.season_number !== null ? `S${String(r.season_number).padStart(2, '0')}` : 'any'}</td>
                    <td className="num">{r.priority}</td>
                    <td>
                      <StatusBadge status={r.enabled ? 'enabled' : 'disabled'} />
                    </td>
                    <td>
                      <div className="actions">
                        <button type="button" className="btn btn-sm" onClick={() => setEditing(editing === r.id ? null : r.id)}>
                          {editing === r.id ? 'Close' : 'Edit'}
                        </button>
                        <button
                          type="button"
                          className="btn btn-sm"
                          disabled={save.isPending}
                          onClick={() => save.mutate({ id: r.id, body: { ...ruleToIn(r), enabled: !r.enabled } })}
                        >
                          {r.enabled ? 'Disable' : 'Enable'}
                        </button>
                        <button
                          type="button"
                          className="btn btn-sm"
                          disabled={testRecent.isPending}
                          onClick={() => {
                            setTested(r.id);
                            testRecent.mutate({ id: r.id, limit: 100 });
                          }}
                        >
                          {testRecent.isPending && tested === r.id ? 'Testing…' : 'Test recent'}
                        </button>
                        <ConfirmInline label="Delete" confirmLabel="Delete rule" pending={del.isPending && del.variables === r.id} onConfirm={() => del.mutate(r.id)} />
                      </div>
                    </td>
                  </tr>
                  {editing === r.id ? (
                    <tr className="detail-row">
                      <td colSpan={5}>
                        <RuleForm initial={r} defaultSeriesId={series.id} seasonsFor={seasonsFor} onDone={() => setEditing(null)} />
                      </td>
                    </tr>
                  ) : null}
                  {tested === r.id && (testRecent.data || testRecent.error) && !testRecent.isPending ? (
                    <tr className="detail-row">
                      <td colSpan={5}>
                        <div className="detail-head">
                          <strong className="small">Test against the 100 most recent stored releases (no side effects)</strong>
                          <button type="button" className="btn btn-sm btn-ghost" onClick={() => setTested(null)}>
                            Hide
                          </button>
                        </div>
                        <ErrorBanner error={testRecent.error} />
                        {testRecent.data ? <SimulationTable items={testRecent.data.items} /> : null}
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              ))}
            </tbody>
          </table>
        </TableWrap>
      )}
    </Card>
  );
}

function PathsCard({ seriesId }: { seriesId: number }) {
  const paths = useSeriesPaths(seriesId);
  return (
    <Card title="Save paths (server-computed)">
      <p className="small muted">
        Exactly what is sent to qBittorrent as <code>savepath</code>, as seen by qBittorrent. This app never creates or touches these folders.
      </p>
      <ErrorBanner error={paths.error} />
      {paths.isLoading ? (
        <Spinner />
      ) : (
        <TableWrap>
          <table className="table">
            <thead>
              <tr>
                <th>Season</th>
                <th>Save path</th>
              </tr>
            </thead>
            <tbody>
              {(paths.data?.items ?? []).length === 0 ? <EmptyRow colSpan={2}>No seasons.</EmptyRow> : null}
              {(paths.data?.items ?? []).map((p) => (
                <tr key={p.season_id}>
                  <td className="nowrap">S{String(p.season_number).padStart(2, '0')}</td>
                  <td>
                    <code className="path-sm">{p.save_path}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      )}
    </Card>
  );
}

export default function SeriesDetail() {
  const params = useParams();
  const id = Number(params.id);
  const nav = useNavigate();
  const series = useSeries(id);
  const update = useUpdateSeries();
  const del = useDeleteSeries();
  const providersQ = useMetadataProviders();
  const providers = providersQ.data?.items ?? [];
  const [editing, setEditing] = useState(false);

  if (!Number.isFinite(id)) return <ErrorBanner error="Invalid series id" />;
  if (series.isLoading) return <LoadingBlock />;
  if (!series.data) return <ErrorBanner error={series.error ?? 'Not found'} title="Could not load series" onRetry={() => void series.refetch()} />;
  const s = series.data;

  return (
    <>
      <PageHeader
        title={s.name}
        subtitle={
          <>
            <StatusBadge status={s.monitored ? 'monitored' : 'unmonitored'} />{' '}
            {s.aliases.length ? <>aliases: {s.aliases.join(', ')} · </> : null}
            folder format <code>{s.season_folder_format}</code>
            {s.category_override ? <> · category {s.category_override}</> : null}
          </>
        }
        actions={
          <>
            <Link to="/series" className="btn btn-ghost">
              All series
            </Link>
            <button
              type="button"
              className="btn"
              disabled={update.isPending}
              onClick={() => update.mutate({ id: s.id, body: { ...seriesToIn(s), monitored: !s.monitored } })}
            >
              {s.monitored ? 'Unmonitor' : 'Monitor'}
            </button>
            {!editing ? (
              <button type="button" className="btn" onClick={() => setEditing(true)}>
                Edit series
              </button>
            ) : null}
            <ConfirmInline
              label="Delete"
              confirmLabel="Delete series"
              size="md"
              message="Removes seasons and rules. qBittorrent torrents are not touched."
              pending={del.isPending}
              onConfirm={() => del.mutate(s.id, { onSuccess: () => nav('/series') })}
            />
          </>
        }
      />
      <ErrorBanner error={update.error ?? del.error} onDismiss={() => { update.reset(); del.reset(); }} />
      {!s.monitored ? (
        <Notice kind="info">This series is not monitored: matches are shown in the inspector but nothing is sent automatically.</Notice>
      ) : null}
      {editing ? (
        <Card title="Edit series">
          <SeriesForm series={s} onDone={() => setEditing(false)} />
        </Card>
      ) : null}
      <MetadataCard series={s} providers={providers} />
      <SeasonsCard series={s} />
      {sortSeasons(s.seasons).map((se) => (
        <SeasonEpisodesCard key={se.id} series={s} season={se} providers={providers} />
      ))}
      <RulesCard series={s} />
      <PathsCard seriesId={s.id} />
    </>
  );
}
