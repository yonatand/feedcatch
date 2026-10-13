import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ApiError } from '../api/client';
import { useEntry, useEvaluateEntry, useGrabConfirm, useGrabPreview, useSeriesList } from '../api/hooks';
import type { Download, Evaluation, FeedEntryDetail, GrabPreview } from '../api/types';
import { ConditionsTable } from '../components/ConditionsTable';
import { ConfirmInline } from '../components/ConfirmInline';
import { CopyButton } from '../components/CopyButton';
import { DownloadsTable } from '../components/DownloadsTable';
import { ErrorBanner, Notice } from '../components/ErrorBanner';
import { CheckField, FormField } from '../components/FormField';
import { NumberInput } from '../components/NumberInput';
import { ParsedTable } from '../components/ParsedBadges';
import { PathPreview } from '../components/PathPreview';
import { LoadingBlock } from '../components/Spinner';
import { Badge, StatusBadge } from '../components/StatusBadge';
import { Card, PageHeader } from '../components/Table';
import { TimeAgo } from '../components/TimeAgo';
import { formatBytes, seasonEpisode, truncateMiddle } from '../lib/format';
import { sortSeasons } from '../lib/series';

function LinksCard({ e }: { e: FeedEntryDetail }) {
  return (
    <Card title="Links">
      <dl className="kv">
        <div className="kv-row">
          <dt>Magnet</dt>
          <dd>
            {e.magnet_url ? (
              <span className="path-row">
                <code className="path-sm" title={e.magnet_url}>
                  {truncateMiddle(e.magnet_url, 64)}
                </code>
                <CopyButton text={e.magnet_url} />
              </span>
            ) : (
              <span className="muted">none</span>
            )}
          </dd>
        </div>
        <div className="kv-row">
          <dt>.torrent</dt>
          <dd>
            {e.torrent_url ? (
              <span className="path-row">
                <code className="path-sm" title={e.torrent_url}>
                  {truncateMiddle(e.torrent_url, 64)}
                </code>
                <CopyButton text={e.torrent_url} />
              </span>
            ) : (
              <span className="muted">none</span>
            )}
          </dd>
        </div>
        <div className="kv-row">
          <dt>NZB</dt>
          <dd>
            {e.has_nzb ? (
              <span className="muted">present — ignored; NZB links are never sent to qBittorrent</span>
            ) : (
              <span className="muted">none</span>
            )}
          </dd>
        </div>
        <div className="kv-row">
          <dt>Infohash</dt>
          <dd>{e.infohash ? <code className="path-sm">{e.infohash}</code> : <span className="muted">unknown</span>}</dd>
        </div>
        <div className="kv-row">
          <dt>Page</dt>
          <dd>
            {e.link && /^https?:\/\//i.test(e.link) ? (
              <a href={e.link} target="_blank" rel="noopener noreferrer nofollow" className="break">
                {truncateMiddle(e.link, 64)}
              </a>
            ) : (
              <span className="muted">—</span>
            )}
          </dd>
        </div>
      </dl>
      {!e.magnet_url && !e.torrent_url ? <Notice kind="warning">No torrent/magnet link (NZB-only). This release cannot be sent to qBittorrent.</Notice> : null}
    </Card>
  );
}

function EvaluationBlock({ ev }: { ev: Evaluation }) {
  return (
    <details className="eval" open={ev.matched}>
      <summary>
        <StatusBadge status={ev.matched ? 'matched' : 'rejected'} /> <strong>{ev.rule_name}</strong>{' '}
        <span className="muted">
          → <Link to={`/series/${ev.series_id}`}>{ev.series_name}</Link> {seasonEpisode(ev.season_number, ev.episode_number)}
        </span>{' '}
        <span className="small muted">
          evaluated <TimeAgo iso={ev.evaluated_at} />
        </span>
      </summary>
      <ConditionsTable conditions={ev.conditions} />
    </details>
  );
}

function GrabResult({ d }: { d: Download }) {
  return (
    <Notice kind={d.status === 'failed' ? 'error' : d.status === 'path_mismatch' ? 'warning' : 'success'}>
      Download #{d.id}: <StatusBadge status={d.status} /> {d.last_error ? <span>— {d.last_error}</span> : null}{' '}
      <Link to="/downloads">View downloads →</Link>
    </Notice>
  );
}

