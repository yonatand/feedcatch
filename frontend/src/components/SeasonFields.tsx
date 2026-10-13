import { useEffect, useState } from 'react';
import { errorMessage } from '../api/client';
import { previewPath } from '../api/hooks';
import type { SeasonIn } from '../api/types';
import { CheckField, FormField } from './FormField';
import { NumberInput } from './NumberInput';
import { PathPreview } from './PathPreview';

type PreviewArgs = {
  name: string;
  season_folder_format: string;
  path_override: string | null;
  season_number: number | null;
  season_path_override: string | null;
};

/** Debounced call to POST /api/series/preview-path. */
export function usePathPreview(args: PreviewArgs, delay = 350) {
  const [state, setState] = useState<{ path: string | null; error: string | null; loading: boolean }>({
    path: null,
    error: null,
    loading: false,
  });
  const { name, season_folder_format, path_override, season_number, season_path_override } = args;

  useEffect(() => {
    if (name.trim() === '' || season_number === null) {
      setState({ path: null, error: name.trim() === '' ? 'Enter a series name to compute the path.' : 'Enter a season number.', loading: false });
      return undefined;
    }
    let cancelled = false;
    setState((s) => ({ ...s, loading: true }));
    const t = window.setTimeout(() => {
      previewPath({
        name: name.trim(),
        season_folder_format,
        path_override: path_override && path_override.trim() !== '' ? path_override.trim() : null,
        season_number,
        season_path_override: season_path_override && season_path_override.trim() !== '' ? season_path_override.trim() : null,
      })
        .then((r) => {
          if (!cancelled) setState({ path: r.save_path, error: null, loading: false });
        })
        .catch((e: unknown) => {
          if (!cancelled) setState({ path: null, error: errorMessage(e), loading: false });
        });
    }, delay);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
  }, [name, season_folder_format, path_override, season_number, season_path_override, delay]);

  return state;
}

type Props = {
  value: SeasonIn;
  onChange: (v: SeasonIn) => void;
  /** series-level info for the live path preview */
  seriesName: string;
  seasonFolderFormat: string;
  seriesPathOverride: string | null;
};

export function SeasonFields({ value, onChange, seriesName, seasonFolderFormat, seriesPathOverride }: Props) {
  const set = <K extends keyof SeasonIn>(k: K, v: SeasonIn[K]) => onChange({ ...value, [k]: v });
  const [seasonNum, setSeasonNum] = useState<number | null>(value.season_number);
  const preview = usePathPreview({
    name: seriesName,
    season_folder_format: seasonFolderFormat,
    path_override: seriesPathOverride,
    season_number: seasonNum,
    season_path_override: value.path_override,
  });

  return (
    <div className="season-fields">
      <div className="form-grid">
        <FormField label="Season number" help="0 for specials.">
          {(id) => (
            <NumberInput
              id={id}
              min={0}
              required
              value={seasonNum}
              onChange={(n) => {
                setSeasonNum(n);
                if (n !== null) set('season_number', n);
              }}
            />
          )}
        </FormField>
        <CheckField label="Season monitored" checked={value.monitored} onChange={(b) => set('monitored', b)} />
        <FormField label="Episode range (season numbering)" help="Optional. e.g. 1–51 for titles like S02E05 or “Season 2 - 05”.">
          {(id) => (
            <div className="range-inputs">
              <NumberInput id={id} min={0} placeholder="min" value={value.episode_min} onChange={(n) => set('episode_min', n)} />
              <span aria-hidden="true">–</span>
              <NumberInput min={0} placeholder="max" value={value.episode_max} onChange={(n) => set('episode_max', n)} />
            </div>
          )}
        </FormField>
        <FormField
          label="Absolute episode range"
          help={
            <>
              Optional. Maps seasonless titles like “- 171” to this season: episode = absolute − min + 1.
              {value.absolute_min !== null ? ` (${value.absolute_min} → E01)` : ''}
            </>
          }
        >
          {(id) => (
            <div className="range-inputs">
              <NumberInput id={id} min={0} placeholder="min" value={value.absolute_min} onChange={(n) => set('absolute_min', n)} />
              <span aria-hidden="true">–</span>
              <NumberInput min={0} placeholder="max" value={value.absolute_max} onChange={(n) => set('absolute_max', n)} />
            </div>
          )}
        </FormField>
        <FormField label="Season path override" help="Optional absolute path (as seen by qBittorrent) replacing the whole computed path." className="span-2">
          {(id) => (
            <input
              id={id}
              type="text"
              className="mono"
              value={value.path_override ?? ''}
              placeholder="/home/qbittorrent-nox/media/Some Show/Season 02"
              onChange={(e) => set('path_override', e.target.value === '' ? null : e.target.value)}
            />
          )}
        </FormField>
      </div>
      <PathPreview path={preview.path} loading={preview.loading} error={preview.error} />
    </div>
  );
}
