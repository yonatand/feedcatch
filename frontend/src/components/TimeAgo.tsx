import { useEffect, useState } from 'react';

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['year', 365 * 24 * 3600],
  ['month', 30 * 24 * 3600],
  ['week', 7 * 24 * 3600],
  ['day', 24 * 3600],
  ['hour', 3600],
  ['minute', 60],
  ['second', 1],
];

let rtf: Intl.RelativeTimeFormat | null = null;
function getRtf(): Intl.RelativeTimeFormat {
  if (!rtf) rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });
  return rtf;
}

export function relativeTime(iso: string, now: number = Date.now()): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  const diffSec = Math.round((t - now) / 1000);
  const abs = Math.abs(diffSec);
  if (abs < 10) return 'just now';
  for (const [unit, secs] of UNITS) {
    if (abs >= secs || unit === 'second') {
      return getRtf().format(Math.round(diffSec / secs), unit);
    }
  }
  return iso;
}

export function absoluteTime(iso: string): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  return new Date(t).toLocaleString();
}

/** Relative time ("5 minutes ago") with the absolute local time in the title tooltip. */
export function TimeAgo({ iso, fallback = '—' }: { iso: string | null | undefined; fallback?: string }) {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!iso) return undefined;
    const id = window.setInterval(() => setTick((x) => x + 1), 30_000);
    return () => window.clearInterval(id);
  }, [iso]);
  if (!iso) return <span className="muted">{fallback}</span>;
  return (
    <time dateTime={iso} title={`${absoluteTime(iso)} (${iso})`} className="nowrap">
      {relativeTime(iso)}
    </time>
  );
}
