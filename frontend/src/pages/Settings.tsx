import { useEffect, useState } from 'react';
import { useSaveSettings, useSettings } from '../api/hooks';
import type { AppSettings, AppSettingsIn } from '../api/types';
import { ErrorBanner, Notice } from '../components/ErrorBanner';
import { CheckField, FormField } from '../components/FormField';
import { NumberInput } from '../components/NumberInput';
import { LoadingBlock } from '../components/Spinner';
import { Badge } from '../components/StatusBadge';
import { Card, PageHeader } from '../components/Table';

function toIn(s: AppSettings): AppSettingsIn {
  return {
    media_base_path: s.media_base_path,
    default_season_folder_format: s.default_season_folder_format,
    duplicate_policy: s.duplicate_policy,
    allow_private_feed_hosts: s.allow_private_feed_hosts,
    feed_fetch_timeout_seconds: s.feed_fetch_timeout_seconds,
    log_retention_days: s.log_retention_days,
    auto_search_missing: s.auto_search_missing ?? false,
    search_interval_hours: s.search_interval_hours ?? 24,
    metadata_refresh_hours: s.metadata_refresh_hours ?? 12,
    search_delay_seconds: s.search_delay_seconds ?? 3,
  };
}

export default function Settings() {
  const settings = useSettings();
  const save = useSaveSettings();
  const [v, setV] = useState<AppSettingsIn | null>(null);
  const [saved, setSaved] = useState(false);
  // TMDB key is write-only: only sent when typed (or "" when the user asked to clear it).
  const [tmdbKey, setTmdbKey] = useState('');
  const [tmdbClear, setTmdbClear] = useState(false);

  useEffect(() => {
    if (settings.data && v === null) setV(toIn(settings.data));
  }, [settings.data, v]);

  if (settings.isLoading) return <LoadingBlock />;
  if (!settings.data || !v) return <ErrorBanner error={settings.error ?? 'No data'} title="Could not load settings" onRetry={() => void settings.refetch()} />;
  const sources = settings.data.sources;
  const env = (k: string) => sources[k] === 'env';
  const envBadge = (k: string) => (env(k) ? <Badge tone="purple" title="Set by environment variable">env</Badge> : null);
  const set = <K extends keyof AppSettingsIn>(k: K, val: AppSettingsIn[K]) => {
    setSaved(false);
    setV({ ...v, [k]: val });
  };
  const baseOk = v.media_base_path.startsWith('/') && !v.media_base_path.includes('\\');
  const keySet = settings.data.tmdb_api_key_set;
  const tmdbBody: Pick<AppSettingsIn, 'tmdb_api_key'> = tmdbClear ? { tmdb_api_key: '' } : tmdbKey.trim() !== '' ? { tmdb_api_key: tmdbKey.trim() } : {};

  return (
    <>
      <PageHeader title="Settings" subtitle="Application-wide defaults. Saved in the database and kept across restarts." />
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate(
            {
              ...v,
              media_base_path: v.media_base_path.trim(),
              default_season_folder_format: v.default_season_folder_format.trim(),
              ...tmdbBody,
            },
            {
              onSuccess: (d) => {
                setV(toIn(d));
                setTmdbKey('');
                setTmdbClear(false);
                setSaved(true);
              },
            },
          );
        }}
      >
        <Card title="Paths">
          <FormField
            label="Media base path"
            badge={envBadge('media_base_path')}
            error={baseOk ? null : 'Must be an absolute POSIX path (starting with /).'}
            help={
              <>
                As seen by qBittorrent — not by this container. Save paths are built as <code>base / series / season folder</code> and handed to qBittorrent;
                this app never accesses the folder.
              </>
            }
          >
            {(id) => (
              <input
                id={id}
                type="text"
                className="mono"
                required
                disabled={env('media_base_path')}
                value={v.media_base_path}
                onChange={(e) => set('media_base_path', e.target.value)}
                placeholder="/home/qbittorrent-nox/media"
              />
            )}
          </FormField>
          <FormField
            label="Default season folder format"
            badge={envBadge('default_season_folder_format')}
            help={
              <>
                Used for new series. Tokens: <code>{'{season}'}</code>, <code>{'{season:02d}'}</code>, <code>{'{season:03d}'}</code>, <code>{'{series}'}</code>.
              </>
            }
          >
            {(id) => (
              <input
                id={id}
                type="text"
                className="mono"
                disabled={env('default_season_folder_format')}
                value={v.default_season_folder_format}
                onChange={(e) => set('default_season_folder_format', e.target.value)}
              />
            )}
          </FormField>
        </Card>
        <Card title="Matching">
          <FormField
            label="Duplicate policy"
            badge={envBadge('duplicate_policy')}
            help={
              v.duplicate_policy === 'one_per_episode'
                ? 'At most one active download per episode. Further releases for the same episode are recorded as duplicates. A manual force-grab can override.'
                : 'Allow upgrades: a manual (non-forced) grab may replace an episode whose earlier download failed.'
            }
          >
            {(id) => (
              <select
                id={id}
                disabled={env('duplicate_policy')}
                value={v.duplicate_policy}
                onChange={(e) => set('duplicate_policy', e.target.value === 'allow_upgrades' ? 'allow_upgrades' : 'one_per_episode')}
              >
                <option value="one_per_episode">One per episode (default)</option>
                <option value="allow_upgrades">Allow upgrades</option>
              </select>
            )}
          </FormField>
        </Card>
        <Card title="Feeds and network">
          <CheckField
            label="Allow private / LAN feed hosts"
            checked={v.allow_private_feed_hosts}
            disabled={env('allow_private_feed_hosts')}
            badge={envBadge('allow_private_feed_hosts')}
            onChange={(b) => set('allow_private_feed_hosts', b)}
            help="Off by default. Feed URLs resolving to private, loopback or link-local addresses are rejected to prevent server-side request forgery."
          />
          {v.allow_private_feed_hosts ? (
            <Notice kind="warning">
              SSRF risk: with this enabled, anyone who can edit feeds can make this server request internal addresses (router, qBittorrent, cloud metadata).
              Only enable it on a trusted network for a self-hosted feed.
            </Notice>
          ) : null}
          <div className="form-grid">
            <FormField label="Feed fetch timeout (seconds)" badge={envBadge('feed_fetch_timeout_seconds')}>
              {(id) => (
                <NumberInput
                  id={id}
                  min={1}
                  max={300}
                  disabled={env('feed_fetch_timeout_seconds')}
                  value={v.feed_fetch_timeout_seconds}
                  onChange={(n) => set('feed_fetch_timeout_seconds', n ?? 20)}
                />
              )}
            </FormField>
            <FormField label="Activity log retention (days)" badge={envBadge('log_retention_days')}>
              {(id) => (
                <NumberInput id={id} min={1} max={3650} disabled={env('log_retention_days')} value={v.log_retention_days} onChange={(n) => set('log_retention_days', n ?? 30)} />
              )}
            </FormField>
          </div>
        </Card>
        <Card title="Episodes and release search">
          <CheckField
            label="Automatically search for missing episodes"
            checked={v.auto_search_missing}
            disabled={env('auto_search_missing')}
            badge={envBadge('auto_search_missing')}
            onChange={(b) => set('auto_search_missing', b)}
            help="Off by default. When on, every search interval each monitored season with missing episodes is searched through the feeds’ search URL templates, and only episodes whose status is “missing” (aired, nothing downloaded) are grabbed, with the normal duplicate rules. Requires episode metadata for the season."
          />
          <div className="form-grid">
            <FormField
              label="Search interval (hours)"
              badge={envBadge('search_interval_hours')}
              help="How often the automatic missing-episode search runs (min 1, default 24)."
            >
              {(id) => (
                <NumberInput
                  id={id}
                  min={1}
                  max={8760}
                  disabled={env('search_interval_hours')}
                  value={v.search_interval_hours}
                  onChange={(n) => set('search_interval_hours', n ?? 24)}
                />
              )}
            </FormField>
            <FormField
              label="Metadata refresh (hours)"
              badge={envBadge('metadata_refresh_hours')}
              help="How often episode titles and air dates are refreshed for monitored seasons linked to a metadata entry (min 1, default 12)."
            >
              {(id) => (
                <NumberInput
                  id={id}
                  min={1}
                  max={8760}
                  disabled={env('metadata_refresh_hours')}
                  value={v.metadata_refresh_hours}
                  onChange={(n) => set('metadata_refresh_hours', n ?? 12)}
                />
              )}
            </FormField>
            <FormField
              label="Delay between search fetches (seconds)"
              badge={envBadge('search_delay_seconds')}
              help="Pause between consecutive search-feed requests, to be polite to the feed host (default 3)."
            >
              {(id) => (
                <NumberInput
                  id={id}
                  min={0}
                  max={120}
                  disabled={env('search_delay_seconds')}
                  value={v.search_delay_seconds}
                  onChange={(n) => set('search_delay_seconds', n ?? 3)}
                />
              )}
            </FormField>
          </div>
        </Card>
        <Card title="Metadata providers">
          <p className="small muted">
            AniList (anime) needs no key. TMDB (TV shows) needs a free API key: create one at{' '}
            <a href="https://www.themoviedb.org/settings/api" target="_blank" rel="noopener noreferrer">
              themoviedb.org/settings/api
            </a>{' '}
            and paste the v3 API key or the v4 read access token.
          </p>
          <FormField
            label="TMDB API key"
            badge={
              <>
                {envBadge('tmdb_api_key')}{' '}
                {keySet && !tmdbClear ? (
                  <Badge tone="green">key set</Badge>
                ) : tmdbClear ? (
                  <Badge tone="orange">will be cleared</Badge>
                ) : (
                  <Badge tone="grey">not set</Badge>
                )}
              </>
            }
            help={
              env('tmdb_api_key')
                ? 'Set by the TMDB_API_KEY environment variable; change it there.'
                : keySet
                  ? 'Stored encrypted and never shown. Type a new key to replace it, or clear it.'
                  : 'Stored encrypted and never shown again after saving.'
            }
          >
            {(id) => (
              <div className="inline-edit">
                <input
                  id={id}
                  type="password"
                  autoComplete="off"
                  spellCheck={false}
                  disabled={env('tmdb_api_key') || tmdbClear}
                  value={tmdbKey}
                  placeholder={keySet ? '•••••••• (unchanged)' : 'paste API key'}
                  onChange={(e) => {
                    setSaved(false);
                    setTmdbKey(e.target.value);
                  }}
                />
                {keySet && !env('tmdb_api_key') ? (
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={() => {
                      setSaved(false);
                      setTmdbKey('');
                      setTmdbClear((c) => !c);
                    }}
                  >
                    {tmdbClear ? 'Keep key' : 'Clear'}
                  </button>
                ) : null}
              </div>
            )}
          </FormField>
        </Card>
        {(settings.data.warnings ?? []).length > 0 ? (
          <Notice kind="warning">
            <ul className="plain-list">
              {(settings.data.warnings ?? []).map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          </Notice>
        ) : null}
        <ErrorBanner error={save.error} title="Could not save settings" />
        {saved ? <Notice kind="success">Settings saved.</Notice> : null}
        <div className="form-actions">
          <button type="submit" className="btn btn-primary" disabled={save.isPending || !baseOk}>
            {save.isPending ? 'Saving…' : 'Save settings'}
          </button>
        </div>
      </form>
    </>
  );
}
