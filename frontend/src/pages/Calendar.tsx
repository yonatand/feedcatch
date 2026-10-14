import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useCalendar } from '../api/hooks';
import type { CalendarItem } from '../api/types';
import { CheckField } from '../components/FormField';
import { Cover } from '../components/Cover';
import { ErrorBanner } from '../components/ErrorBanner';
import { LoadingBlock, Spinner } from '../components/Spinner';
import { StatusBadge } from '../components/StatusBadge';
import { Card, EmptyState, PageHeader } from '../components/Table';
import { seasonEpisode } from '../lib/format';

const DAY = 24 * 3600 * 1000;

function startOfLocalDay(t: number): number {
  const d = new Date(t);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

function dayKey(iso: string): string {
  const d = new Date(Date.parse(iso));
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function dayLabel(iso: string, today: number): string {
  const t = startOfLocalDay(Date.parse(iso));
  const diff = Math.round((t - today) / DAY);
  const date = new Date(t).toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' });
  if (diff === 0) return `Today · ${date}`;
  if (diff === 1) return `Tomorrow · ${date}`;
  if (diff === -1) return `Yesterday · ${date}`;
  return date;
}

function timeLabel(iso: string): string {
  return new Date(Date.parse(iso)).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

function CalendarRow({ it }: { it: CalendarItem }) {
  return (
    <li className="cal-row">
      <Cover url={it.cover_url} alt={it.series_name} size="xs" />
      <div className="cal-main">
        <div>
          <Link to={`/series/${it.series_id}`}>
            <strong>{it.series_name}</strong>
          </Link>{' '}
          <span className="mono small">{seasonEpisode(it.season_number, it.episode_number)}</span>
          {!it.monitored ? (
            <>
              {' '}
              <StatusBadge status="unmonitored" />
            </>
          ) : null}
        </div>
        <div className="small muted truncate">{it.title ?? `Episode ${it.episode_number}`}</div>
      </div>
      <div className="cal-side">
        <time dateTime={it.air_date} className="small nowrap">
          {timeLabel(it.air_date)}
        </time>
        <StatusBadge status={it.status} />
      </div>
    </li>
  );
}

export default function Calendar() {
  // Window anchored to "today": past 7 days, next 14 days; prev/next shift by a week.
  const [today] = useState(() => startOfLocalDay(Date.now()));
  const [shift, setShift] = useState(0);
  const [monitoredOnly, setMonitoredOnly] = useState(true);
  const fromT = today - 7 * DAY + shift * 7 * DAY;
  const toT = today + 14 * DAY + shift * 7 * DAY;
  const from = new Date(fromT).toISOString();
  const to = new Date(toT).toISOString();
  const cal = useCalendar(from, to);

  const groups = useMemo(() => {
    const items = (cal.data?.items ?? []).filter((i) => !monitoredOnly || i.monitored);
    const map = new Map<string, CalendarItem[]>();
    for (const it of items) {
      const k = dayKey(it.air_date);
      const arr = map.get(k);
      if (arr) arr.push(it);
      else map.set(k, [it]);
    }
    return [...map.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([k, list]) => ({ key: k, items: [...list].sort((a, b) => a.air_date.localeCompare(b.air_date)) }));
  }, [cal.data, monitoredOnly]);

  const fmt = (t: number) => new Date(t).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  const todayKey = dayKey(new Date(today).toISOString());

  return (
    <>
      <PageHeader
        title="Calendar"
        subtitle="Episode air dates from the linked metadata (AniList / TMDB) with their download status, in your local time."
        actions={
          <>
            <button type="button" className="btn" onClick={() => setShift((s) => s - 1)}>
              ‹ Previous week
            </button>
            {shift !== 0 ? (
              <button type="button" className="btn btn-ghost" onClick={() => setShift(0)}>
                Today
              </button>
            ) : null}
            <button type="button" className="btn" onClick={() => setShift((s) => s + 1)}>
              Next week ›
            </button>
          </>
        }
      />
      <div className="toolbar">
        <span className="small muted">
          {fmt(fromT)} – {fmt(toT - 1)}
        </span>
        <CheckField label="Monitored only" checked={monitoredOnly} onChange={setMonitoredOnly} />
        {cal.isFetching && !cal.isLoading ? <Spinner label="Updating…" inline /> : null}
      </div>
      <ErrorBanner error={cal.error} title="Could not load the calendar" onRetry={() => void cal.refetch()} />
      {cal.isLoading ? (
        <LoadingBlock />
      ) : groups.length === 0 ? (
        <Card>
          <EmptyState title="Nothing airs in this window">
            Episodes appear here once a season is linked to a metadata entry and its episodes are fetched (series page → “Refresh metadata”).
            {monitoredOnly ? ' Unmonitored series are hidden.' : null}
          </EmptyState>
        </Card>
      ) : (
        groups.map((g) => (
          <section key={g.key} className={`card cal-day${g.key === todayKey ? ' cal-today' : ''}`} aria-label={dayLabel(g.items[0].air_date, today)}>
            <h2 className="cal-day-title">{dayLabel(g.items[0].air_date, today)}</h2>
            <ul className="cal-list">
              {g.items.map((it) => (
                <CalendarRow key={`${it.season_id}-${it.episode_number}`} it={it} />
              ))}
            </ul>
          </section>
        ))
      )}
    </>
  );
}
