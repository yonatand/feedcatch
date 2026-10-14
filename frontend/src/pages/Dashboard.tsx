import { Link } from 'react-router-dom';
import { useDashboard } from '../api/hooks';
import type { CalendarItem, Dashboard as DashboardData } from '../api/types';
import { Cover } from '../components/Cover';
import { DownloadsTable } from '../components/DownloadsTable';
import { EntriesTable } from '../components/EntriesTable';
import { ErrorBanner, Notice } from '../components/ErrorBanner';
import { LoadingBlock } from '../components/Spinner';
import { Badge, StatusBadge } from '../components/StatusBadge';
import { Card, EmptyRow, PageHeader, TableWrap } from '../components/Table';
import { TimeAgo } from '../components/TimeAgo';
import { seasonEpisode } from '../lib/format';

function Stat({ label, value, to, tone }: { label: string; value: React.ReactNode; to?: string; tone?: 'bad' | 'warn' }) {
  const inner = (
    <>
      <div className={`stat-value${tone ? ` stat-${tone}` : ''}`}>{value}</div>
      <div className="stat-label">{label}</div>
    </>
  );
  return to ? (
    <Link to={to} className="stat card">
      {inner}
    </Link>
  ) : (
    <div className="stat card">{inner}</div>
  );
}

function QbitCard({ qbit }: { qbit: DashboardData['qbit'] }) {
  const t = qbit.last_test;
  return (
    <Card title="qBittorrent" actions={<Link to="/qbittorrent">Configure</Link>}>
      {!qbit.configured ? (
        <p>
          <StatusBadge status="not configured" tone="orange" /> Set the Web API URL and credentials before anything can be sent.
        </p>
      ) : (
        <dl className="kv">
          <div className="kv-row">
            <dt>Configured</dt>
            <dd>
              <Badge tone="green">yes</Badge>
            </dd>
          </div>
          <div className="kv-row">
            <dt>Last test</dt>
            <dd>
              {t ? (
                <>
                  <StatusBadge status={t.ok ? 'ok' : 'failed'} /> <TimeAgo iso={t.at} />
                </>
              ) : (
                <span className="muted">never tested</span>
              )}
            </dd>
          </div>
          {t?.version ? (
            <div className="kv-row">
              <dt>Version</dt>
              <dd>
                {t.version}
                {t.api_version ? <span className="muted"> (API {t.api_version})</span> : null}
              </dd>
            </div>
          ) : null}
          {t?.error ? (
            <div className="kv-row">
              <dt>Error</dt>
              <dd className="err-text">{t.error}</dd>
            </div>
          ) : null}
          {t && t.warnings.length > 0 ? (
            <div className="kv-row">
              <dt>Warnings</dt>
              <dd className="warn-text">{t.warnings.length}</dd>
            </div>
          ) : null}
        </dl>
      )}
    </Card>
  );
}

function OnboardingCard({ data }: { data: DashboardData }) {
  const steps = [
    {
      done: data.feeds.length > 0,
      to: '/feeds',
      title: 'Add a feed',
      text: 'An RSS/Atom feed of releases. Presets: AnimeTosho or Nyaa (anime), or any custom feed.',
    },
    {
      done: data.qbit.configured,
      to: '/qbittorrent',
      title: 'Connect qBittorrent',
      text: 'Web API URL and credentials of your existing qBittorrent; test the connection.',
    },
    {
      done: data.counts.series_total > 0,
      to: '/series/new',
      title: 'Add a series',
      text: 'Search AniList (anime) or TMDB (TV), define seasons and a matching rule, then monitor it.',
    },
  ];
  return (
    <Card title="Get started">
      <ol className="onboarding">
        {steps.map((s, i) => (
          <li key={s.to} className={s.done ? 'done' : ''}>
            <span className="step-num" aria-hidden="true">
              {s.done ? '✓' : i + 1}
            </span>
            <div>
              <Link to={s.to}>
                <strong>{s.title}</strong>
              </Link>
              {s.done ? <span className="sr-only"> (done)</span> : null}
              <div className="small muted">{s.text}</div>
            </div>
          </li>
        ))}
      </ol>
    </Card>
  );
}

