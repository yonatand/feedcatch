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
  };
}

export default function Settings() {
  const settings = useSettings();
  const save = useSaveSettings();
  const [v, setV] = useState<AppSettingsIn | null>(null);
  const [saved, setSaved] = useState(false);

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

  return (
    <>
      <PageHeader title="Settings" subtitle="Application-wide defaults. Saved in the database and kept across restarts." />
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate(
            { ...v, media_base_path: v.media_base_path.trim(), default_season_folder_format: v.default_season_folder_format.trim() },
            {
              onSuccess: (d) => {
                setV(toIn(d));
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
