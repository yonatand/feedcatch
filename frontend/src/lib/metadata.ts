import type { MetadataProvider, MetadataProviderName } from '../api/types';

type Tone = 'grey' | 'green' | 'red' | 'blue' | 'orange' | 'purple' | 'yellow';

const FALLBACK_LABELS: Record<string, string> = { anilist: 'AniList', tmdb: 'TMDB' };

/** Provider label from the providers list, else a built-in fallback, else the raw name. */
export function providerLabel(name: string | null | undefined, providers?: readonly MetadataProvider[]): string {
  if (!name) return 'metadata provider';
  return providers?.find((p) => p.name === name)?.label ?? FALLBACK_LABELS[name] ?? name;
}

export function isProviderName(v: string): v is MetadataProviderName {
  return v === 'anilist' || v === 'tmdb';
}

/** Original title shown as a secondary line only when it differs from the main title. */
export function mediaSubtitle(m: { title: string | null; original_title: string | null }): string | null {
  return m.original_title && m.original_title !== m.title ? m.original_title : null;
}

const FORMAT_LABELS: Record<string, string> = { TV_SHORT: 'TV short', MOVIE: 'Movie', SPECIAL: 'Special', MUSIC: 'Music' };

export function formatLabel(f: string | null | undefined): string | null {
  if (!f) return null;
  return FORMAT_LABELS[f] ?? f;
}

// AniList (upper snake) and TMDB (title case) status values.
const STATUS: Record<string, { label: string; tone: Tone }> = {
  RELEASING: { label: 'airing', tone: 'green' },
  FINISHED: { label: 'finished', tone: 'blue' },
  NOT_YET_RELEASED: { label: 'upcoming', tone: 'yellow' },
  CANCELLED: { label: 'cancelled', tone: 'red' },
  HIATUS: { label: 'hiatus', tone: 'orange' },
  'Returning Series': { label: 'airing', tone: 'green' },
  Ended: { label: 'ended', tone: 'blue' },
  Canceled: { label: 'cancelled', tone: 'red' },
  'In Production': { label: 'in production', tone: 'yellow' },
  Planned: { label: 'planned', tone: 'yellow' },
  Pilot: { label: 'pilot', tone: 'yellow' },
};

export function mediaStatus(s: string | null | undefined): { label: string; tone: Tone } {
  if (!s) return { label: 'unknown', tone: 'grey' };
  return STATUS[s] ?? { label: s.toLowerCase().replace(/_/g, ' '), tone: 'grey' };
}

const RELATION_LABELS: Record<string, string> = {
  SEQUEL: 'Sequel',
  PREQUEL: 'Prequel',
  PARENT: 'Parent',
  SIDE_STORY: 'Side story',
  ALTERNATIVE: 'Alternative',
  SPIN_OFF: 'Spin-off',
};

export function relationLabel(r: string): string {
  return RELATION_LABELS[r] ?? r.toLowerCase().replace(/_/g, ' ');
}

/** "TV · 2017 · 170 eps" */
export function metaLine(m: { format: string | null; year: number | null; episodes: number | null }): string {
  const parts: string[] = [];
  const f = formatLabel(m.format);
  if (f) parts.push(f);
  if (m.year !== null) parts.push(String(m.year));
  parts.push(m.episodes !== null ? `${m.episodes} ep${m.episodes === 1 ? '' : 's'}` : '? eps');
  return parts.join(' · ');
}

/** Display title; providers may omit it. */
export function mediaTitle(m: { title: string | null } | null | undefined): string {
  return m?.title || 'Untitled';
}

/** Only follow http(s) links coming from the API. */
export function safeUrl(u: string | null | undefined): string | null {
  if (!u) return null;
  return /^https?:\/\//i.test(u) ? u : null;
}