function PreviewView({ p }: { p: GrabPreview }) {
  return (
    <div className="grab-preview">
      <PathPreview path={p.save_path} label="Will be sent with savepath" note />
      <dl className="kv">
        <div className="kv-row">
          <dt>Category</dt>
          <dd>{p.category ?? <span className="muted">none</span>}</dd>
        </div>
        <div className="kv-row">
          <dt>Source</dt>
          <dd>
            <Badge tone="green">{p.source_url_kind}</Badge>{' '}
            <code className="path-sm" title={p.source_url}>
              {truncateMiddle(p.source_url, 64)}
            </code>{' '}
            <CopyButton text={p.source_url} />
          </dd>
        </div>
        <div className="kv-row">
          <dt>Infohash</dt>
          <dd>{p.infohash ? <code className="path-sm">{p.infohash}</code> : <span className="muted">unknown</span>}</dd>
        </div>
      </dl>
      {p.warnings.length > 0 ? (
        <Notice kind="warning">
          <ul className="plain-list">
            {p.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </Notice>
      ) : null}
      {p.duplicate_of ? (
        <Notice kind="warning">
          <strong>Duplicate:</strong> download #{p.duplicate_of.id} ({p.duplicate_of.entry_title}) already covers{' '}
          {p.duplicate_of.series_name} {seasonEpisode(p.duplicate_of.season_number, p.duplicate_of.episode_number)} with status{' '}
          <StatusBadge status={p.duplicate_of.status} />.
        </Notice>
      ) : null}
    </div>
  );
}

function GrabCard({ e }: { e: FeedEntryDetail }) {
  const seriesList = useSeriesList();
  const previewM = useGrabPreview();
  const confirmM = useGrabConfirm();
  const matched = e.evaluations.filter((ev) => ev.matched && ev.season_id !== null);
  const [mode, setMode] = useState<'match' | 'manual'>(matched.length > 0 ? 'match' : 'manual');
  const [matchIdx, setMatchIdx] = useState(0);
  const [seasonId, setSeasonId] = useState<number | null>(null);
  const [episode, setEpisode] = useState<number | null>(e.parsed.absolute ? null : e.parsed.episode);
  const [force, setForce] = useState(false);
  const [result, setResult] = useState<Download | null>(null);

  const allSeasons = useMemo(
    () =>
      (seriesList.data?.items ?? []).flatMap((s) =>
        sortSeasons(s.seasons).map((se) => ({ id: se.id, label: `${s.name} — Season ${se.season_number}` })),
      ),
    [seriesList.data],
  );

  const chosen: { season_id: number; episode_number: number } | null =
    mode === 'match'
      ? matched[matchIdx] && matched[matchIdx].season_id !== null && matched[matchIdx].episode_number !== null
        ? { season_id: matched[matchIdx].season_id as number, episode_number: matched[matchIdx].episode_number as number }
        : null
      : seasonId !== null && episode !== null
        ? { season_id: seasonId, episode_number: episode }
        : null;

  // Any change to the target invalidates a shown preview.
  const key = chosen ? `${chosen.season_id}:${chosen.episode_number}` : '';
  useEffect(() => {
    previewM.reset();
    confirmM.reset();
    setForce(false);
  }, [key]);

  const noLink = !e.magnet_url && !e.torrent_url;
  const preview = previewM.data;
  const dup = preview?.duplicate_of ?? null;
  const conflict = confirmM.error instanceof ApiError && confirmM.error.status === 409;

  const send = () => {
    if (!chosen) return;
    confirmM.mutate(
      { entryId: e.id, body: { ...chosen, force: dup !== null && force } },
      {
        onSuccess: (d) => {
          setResult(d);
          previewM.reset();
        },
      },
    );
  };

  return (
    <Card title="Manual grab">
      {noLink ? (
        <Notice kind="warning">Nothing to grab: this entry has no magnet or .torrent link.</Notice>
      ) : (
        <>
          {e.is_historical ? (
            <Notice kind="info">This is a historical entry (seen on the first poll). It was never auto-grabbed; a manual grab is allowed.</Notice>
          ) : null}
          {result ? <GrabResult d={result} /> : null}
          <div className="segmented" role="radiogroup" aria-label="Target">
            <label className={mode === 'match' ? 'active' : ''}>
              <input type="radio" name="grab-mode" checked={mode === 'match'} disabled={matched.length === 0} onChange={() => setMode('match')} />
              From matched rule{matched.length === 0 ? ' (none)' : ''}
            </label>
            <label className={mode === 'manual' ? 'active' : ''}>
              <input type="radio" name="grab-mode" checked={mode === 'manual'} onChange={() => setMode('manual')} />
              Choose series / season
            </label>
          </div>
          {mode === 'match' && matched.length > 0 ? (
            <FormField label="Matched evaluation">
              {(id) => (
                <select id={id} value={matchIdx} onChange={(ev) => setMatchIdx(Number(ev.target.value))}>
                  {matched.map((m, i) => (
                    <option key={m.rule_id} value={i}>
                      {m.rule_name}: {m.series_name} {seasonEpisode(m.season_number, m.episode_number)}
                    </option>
                  ))}
                </select>
              )}
            </FormField>
          ) : null}
          {mode === 'match' && matched.length > 0 && matched[matchIdx]?.episode_number === null ? (
            <Notice kind="warning">That evaluation has no episode number; choose the season and episode manually.</Notice>
          ) : null}
          {mode === 'manual' ? (
            <div className="form-grid">
              <FormField label="Series / season">
                {(id) => (
                  <select id={id} value={seasonId ?? ''} onChange={(ev) => setSeasonId(ev.target.value === '' ? null : Number(ev.target.value))}>
                    <option value="">Select…</option>
                    {allSeasons.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.label}
                      </option>
                    ))}
                  </select>
                )}
              </FormField>
              <FormField
                label="Episode number (season-relative)"
                help={e.parsed.absolute && e.parsed.episode !== null ? `Title has absolute number ${e.parsed.episode}; enter the season episode.` : undefined}
              >
                {(id) => <NumberInput id={id} min={0} value={episode} onChange={setEpisode} />}
              </FormField>
            </div>
          ) : null}
          {allSeasons.length === 0 && mode === 'manual' && seriesList.data ? (
            <Notice kind="info">
              No seasons defined. <Link to="/series/new">Create a series</Link> first.
            </Notice>
          ) : null}
          <div className="form-actions">
            <button
              type="button"
              className="btn"
              disabled={!chosen || previewM.isPending}
              onClick={() => {
                if (!chosen) return;
                setResult(null);
                previewM.mutate({ entryId: e.id, body: { ...chosen, force: false } });
              }}
            >
              {previewM.isPending ? 'Preparing…' : 'Grab — preview first'}
            </button>
          </div>
          <ErrorBanner error={previewM.error} title="Preview failed" />
          {preview ? (
            <div className="subcard">
              <h3>Review before sending</h3>
              <PreviewView p={preview} />
              {dup ? (
                <div className="force-box">
                  <CheckField
                    label={<strong>Force grab despite the duplicate</strong>}
                    checked={force}
                    onChange={setForce}
                    help="qBittorrent will receive a second torrent for the same episode. Existing torrents are not removed or changed."
                  />
                </div>
              ) : null}
              <ErrorBanner
                error={conflict ? 'Rejected as a duplicate (409). Tick “Force grab” to send anyway.' : confirmM.error}
                title="Send failed"
              />
              <div className="form-actions">
                {dup ? (
                  <ConfirmInline
                    label="Force send to qBittorrent"
                    confirmLabel="Yes, send duplicate"
                    message="Send a duplicate torrent?"
                    size="md"
                    disabled={!force}
                    pending={confirmM.isPending}
                    onConfirm={send}
                  />
                ) : (
                  <button type="button" className="btn btn-primary" disabled={confirmM.isPending} onClick={send}>
                    {confirmM.isPending ? 'Sending…' : 'Confirm send to qBittorrent'}
                  </button>
                )}
                <button type="button" className="btn btn-ghost" onClick={() => previewM.reset()}>
                  Cancel
                </button>
              </div>
            </div>
          ) : null}
        </>
      )}
    </Card>
  );
}

