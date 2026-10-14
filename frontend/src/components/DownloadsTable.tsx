import { Link } from 'react-router-dom';
import { errorMessage } from '../api/client';
import { useDeleteDownload } from '../api/hooks';
import type { Download } from '../api/types';
import { ConfirmInline } from './ConfirmInline';
import { normPath, percent, seasonEpisode } from '../lib/format';
import { useIsMobile } from '../lib/useMedia';
import { Badge, StatusBadge } from './StatusBadge';
import { EmptyRow, TableWrap } from './Table';
import { TimeAgo } from './TimeAgo';

export function pathsMismatch(d: Download): boolean {
  return d.qbit_save_path !== null && normPath(d.qbit_save_path) !== normPath(d.save_path);
}

export function SavePaths({ d }: { d: Download }) {
  const mismatch = pathsMismatch(d) || d.status === 'path_mismatch';
  return (
    <div className={`paths-pair${mismatch ? ' mismatch' : ''}`}>
      <div>
        <span className="path-tag">sent</span> <code className="path-sm">{d.save_path}</code>
      </div>
      <div>
        <span className="path-tag">qBit</span>{' '}
        {d.qbit_save_path ? <code className="path-sm">{d.qbit_save_path}</code> : <span className="muted small">not reported</span>}
      </div>
      {mismatch ? <div className="small warn-text">qBittorrent reports a different save path</div> : null}
    </div>
  );
}

export const DELETE_DOWNLOAD_MESSAGE =
  "Removes feedcatch's record only; the torrent stays in qBittorrent. The episode becomes missing again.";

/** "Delete" + inline confirm for one download record (DELETE /api/downloads/{id}); never touches qBittorrent. */
export function DeleteDownloadButton({ id, what, onDeleted }: { id: number; what: string; onDeleted?: () => void }) {
  const del = useDeleteDownload();
  return (
    <>
      <ConfirmInline
        label="Delete"
        confirmLabel="Delete record"
        ariaLabel={`Delete download record for ${what}`}
        message={DELETE_DOWNLOAD_MESSAGE}
        pending={del.isPending}
        wrap
        onConfirm={() => del.mutate(id, { onSuccess: onDeleted })}
      />
      {del.error ? (
        <span className="small err-text" role="alert">
          Delete failed: {errorMessage(del.error)}
        </span>
      ) : null}
    </>
  );
}

type Props = {
  items: Download[];
  compact?: boolean;
  renderActions?: (d: Download) => React.ReactNode;
  emptyText?: string;
};

function DownloadStatusInfo({ d }: { d: Download }) {
  return (
    <>
      {d.last_error ? (
        <div className="small err-text" title={d.last_error}>
          {d.last_error}
        </div>
      ) : null}
      {d.status === 'pending' && d.next_retry_at ? (
        <div className="small muted">
          retry <TimeAgo iso={d.next_retry_at} />
        </div>
      ) : null}
    </>
  );
}

function RuleLine({ d }: { d: Download }) {
  return (
    <div className="small muted">
      {d.rule_name ? `rule: ${d.rule_name}` : 'manual grab'}
      {d.forced ? (
        <>
          {' '}
          <Badge tone="orange">forced</Badge>
        </>
      ) : null}
    </div>
  );
}

/** Mobile card list: series + episode on top, release title, status/meta line, save paths, actions. */
function DownloadCards({ items, compact, renderActions, emptyText }: Required<Pick<Props, 'items' | 'emptyText'>> & Omit<Props, 'items' | 'emptyText'>) {
  if (items.length === 0) return <p className="mcards-empty muted">{emptyText}</p>;
  return (
    <ul className="mcards downloads-cards">
      {items.map((d) => (
        <li key={d.id} className="mcard">
          <div className="mcard-title">
            <Link to={`/series/${d.series_id}`}>{d.series_name}</Link>{' '}
            <span className="mono small muted">{seasonEpisode(d.season_number, d.episode_number)}</span>
          </div>
          <div className="mcard-sub break">
            <Link to={`/releases/${d.entry_id}`}>{d.entry_title}</Link>
          </div>
          <div className="mcard-meta">
            <StatusBadge status={d.status} />
            <TimeAgo iso={d.created_at} />
            {!compact && d.qbit_state ? (
              <span className="small">
                qBit: {d.qbit_state}
                {d.qbit_progress !== null ? ` · ${percent(d.qbit_progress)}` : ''}
              </span>
            ) : null}
            {!compact && d.attempts > 0 ? <span className="small muted">{d.attempts} attempt{d.attempts === 1 ? '' : 's'}</span> : null}
          </div>
          <RuleLine d={d} />
          <DownloadStatusInfo d={d} />
          <div className="mcard-body">
            {compact ? <code className="path-sm">{d.save_path}</code> : <SavePaths d={d} />}
          </div>
          {!compact && renderActions ? <div className="mcard-actions">{renderActions(d)}</div> : null}
        </li>
      ))}
    </ul>
  );
}

export function DownloadsTable({ items, compact, renderActions, emptyText = 'No downloads yet.' }: Props) {
  const mobile = useIsMobile();
  if (mobile) return <DownloadCards items={items} compact={compact} renderActions={renderActions} emptyText={emptyText} />;
  const cols = compact ? 5 : renderActions ? 8 : 7;
  return (
    <TableWrap>
      <table className="table">
        <thead>
          <tr>
            <th>When</th>
            <th>Series</th>
            <th>Release</th>
            <th>Status</th>
            {compact ? <th>Save path</th> : null}
            {!compact ? <th>Save path (sent vs qBittorrent)</th> : null}
            {!compact ? <th>qBit state</th> : null}
            {!compact ? <th className="num">Attempts</th> : null}
            {!compact && renderActions ? <th>Actions</th> : null}
          </tr>
        </thead>
        <tbody>
          {items.length === 0 ? <EmptyRow colSpan={cols}>{emptyText}</EmptyRow> : null}
          {items.map((d) => (
            <tr key={d.id}>
              <td>
                <TimeAgo iso={d.created_at} />
              </td>
              <td className="nowrap">
                <Link to={`/series/${d.series_id}`}>{d.series_name}</Link>{' '}
                <span className="muted">{seasonEpisode(d.season_number, d.episode_number)}</span>
              </td>
              <td className="title-cell">
                <Link to={`/releases/${d.entry_id}`} title={d.entry_title}>
                  {d.entry_title}
                </Link>
                <RuleLine d={d} />
              </td>
              <td>
                <StatusBadge status={d.status} />
                <DownloadStatusInfo d={d} />
              </td>
              {compact ? (
                <td>
                  <code className="path-sm">{d.save_path}</code>
                </td>
              ) : (
                <>
                  <td>
                    <SavePaths d={d} />
                  </td>
                  <td className="nowrap">
                    {d.qbit_state ?? <span className="muted">—</span>}
                    {d.qbit_progress !== null ? <div className="small muted">{percent(d.qbit_progress)}</div> : null}
                  </td>
                  <td className="num">{d.attempts}</td>
                  {renderActions ? <td className="nowrap">{renderActions(d)}</td> : null}
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </TableWrap>
  );
}
