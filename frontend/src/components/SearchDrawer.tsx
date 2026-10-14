import { Fragment, useEffect, useId, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ApiError } from '../api/client';
import { useGrabMissing, useSeasonSearch } from '../api/hooks';
import type { Candidate, EpisodeStatus, SearchRejected, SearchResult } from '../api/types';
import { formatBytes, pad2 } from '../lib/format';
import { useIsMobile } from '../lib/useMedia';
import { ConditionsTable } from './ConditionsTable';
import { Drawer } from './Drawer';
import { ErrorBanner, Notice } from './ErrorBanner';
import { GrabFlow } from './GrabFlow';
import { Spinner } from './Spinner';
import { Badge, StatusBadge } from './StatusBadge';
import { TableWrap } from './Table';
import { TimeAgo } from './TimeAgo';

type Props = {
  seasonId: number;
  /** e.g. "Black Clover — Season 2" */
  title: string;
  /** Show only this episode's candidates initially (null = all). */
  episode?: number | null;
  /** Reuse an earlier result instead of searching on open. */
  initialResult?: SearchResult | null;
  onResult?: (r: SearchResult) => void;
  onClose: () => void;
};

type Group = { episode: number; status: EpisodeStatus; alreadyHave: boolean; candidates: Candidate[] };

/** Statuses grab-missing acts on (unknown only matters when the season has no metadata; the server decides). */
const GRABBABLE: ReadonlySet<EpisodeStatus> = new Set<EpisodeStatus>(['missing', 'unknown']);

function groupCandidates(cands: readonly Candidate[]): Group[] {
  const map = new Map<number, Group>();
  for (const c of cands) {
    let g = map.get(c.episode_number);
    if (!g) {
      g = { episode: c.episode_number, status: c.episode_status, alreadyHave: c.already_have, candidates: [] };
      map.set(c.episode_number, g);
    }
    g.candidates.push(c); // server order: rule priority desc, then published desc
  }
  return [...map.values()].sort((a, b) => a.episode - b.episode);
}

function feedsText(f: SearchResult['feeds_searched']): string {
  return f.length ? f.join(', ') : 'none';
}

function candKey(c: Candidate): string {
  return `${c.entry.id}:${c.episode_number}`;
}

function CandidateRows({ g, seasonId, open, setOpen }: { g: Group; seasonId: number; open: string | null; setOpen: (k: string | null) => void }) {
  return (
    <>
      <tr className="group-row">
        <th colSpan={6} scope="rowgroup">
          <span className="group-row-inner">
            <GroupHead g={g} />
          </span>
        </th>
      </tr>
      {g.candidates.map((c) => {
        const k = candKey(c);
        const e = c.entry;
        const passed = c.conditions.filter((x) => x.passed).length;
        const noLink = !e.magnet_url && !e.torrent_url;
        return (
          <Fragment key={k}>
            <tr>
              <td className="title-cell">
                <Link to={`/releases/${e.id}`} title={e.title}>
                  {e.title}
                </Link>
                <div className="row-sub">
                  {e.parsed.group ? <Badge tone="purple">{e.parsed.group}</Badge> : null}
                  <span className="small muted">{e.feed_name}</span>
                </div>
              </td>
              <td className="nowrap">{e.parsed.resolution ?? <span className="muted">—</span>}</td>
              <td className="num nowrap">{formatBytes(e.size_bytes)}</td>
              <td>
                <TimeAgo iso={e.published_at} fallback="unknown" />
              </td>
              <td>
                <div className="nowrap">{c.rule_name}</div>
                <details className="cond-details">
                  <summary className="small">
                    {passed}/{c.conditions.length} conditions
                  </summary>
                  <ConditionsTable conditions={c.conditions} compact />
                </details>
                {c.save_path ? (
                  <code className="path-sm break" title="qBittorrent save path">
                    {c.save_path}
                  </code>
                ) : (
                  <span className="small muted">save path computed on grab</span>
                )}
              </td>
              <td className="nowrap">
                <button
                  type="button"
                  className={`btn btn-sm${g.alreadyHave ? '' : ' btn-primary'}`}
                  disabled={noLink}
                  title={noLink ? 'No magnet or .torrent link' : undefined}
                  aria-expanded={open === k}
                  onClick={() => setOpen(open === k ? null : k)}
                >
                  {open === k ? 'Close' : 'Grab'}
                </button>
              </td>
            </tr>
            {open === k ? (
              <tr className="detail-row">
                <td colSpan={6}>
                  {g.alreadyHave ? (
                    <Notice kind="info">This episode is already downloaded, downloading or pending; the preview will show the duplicate.</Notice>
                  ) : null}
                  <GrabFlow entryId={e.id} target={{ season_id: seasonId, episode_number: c.episode_number }} autoPreview onCancel={() => setOpen(null)} />
                </td>
              </tr>
            ) : null}
          </Fragment>
        );
      })}
    </>
  );
}