/** Short local weekday, date and time, e.g. "Sat 17 Oct, 17:00". */
function upcomingLabel(iso: string): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  return new Date(t).toLocaleString(undefined, { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

function UpcomingCard({ items }: { items: CalendarItem[] }) {
  return (
    <Card title="Upcoming (7 days)" actions={<Link to="/calendar">Calendar</Link>}>
      {items.length === 0 ? (
        <p className="muted small">No episodes of monitored series air in the next 7 days (or no season has episode metadata yet).</p>
      ) : (
        <ul className="cal-list">
          {items.map((it) => (
            <li key={`${it.season_id}-${it.episode_number}`} className="cal-row">
              <Cover url={it.cover_url} alt={it.series_name} size="xs" />
              <div className="cal-main">
                <div>
                  <Link to={`/series/${it.series_id}`}>{it.series_name}</Link>{' '}
                  <span className="mono small">{seasonEpisode(it.season_number, it.episode_number)}</span>
                </div>
                <div className="small muted truncate">{it.title ?? `Episode ${it.episode_number}`}</div>
              </div>
              <div className="cal-side">
                <span className="small nowrap">
                  {upcomingLabel(it.air_date)} · <TimeAgo iso={it.air_date} />
                </span>
                <StatusBadge status={it.status} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function SchedulerCard({ s }: { s: DashboardData['scheduler'] }) {
  return (
    <Card title="Scheduler">
      <dl className="kv">
        <div className="kv-row">
          <dt>State</dt>
          <dd>
            <StatusBadge status={s.running ? 'running' : 'stopped'} tone={s.running ? 'green' : 'red'} />
          </dd>
        </div>
        <div className="kv-row">
          <dt>Next feed poll</dt>
          <dd>
            <TimeAgo iso={s.next_feed_poll_at} fallback="none scheduled" />
          </dd>
        </div>
      </dl>
    </Card>
  );
}

export default function Dashboard() {
  const { data, error, isLoading, refetch } = useDashboard();
  if (isLoading) return <LoadingBlock />;
  if (!data) return <ErrorBanner error={error ?? 'No data'} title="Could not load dashboard" onRetry={() => void refetch()} />;
  const c = data.counts;
  const errorFeeds = data.feeds.filter((f) => f.enabled && f.last_status === 'error').length;
  const onboarding = data.feeds.length === 0 || c.series_total === 0;
  const wanted = c.wanted ?? 0;

  return (
    <>
      <PageHeader title="Dashboard" subtitle="Feed health, matches and qBittorrent submissions. Refreshes every 30 s." />
      <ErrorBanner error={error} title="Refresh failed" />
      {errorFeeds > 0 ? (
        <Notice kind="warning">
          {errorFeeds} enabled feed{errorFeeds > 1 ? 's are' : ' is'} failing. See <Link to="/feeds">Feeds</Link>.
        </Notice>
      ) : null}
      {onboarding ? <OnboardingCard data={data} /> : null}

      <div className="stats">
        <Stat label="Series monitored" value={`${c.series_monitored} / ${c.series_total}`} to="/series" />
        <Stat label="Active rules" value={c.rules_active} to="/rules" />
        <Stat label="Releases (24 h)" value={c.entries_24h} to="/releases" />
        <Stat label="Sent to qBit (24 h)" value={c.downloads_submitted_24h} to="/downloads?status=submitted" />
        <Stat label="Pending" value={c.downloads_pending} to="/downloads?status=pending" tone={c.downloads_pending > 0 ? 'warn' : undefined} />
        <Stat label="Failed" value={c.downloads_failed} to="/downloads?status=failed" tone={c.downloads_failed > 0 ? 'bad' : undefined} />
        <Stat label="Wanted episodes" value={wanted} to="/wanted" tone={wanted > 0 ? 'warn' : undefined} />
      </div>

      <UpcomingCard items={data.upcoming ?? []} />

      <div className="grid-3">
        <Card title="Feed health" actions={<Link to="/feeds">Manage</Link>} className="span-1">
          {data.feeds.length === 0 ? (
            <p className="muted">
              No feeds yet. <Link to="/feeds">Add one</Link>.
            </p>
          ) : (
            <ul className="feed-health">
              {data.feeds.map((f) => (
                <li key={f.id}>
                  <div className="feed-health-row">
                    <span className="truncate" title={f.url}>
                      {f.name}
                    </span>
                    {f.enabled ? <StatusBadge status={f.last_status} /> : <StatusBadge status="disabled" />}
                  </div>
                  <div className="small muted">
                    checked <TimeAgo iso={f.last_checked_at} fallback="never" /> · every {f.poll_interval_minutes} min
                  </div>
                  {f.last_error ? (
                    <div className="small err-text" title={f.last_error}>
                      {f.last_error}
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </Card>
        <QbitCard qbit={data.qbit} />
        <SchedulerCard s={data.scheduler} />
      </div>

      <Card title="Failed submissions" actions={<Link to="/downloads?status=failed">All failed</Link>}>
        <DownloadsTable items={data.failed_downloads} compact emptyText="No failed or mismatched submissions." />
      </Card>

      <Card title="Recent downloads" actions={<Link to="/downloads">All downloads</Link>}>
        <DownloadsTable items={data.recent_downloads} compact emptyText="Nothing has been sent to qBittorrent yet." />
      </Card>

      <Card title="Recent releases" actions={<Link to="/releases">All releases</Link>}>
        {data.recent_entries.length === 0 ? (
          <TableWrap>
            <table className="table">
              <tbody>
                <EmptyRow colSpan={1}>No releases seen yet. Feeds are polled on their interval, or use “Poll now” on the Feeds page.</EmptyRow>
              </tbody>
            </table>
          </TableWrap>
        ) : (
          <EntriesTable items={data.recent_entries} compact />
        )}
      </Card>
    </>
  );
}
