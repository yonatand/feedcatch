import { Link } from 'react-router-dom';
import type { FeedEntry } from '../api/types';
import { formatBytes } from '../lib/format';
import { ParsedBadges } from './ParsedBadges';
import { Badge, StatusBadge } from './StatusBadge';
import { EmptyRow, TableWrap } from './Table';
import { TimeAgo } from './TimeAgo';

export function LinkKinds({ magnet, torrent, nzb }: { magnet: boolean; torrent: boolean; nzb: boolean }) {
  return (
    <span className="badges">
      {magnet ? <Badge tone="green">magnet</Badge> : null}
      {torrent ? <Badge tone="green">torrent</Badge> : null}
      {nzb ? (
        <Badge tone="grey" title="NZB links are never sent to qBittorrent">
          nzb (ignored)
        </Badge>
      ) : null}
      {!magnet && !torrent ? <Badge tone="red">no torrent link</Badge> : null}
    </span>
  );
}

export function EntriesTable({ items, compact, emptyText = 'No releases yet.' }: { items: FeedEntry[]; compact?: boolean; emptyText?: string }) {
  const cols = compact ? 3 : 5;
  return (
    <TableWrap>
      <table className="table">
        <thead>
          <tr>
            <th>Seen</th>
            <th>Title</th>
            <th>Outcome</th>
            {!compact ? <th>Feed</th> : null}
            {!compact ? <th className="num">Size</th> : null}
          </tr>
        </thead>
        <tbody>
          {items.length === 0 ? <EmptyRow colSpan={cols}>{emptyText}</EmptyRow> : null}
          {items.map((e) => (
            <tr key={e.id}>
              <td data-label="Seen">
                <TimeAgo iso={e.first_seen_at} />
              </td>
              <td className="title-cell cell-main">
                <Link to={`/releases/${e.id}`} title={e.title}>
                  {e.title}
                </Link>
                {!compact ? (
                  <div className="row-sub">
                    <ParsedBadges parsed={e.parsed} />
                    <LinkKinds magnet={e.magnet_url !== null} torrent={e.torrent_url !== null} nzb={e.has_nzb} />
                  </div>
                ) : null}
              </td>
              <td data-label="Outcome" className="cell-grow">
                <StatusBadge status={e.outcome} />
                {e.outcome_summary ? (
                  <div className="small muted" title={e.outcome_summary}>
                    {e.outcome_summary}
                  </div>
                ) : null}
              </td>
              {!compact ? (
                <td className="nowrap" data-label="Feed">
                  {e.feed_name}
                </td>
              ) : null}
              {!compact ? (
                <td className="num nowrap" data-label="Size">
                  {formatBytes(e.size_bytes)}
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
    </TableWrap>
  );
}
