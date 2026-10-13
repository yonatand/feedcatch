import type { FeedEntryPreview } from '../api/types';
import { formatBytes } from '../lib/format';
import { LinkKinds } from './EntriesTable';
import { ParsedBadges } from './ParsedBadges';
import { EmptyRow, TableWrap } from './Table';
import { TimeAgo } from './TimeAgo';

/** Live (unpersisted) feed items with parsed metadata badges. */
export function FeedPreviewList({ items }: { items: FeedEntryPreview[] }) {
  return (
    <TableWrap>
      <table className="table">
        <thead>
          <tr>
            <th>Published</th>
            <th>Title / parsed</th>
            <th className="num">Size</th>
          </tr>
        </thead>
        <tbody>
          {items.length === 0 ? <EmptyRow colSpan={3}>The feed returned no entries.</EmptyRow> : null}
          {items.map((e) => (
            <tr key={e.guid}>
              <td>
                <TimeAgo iso={e.published_at} />
              </td>
              <td className="title-cell">
                <div className="break">{e.title}</div>
                <div className="row-sub">
                  <ParsedBadges parsed={e.parsed} />
                  <LinkKinds magnet={e.magnet_url !== null} torrent={e.torrent_url !== null} nzb={e.has_nzb} />
                </div>
              </td>
              <td className="num nowrap">{formatBytes(e.size_bytes)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableWrap>
  );
}