function GroupHead({ g }: { g: Group }) {
  return (
    <>
      <strong>E{pad2(g.episode)}</strong> <StatusBadge status={g.status} />
      {g.alreadyHave ? <Badge tone="blue">already have</Badge> : null}
      <span className="muted small">
        {g.candidates.length} candidate{g.candidates.length === 1 ? '' : 's'}
      </span>
    </>
  );
}

/** Mobile: one section per episode, one card per candidate; the grab flow opens inside the card. */
function CandidateCards({ groups, seasonId, open, setOpen }: { groups: Group[]; seasonId: number; open: string | null; setOpen: (k: string | null) => void }) {
  // The review's own Cancel closes it; only after a successful send (no Cancel left) is a Close shown, at the bottom.
  const [sent, setSent] = useState<string | null>(null);
  const toggle = (k: string | null) => {
    setSent(null);
    setOpen(k);
  };
  return (
    <div className="cand-groups">
      {groups.map((g) => (
        <section key={g.episode} className="cand-group" aria-label={`Episode ${g.episode}`}>
          <div className="cand-group-head">
            <GroupHead g={g} />
          </div>
          <ul className="mcards">
            {g.candidates.map((c) => {
              const k = candKey(c);
              const e = c.entry;
              const passed = c.conditions.filter((x) => x.passed).length;
              const noLink = !e.magnet_url && !e.torrent_url;
              return (
                <li key={k} className={`mcard${open === k ? ' mcard-open' : ''}`}>
                  <div className="mcard-title break">
                    <Link to={`/releases/${e.id}`}>{e.title}</Link>
                  </div>
                  <div className="mcard-meta">
                    {e.parsed.group ? <Badge tone="purple">{e.parsed.group}</Badge> : null}
                    {e.parsed.resolution ? <Badge>{e.parsed.resolution}</Badge> : null}
                    <span className="small">{formatBytes(e.size_bytes)}</span>
                    <span className="small">
                      <TimeAgo iso={e.published_at} fallback="unknown" />
                    </span>
                    <span className="small muted">{e.feed_name}</span>
                  </div>
                  <div className="mcard-body">
                    <div className="small">
                      Rule: <strong>{c.rule_name}</strong>
                    </div>
                    <details className="cond-details">
                      <summary className="small">
                        {passed}/{c.conditions.length} conditions
                      </summary>
                      <ConditionsTable conditions={c.conditions} compact />
                    </details>
                    {c.save_path ? (
                      <code className="path-sm break" title="qBittorrent save path">
                        {c.save_path}
                      </code>
                    ) : (
                      <span className="small muted">save path computed on grab</span>
                    )}
                  </div>
                  {open !== k ? (
                    <div className="mcard-actions">
                      <button
                        type="button"
                        className={`btn${g.alreadyHave ? '' : ' btn-primary'}`}
                        disabled={noLink}
                        title={noLink ? 'No magnet or .torrent link' : undefined}
                        aria-expanded={false}
                        onClick={() => toggle(k)}
                      >
                        {noLink ? 'No torrent link' : 'Grab'}
                      </button>
                    </div>
                  ) : (
                    <div className="mcard-detail">
                      {g.alreadyHave ? (
                        <Notice kind="info">This episode is already downloaded, downloading or pending; the preview will show the duplicate.</Notice>
                      ) : null}
                      <GrabFlow
                        entryId={e.id}
                        target={{ season_id: seasonId, episode_number: c.episode_number }}
                        autoPreview
                        onCancel={() => toggle(null)}
                        onSent={() => setSent(k)}
                      />
                      {sent === k ? (
                        <div className="form-actions">
                          <button type="button" className="btn btn-ghost" onClick={() => toggle(null)}>
                            Close
                          </button>
                        </div>
                      ) : null}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}

function sxe(r: SearchRejected): string {
  if (r.episode_number === null) return r.season_number === null ? '—' : `S${pad2(r.season_number)}`;
  return `${r.season_number === null ? '' : `S${pad2(r.season_number)}`}E${pad2(r.episode_number)}`;
}

function RejectedRow({ r }: { r: SearchRejected }) {
  return (
    <tr>
      <td className="title-cell">
        <Link to={`/releases/${r.entry_id}`} title={r.title}>
          {r.title}
        </Link>
        <div className="small muted">
          parsed as: <span className="mono">{r.parsed_title || '—'}</span>
          {r.alt_titles.length > 0 ? <> · aka {r.alt_titles.join(' / ')}</> : null}
        </div>
      </td>
      <td className="nowrap">{sxe(r)}</td>
      <td>
        <RejectedChecks r={r} />
      </td>
    </tr>
  );
}

function RejectedChecks({ r }: { r: SearchRejected }) {
  return r.failed_checks.length === 0 ? (
    <span className="small muted">no enabled rule</span>
  ) : (
    <ul className="plain-list small rejected-checks">
      {r.failed_checks.map((f, i) => (
        <li key={`${f.rule_name}-${i}`} className="break">
          <strong>{f.rule_name}</strong> · <span className="mono">{f.check}</span>: {f.detail}
        </li>
      ))}
    </ul>
  );
}

function RejectedTable({ rows }: { rows: readonly SearchRejected[] }) {
  const mobile = useIsMobile();
  if (mobile) {
    return (
      <ul className="mcards rejected-cards">
        {rows.map((r) => (
          <li key={r.entry_id} className="mcard">
            <div className="mcard-title break">
              <Link to={`/releases/${r.entry_id}`}>{r.title}</Link>
            </div>
            <div className="mcard-meta">
              <span className="mono small">{sxe(r)}</span>
              <span className="small muted break">
                parsed as: <span className="mono">{r.parsed_title || '—'}</span>
                {r.alt_titles.length > 0 ? <> · aka {r.alt_titles.join(' / ')}</> : null}
              </span>
            </div>
            <div className="mcard-body">
              <div className="mcard-label">Why rejected</div>
              <RejectedChecks r={r} />
            </div>
          </li>
        ))}
      </ul>
    );
  }
  return (
    <TableWrap>
      <table className="table table-compact rejected-table">
        <thead>
          <tr>
            <th>Release</th>
            <th>Ep</th>
            <th>Why rejected (first failing check per rule)</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <RejectedRow key={r.entry_id} r={r} />
          ))}
        </tbody>
      </table>
    </TableWrap>
  );
}

/** Fetched releases that matched no rule, with the first failing check per rule. Collapsed by default. */
function RejectedSection({ rejected, total, onlyEp }: { rejected: readonly SearchRejected[]; total: number; onlyEp: number | null }) {
  const [open, setOpen] = useState(false);
  const [showOthers, setShowOthers] = useState(false);
  const shown = rejected.slice(0, 100);
  const inScope = onlyEp === null ? shown : shown.filter((r) => r.episode_number === onlyEp);
  const others = onlyEp === null ? [] : shown.filter((r) => r.episode_number !== onlyEp);
  return (
    <div className="rejected-section">
      <button type="button" className="link-btn" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? '▾' : '▸'} Fetched releases that matched no rule ({total})
      </button>
      {open ? (
        <div className="stack">
          {total > shown.length ? (
            <p className="small muted">
              Showing the first {shown.length} of {total}.
            </p>
          ) : null}
          {shown.length === 0 ? (
            <p className="small muted">Every fetched release matched a rule.</p>
          ) : onlyEp === null ? (
            <RejectedTable rows={shown} />
          ) : (
            <>
              {inScope.length > 0 ? <RejectedTable rows={inScope} /> : <p className="small muted">No rejected release was parsed as episode {onlyEp}.</p>}
              {others.length > 0 ? (
                <>
                  <button type="button" className="link-btn small" aria-expanded={showOthers} onClick={() => setShowOthers(!showOthers)}>
                    {showOthers ? 'Hide' : 'Show'} {others.length} other rejected release{others.length === 1 ? '' : 's'}
                  </button>
                  {showOthers ? <RejectedTable rows={others} /> : null}
                </>
              ) : null}
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}

/**
 * Release search for one season (POST /api/seasons/{id}/search): queries used, feeds searched,
 * candidates grouped per episode with the shared grab preview -> confirm flow, and "Grab all missing".
 */
export function SearchDrawer({ seasonId, title, episode = null, initialResult = null, onResult, onClose }: Props) {
  const queryId = useId();
  const search = useSeasonSearch();
  const grabMissing = useGrabMissing();
  const mobile = useIsMobile();
  const [query, setQuery] = useState('');
  const [usedQuery, setUsedQuery] = useState('');
  const [result, setResult] = useState<SearchResult | null>(initialResult);
  const [onlyEp, setOnlyEp] = useState<number | null>(episode);
  const [open, setOpen] = useState<string | null>(null);
  const [confirmAll, setConfirmAll] = useState(false);

  const run = (q: string) => {
    const t = q.trim();
    setOpen(null);
    setConfirmAll(false);
    grabMissing.reset();
    search.mutate(
      { seasonId, body: t ? { query: t } : {} },
      {
        onSuccess: (r) => {
          setResult(r);
          setUsedQuery(t);
          onResult?.(r);
        },
      },
    );
  };

  // Search once on open (a ref survives StrictMode's double effect, so only one request is sent).
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    if (!initialResult) run('');
  }, []);

  const groups = useMemo(() => groupCandidates(result?.candidates ?? []), [result]);
  const visible = onlyEp === null ? groups : groups.filter((g) => g.episode === onlyEp);
  const planned = groups.filter((g) => GRABBABLE.has(g.status) && !g.alreadyHave && g.candidates.length > 0);
  const noTemplate = search.error instanceof ApiError && search.error.status === 400;

  const startGrabAll = () => {
    grabMissing.reset();
    setConfirmAll(true);
  };
  const sendGrabAll = () =>
    grabMissing.mutate({ seasonId, body: usedQuery ? { query: usedQuery } : {} }, { onSuccess: () => setConfirmAll(false) });

  // Mobile: the primary action lives in the sheet's sticky footer (desktop keeps it inline in the body).
  // Nothing to grab: no footer, so the sheet keeps its full height for the candidates.
  // A grab review open in a card brings its own Confirm/Cancel: no second sticky bar under it.
  const footer = result && open === null && (confirmAll || planned.length > 0) ? (
    confirmAll ? (
      <>
        <button type="button" className="btn btn-primary" disabled={grabMissing.isPending} onClick={sendGrabAll}>
          {grabMissing.isPending ? 'Sending…' : `Confirm: send ${planned.length} to qBittorrent`}
        </button>
        <button type="button" className="btn btn-ghost" disabled={grabMissing.isPending} onClick={() => setConfirmAll(false)}>
          Cancel
        </button>
      </>
    ) : (
      <button
        type="button"
        className="btn btn-primary"
        disabled={planned.length === 0 || grabMissing.isPending}
        title={planned.length === 0 ? 'No missing episode has a candidate' : undefined}
        onClick={startGrabAll}
      >
        Grab all missing ({planned.length})
      </button>
    )
  ) : null;

  return (
    <Drawer title={`Search releases: ${title}`} onClose={onClose} wide footer={footer} footerMobileOnly>
      <p className="small muted">
        Searches every enabled feed that has a search URL template, then evaluates the results against this series’ enabled rules (monitoring is ignored:
        searching is explicit). Found releases are stored as “searched” and never auto-grabbed; nothing is sent until you confirm.
      </p>
      <div className="inline-form">
        <label htmlFor={queryId} className="small">
          Custom query (optional)
        </label>
        <input
          id={queryId}
          type="search"
          value={query}
          placeholder="default: series name + aliases (+ S02)"
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              if (!search.isPending) run(query);
            }
          }}
        />
        <button type="button" className="btn btn-primary" disabled={search.isPending} onClick={() => run(query)}>
          {search.isPending ? 'Searching…' : result ? 'Search again' : 'Search'}
        </button>
      </div>
      {search.isPending ? <Spinner label="Searching feeds… (the server pauses a few seconds between feed fetches)" /> : null}
      <ErrorBanner error={search.error} title="Search failed" />
      {noTemplate ? (
        <Notice kind="info">
          Release search needs at least one enabled feed with a <strong>search URL template</strong> (e.g. AnimeTosho:{' '}
          <code>https://feed.animetosho.net/rss2?q={'{query}'}</code>). Set it on the <Link to="/feeds">Feeds</Link> page.
        </Notice>
      ) : null}

      {result ? (
        <div className="stack">
          <dl className="kv">
            <div className="kv-row">
              <dt>Queries</dt>
              <dd>
                {result.queries.length ? (
                  <span className="badges">
                    {result.queries.map((q) => (
                      <code key={q} className="path-sm">
                        {q}
                      </code>
                    ))}
                  </span>
                ) : (
                  <span className="muted">none</span>
                )}
                {usedQuery ? <span className="small muted"> (custom)</span> : null}
              </dd>
            </div>
            <div className="kv-row">
              <dt>Feeds searched</dt>
              <dd>{feedsText(result.feeds_searched)}</dd>
            </div>
            <div className="kv-row">
              <dt>Items fetched</dt>
              <dd>
                {result.fetched} · {result.candidates.length} matching candidate{result.candidates.length === 1 ? '' : 's'} for {groups.length} episode
                {groups.length === 1 ? '' : 's'}
              </dd>
            </div>
          </dl>
          {result.errors.length > 0 ? (
            <Notice kind="warning">
              <strong>
                {result.errors.length} problem{result.errors.length === 1 ? '' : 's'} during the search:
              </strong>
              <ul className="plain-list">
                {result.errors.map((er, i) => (
                  <li key={i} className="break">
                    {er}
                  </li>
                ))}
              </ul>
            </Notice>
          ) : null}

          <div className="search-toolbar">
            {onlyEp !== null ? (
              <span className="small">
                Showing episode {onlyEp} only.{' '}
                <button type="button" className="link-btn" onClick={() => setOnlyEp(null)}>
                  Show all episodes
                </button>
              </span>
            ) : (
              <span className="small muted">All episodes</span>
            )}
            {!confirmAll ? (
              <button
                type="button"
                className="btn d-only"
                disabled={planned.length === 0 || grabMissing.isPending}
                title={planned.length === 0 ? 'No missing episode has a candidate' : undefined}
                onClick={startGrabAll}
              >
                Grab all missing ({planned.length})
              </button>
            ) : null}
          </div>

          {confirmAll ? (
            <div className="subcard" role="group" aria-label="Confirm grab all missing">
              <h3>Send {planned.length} release{planned.length === 1 ? '' : 's'} to qBittorrent?</h3>
              <p className="small muted">
                The first candidate per missing episode (as listed below). The server runs the search again{usedQuery ? ' with the same query' : ''}, applies
                the normal duplicate rules and skips anything that is no longer missing.
              </p>
              <TableWrap>
                <table className="table table-compact">
                  <thead>
                    <tr>
                      <th>Ep</th>
                      <th>Release</th>
                      <th>Save path</th>
                    </tr>
                  </thead>
                  <tbody>
                    {planned.map((g) => (
                      <tr key={g.episode}>
                        <td className="nowrap" data-label="Ep">
                          E{pad2(g.episode)}
                        </td>
                        <td className="title-cell cell-main">{g.candidates[0].entry.title}</td>
                        <td className="cell-wide" data-label="Save path">
                          {g.candidates[0].save_path ? <code className="path-sm break">{g.candidates[0].save_path}</code> : <span className="muted">—</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableWrap>
              <div className="form-actions d-only">
                <button type="button" className="btn btn-primary" disabled={grabMissing.isPending} onClick={sendGrabAll}>
                  {grabMissing.isPending ? 'Sending…' : `Confirm: send ${planned.length} to qBittorrent`}
                </button>
                <button type="button" className="btn btn-ghost" disabled={grabMissing.isPending} onClick={() => setConfirmAll(false)}>
                  Cancel
                </button>
              </div>
            </div>
          ) : null}
          <ErrorBanner error={grabMissing.error} title="Grab all missing failed" />
          {grabMissing.data ? (
            <Notice kind={grabMissing.data.grabbed.length > 0 ? 'success' : 'info'}>
              <strong>
                Sent {grabMissing.data.grabbed.length}, skipped {grabMissing.data.skipped.length}.
              </strong>
              {grabMissing.data.grabbed.length > 0 ? (
                <ul className="plain-list">
                  {grabMissing.data.grabbed.map((d) => (
                    <li key={d.id}>
                      E{pad2(d.episode_number)} <StatusBadge status={d.status} /> <span className="break">{d.entry_title}</span>
                    </li>
                  ))}
                </ul>
              ) : null}
              {grabMissing.data.skipped.length > 0 ? (
                <ul className="plain-list small">
                  {grabMissing.data.skipped.map((s) => (
                    <li key={s.episode_number}>
                      E{pad2(s.episode_number)}: {s.reason}
                    </li>
                  ))}
                </ul>
              ) : null}
              {(grabMissing.data.errors ?? []).length > 0 ? (
                <ul className="plain-list small err-text">
                  {(grabMissing.data.errors ?? []).map((er, i) => (
                    <li key={i}>{er}</li>
                  ))}
                </ul>
              ) : null}{' '}
              <Link to="/downloads">View downloads →</Link>
            </Notice>
          ) : null}

          {visible.length === 0 ? (
            <p className="muted">
              {onlyEp !== null && groups.length > 0
                ? `No candidates for episode ${onlyEp}.`
                : result.rejected
                  ? 'No release passed your rules. Open the list below to see why each fetched release was rejected.'
                  : 'No matching releases found. Check the rule filters (group, resolution, keywords) or try a custom query.'}
            </p>
          ) : mobile ? (
            <CandidateCards groups={visible} seasonId={seasonId} open={open} setOpen={setOpen} />
          ) : (
            <TableWrap>
              <table className="table search-table">
                <thead>
                  <tr>
                    <th>Release</th>
                    <th>Res</th>
                    <th className="num">Size</th>
                    <th>Published</th>
                    <th>Rule · save path</th>
                    <th>
                      <span className="sr-only">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((g) => (
                    <CandidateRows key={g.episode} g={g} seasonId={seasonId} open={open} setOpen={setOpen} />
                  ))}
                </tbody>
              </table>
            </TableWrap>
          )}
          {result.rejected ? (
            <RejectedSection
              key={`${result.fetched}:${result.rejected_total ?? result.rejected.length}`}
              rejected={result.rejected}
              total={result.rejected_total ?? result.rejected.length}
              onlyEp={onlyEp}
            />
          ) : null}
        </div>
      ) : null}
    </Drawer>
  );
}
