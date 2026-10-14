import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ApiError } from '../api/client';
import { useGrabConfirm, useGrabPreview } from '../api/hooks';
import type { Download, GrabPreview } from '../api/types';
import { seasonEpisode, truncateMiddle } from '../lib/format';
import { ConfirmInline } from './ConfirmInline';
import { CopyButton } from './CopyButton';
import { ErrorBanner, Notice } from './ErrorBanner';
import { CheckField } from './FormField';
import { PathPreview } from './PathPreview';
import { Badge, StatusBadge } from './StatusBadge';

export type GrabTarget = { season_id: number; episode_number: number };

export function GrabResult({ d }: { d: Download }) {
  return (
    <Notice kind={d.status === 'failed' ? 'error' : d.status === 'path_mismatch' ? 'warning' : 'success'}>
      Download #{d.id}: <StatusBadge status={d.status} /> {d.last_error ? <span>— {d.last_error}</span> : null}{' '}
      <Link to="/downloads">View downloads →</Link>
    </Notice>
  );
}

export function GrabPreviewView({ p }: { p: GrabPreview }) {
  return (
    <div className="grab-preview">
      <PathPreview path={p.save_path} label="Will be sent with savepath" note />
      <dl className="kv">
        <div className="kv-row">
          <dt>Category</dt>
          <dd>{p.category ?? <span className="muted">none</span>}</dd>
        </div>
        <div className="kv-row">
          <dt>Source</dt>
          <dd>
            <Badge tone="green">{p.source_url_kind}</Badge>{' '}
            <code className="path-sm" title={p.source_url}>
              {truncateMiddle(p.source_url, 64)}
            </code>{' '}
            <CopyButton text={p.source_url} />
          </dd>
        </div>
        <div className="kv-row">
          <dt>Infohash</dt>
          <dd>{p.infohash ? <code className="path-sm">{p.infohash}</code> : <span className="muted">unknown</span>}</dd>
        </div>
      </dl>
      {p.warnings.length > 0 ? (
        <Notice kind="warning">
          <ul className="plain-list">
            {p.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </Notice>
      ) : null}
      {p.duplicate_of ? (
        <Notice kind="warning">
          <strong>Duplicate:</strong> download #{p.duplicate_of.id} ({p.duplicate_of.entry_title}) already covers{' '}
          {p.duplicate_of.series_name} {seasonEpisode(p.duplicate_of.season_number, p.duplicate_of.episode_number)} with status{' '}
          <StatusBadge status={p.duplicate_of.status} />.
        </Notice>
      ) : null}
    </div>
  );
}

type Props = {
  entryId: number;
  /** null = target not chosen yet (button disabled) */
  target: GrabTarget | null;
  /** Fetch the preview immediately on mount (used when the user already clicked "Grab" on a row). */
  autoPreview?: boolean;
  onSent?: (d: Download) => void;
  /** Extra action next to "Cancel" in the review step; when given, Cancel also calls it. */
  onCancel?: () => void;
};

/**
 * The grab preview -> confirm flow shared by the match inspector and the release-search drawer:
 * "Grab — preview first" fetches a GrabPreview (confirm:false), shows save path, category, source,
 * warnings and duplicate info, then "Confirm send" (confirm:true), with an explicit force step for duplicates.
 */
export function GrabFlow({ entryId, target, autoPreview = false, onSent, onCancel }: Props) {
  const previewM = useGrabPreview();
  const confirmM = useGrabConfirm();
  const [force, setForce] = useState(false);
  const [result, setResult] = useState<Download | null>(null);

  const requestPreview = () => {
    if (!target) return;
    setResult(null);
    previewM.mutate({ entryId, body: { ...target, force: false } });
  };

  // Any change to the target invalidates a shown preview.
  const key = target ? `${entryId}:${target.season_id}:${target.episode_number}` : '';
  const lastKey = useRef<string | null>(null);
  useEffect(() => {
    const prev = lastKey.current;
    if (prev === key) return; // StrictMode re-run: nothing changed
    lastKey.current = key;
    if (prev === null) {
      if (autoPreview) requestPreview();
      return;
    }
    previewM.reset();
    confirmM.reset();
    setForce(false);
  }, [key]);

  const preview = previewM.data;
  const dup = preview?.duplicate_of ?? null;
  const conflict = confirmM.error instanceof ApiError && confirmM.error.status === 409;

  const send = () => {
    if (!target) return;
    confirmM.mutate(
      { entryId, body: { ...target, force: dup !== null && force } },
      {
        onSuccess: (d) => {
          setResult(d);
          previewM.reset();
          onSent?.(d);
        },
      },
    );
  };

  return (
    <div className="grab-flow">
      {result ? <GrabResult d={result} /> : null}
      {!preview ? (
        <div className="form-actions">
          <button type="button" className="btn" disabled={!target || previewM.isPending} onClick={requestPreview}>
            {previewM.isPending ? 'Preparing…' : result ? 'Grab again — preview first' : 'Grab — preview first'}
          </button>
          {onCancel && !result ? (
            <button type="button" className="btn btn-ghost" onClick={onCancel}>
              Cancel
            </button>
          ) : null}
        </div>
      ) : null}
      <ErrorBanner error={previewM.error} title="Preview failed" />
      {preview ? (
        <div className="subcard">
          <h3>Review before sending</h3>
          <GrabPreviewView p={preview} />
          {dup ? (
            <div className="force-box">
              <CheckField
                label={<strong>Force grab despite the duplicate</strong>}
                checked={force}
                onChange={setForce}
                help="qBittorrent will receive a second torrent for the same episode. Existing torrents are not removed or changed."
              />
            </div>
          ) : null}
          <ErrorBanner
            error={conflict ? 'Rejected as a duplicate (409). Tick “Force grab” to send anyway.' : confirmM.error}
            title="Send failed"
          />
          <div className="form-actions">
            {dup ? (
              <ConfirmInline
                label="Force send to qBittorrent"
                confirmLabel="Yes, send duplicate"
                message="Send a duplicate torrent?"
                size="md"
                disabled={!force}
                pending={confirmM.isPending}
                onConfirm={send}
              />
            ) : (
              <button type="button" className="btn btn-primary" disabled={confirmM.isPending} onClick={send}>
                {confirmM.isPending ? 'Sending…' : 'Confirm send to qBittorrent'}
              </button>
            )}
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => {
                previewM.reset();
                onCancel?.();
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
