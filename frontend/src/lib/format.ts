export function formatBytes(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return '—';
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v < 10 && i > 0 ? 1 : 0)} ${units[i]}`;
}

export function pad2(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—';
  return String(n).padStart(2, '0');
}

export function seasonEpisode(season: number | null | undefined, episode: number | null | undefined): string {
  if (season === null || season === undefined) {
    return episode === null || episode === undefined ? '—' : `E${pad2(episode)}`;
  }
  return `S${pad2(season)}${episode === null || episode === undefined ? '' : `E${pad2(episode)}`}`;
}

/** "a, b , ,c" -> ["a","b","c"] */
export function splitList(s: string): string[] {
  return s
    .split(',')
    .map((x) => x.trim())
    .filter((x) => x.length > 0);
}

export function joinList(a: readonly string[] | null | undefined): string {
  return (a ?? []).join(', ');
}

/** Empty string -> null, else trimmed string. */
export function nullIfEmpty(s: string): string | null {
  const t = s.trim();
  return t === '' ? null : t;
}

/** Empty string -> null, else integer (NaN -> null). */
export function intOrNull(s: string): number | null {
  const t = s.trim();
  if (t === '') return null;
  const n = Number(t);
  return Number.isFinite(n) ? Math.trunc(n) : null;
}

export function numOrNull(s: string): number | null {
  const t = s.trim();
  if (t === '') return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

export function numToStr(n: number | null | undefined): string {
  return n === null || n === undefined ? '' : String(n);
}

export function truncateMiddle(s: string, max = 60): string {
  if (s.length <= max) return s;
  const keep = Math.floor((max - 1) / 2);
  return `${s.slice(0, keep)}…${s.slice(s.length - keep)}`;
}

export function normPath(p: string | null | undefined): string {
  if (!p) return '';
  return p.length > 1 ? p.replace(/\/+$/, '') : p;
}

export function percent(p: number | null | undefined): string {
  if (p === null || p === undefined) return '—';
  return `${Math.round(p * 1000) / 10}%`;
}
