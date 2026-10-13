import type { AnilistInfo, AnilistMedia, AnilistRelated } from '../api/types';

type Tone = 'grey' | 'green' | 'red' | 'blue' | 'orange' | 'purple' | 'yellow';

type Titled = Pick<AnilistMedia | AnilistRelated | AnilistInfo, 'title_english' | 'title_romaji'>;

/** English title when present, else romaji. */
export function anilistTitle(m: Titled): string {
  return m.title_english || m.title_romaji || 'Untitled';
}

/** Romaji shown as a secondary line only when it differs from the main title. */
export function anilistSubtitle(m: Titled): string | null {
  return m.title_english && m.title_romaji && m.title_romaji !== m.title_english ? m.title_romaji : null;
}

const FORMAT_LABELS: Record<string, string> = { TV_SHORT: 'TV short', MOVIE: 'Movie', SPECIAL: 'Special', MUSIC: 'Music' };

export function formatLabel(f: string | null | undefined): string {
  if (!f) return '—';
  return FORMAT_LABELS[f] ?? f;
}

const STATUS: Record<string, { label: string; tone: Tone }> = {
  RELEASING: { label: 'airing', tone: 'green' },
  FINISHED: { label: 'finished', tone: 'blue' },
  NOT_YET_RELEASED: { label: 'upcoming', tone: 'yellow' },
  CANCELLED: { label: 'cancelled', tone: 'red' },
  HIATUS: { label: 'hiatus', tone: 'orange' },
};

export function anilistStatus(s: string | null | undefined): { label: string; tone: Tone } {
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
export function metaLine(m: { format: string | null; season_year: number | null; episodes: number | null }): string {
  const parts = [formatLabel(m.format)];
  if (m.season_year !== null) parts.push(String(m.season_year));
  parts.push(m.episodes !== null ? `${m.episodes} ep${m.episodes === 1 ? '' : 's'}` : '? eps');
  return parts.join(' · ');
}

/** Only follow http(s) links coming from the API. */
export function safeUrl(u: string | null | undefined): string | null {
  if (!u) return null;
  return /^https?:\/\//i.test(u) ? u : null;
}