export default function ReleaseInspector() {
  const params = useParams();
  const id = Number(params.id);
  const entry = useEntry(id);
  const evaluate = useEvaluateEntry();

  if (!Number.isFinite(id)) return <ErrorBanner error="Invalid release id" />;
  if (entry.isLoading) return <LoadingBlock />;
  if (!entry.data) return <ErrorBanner error={entry.error ?? 'Not found'} title="Could not load release" onRetry={() => void entry.refetch()} />;
  const e = entry.data;
  const evals = [...e.evaluations].sort((a, b) => Number(b.matched) - Number(a.matched) || a.rule_name.localeCompare(b.rule_name));

  return (
    <>
      <PageHeader
        title="Match inspector"
        subtitle={<span className="break">{e.title}</span>}
        actions={
          <Link to="/releases" className="btn btn-ghost">
            All releases
          </Link>
        }
      />
      <Card>
        <div className="decision">
          <StatusBadge status={e.outcome} />
          <span>{e.outcome_summary ?? (e.outcome === 'unprocessed' ? 'Not processed yet.' : '')}</span>
        </div>
        <div className="small muted">
          Feed {e.feed_name} · published <TimeAgo iso={e.published_at} fallback="unknown" /> · first seen <TimeAgo iso={e.first_seen_at} /> · processed{' '}
          <TimeAgo iso={e.processed_at} fallback="never" /> · size {formatBytes(e.size_bytes)}
          {e.is_historical ? ' · historical' : ''}
        </div>
      </Card>
      <div className="grid-2">
        <Card title="Parsed metadata">
          <p className="small muted">Parsing is best-effort; rules decide using these values plus the raw title.</p>
          <ParsedTable parsed={e.parsed} />
        </Card>
        <LinksCard e={e} />
      </div>
      <Card
        title={`Rule evaluations (${evals.length})`}
        actions={
          <button type="button" className="btn btn-sm" disabled={evaluate.isPending} onClick={() => evaluate.mutate(e.id)}>
            {evaluate.isPending ? 'Re-evaluating…' : 'Re-evaluate'}
          </button>
        }
      >
        <p className="small muted">Re-evaluate runs all current rules again and stores the results. It never sends anything and does not change the outcome.</p>
        <ErrorBanner error={evaluate.error} title="Re-evaluate failed" />
        {evals.length === 0 ? (
          <p className="muted">No evaluations stored. There may be no enabled rules for monitored series; use Re-evaluate to run all rules now.</p>
        ) : (
          <div className="stack">
            {evals.map((ev) => (
              <EvaluationBlock key={ev.rule_id} ev={ev} />
            ))}
          </div>
        )}
      </Card>
      <GrabCard key={e.id} e={e} />
      <Card title="Downloads for this release">
        <DownloadsTable items={e.downloads} emptyText="This release has not been sent to qBittorrent." />
      </Card>
    </>
  );
}
