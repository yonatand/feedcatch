import type { Season, SeasonIn, Series, SeriesIn } from '../api/types';

export function seriesToIn(s: Series): SeriesIn {
  return {
    name: s.name,
    aliases: [...s.aliases],
    monitored: s.monitored,
    season_folder_format: s.season_folder_format,
    path_override: s.path_override,
    category_override: s.category_override,
  };
}

export function seasonToIn(s: Season): SeasonIn {
  return {
    season_number: s.season_number,
    monitored: s.monitored,
    path_override: s.path_override,
    episode_min: s.episode_min,
    episode_max: s.episode_max,
    absolute_min: s.absolute_min,
    absolute_max: s.absolute_max,
  };
}

export function emptySeason(n = 1): SeasonIn {
  return {
    season_number: n,
    monitored: true,
    path_override: null,
    episode_min: null,
    episode_max: null,
    absolute_min: null,
    absolute_max: null,
  };
}

export function rangeText(min: number | null, max: number | null): string {
  if (min === null && max === null) return '—';
  return `${min ?? '…'}–${max ?? '…'}`;
}

export function sortSeasons(s: readonly Season[]): Season[] {
  return [...s].sort((a, b) => a.season_number - b.season_number);
}
