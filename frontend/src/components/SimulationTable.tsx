import { Fragment, useState } from 'react';
import { Link } from 'react-router-dom';
import type { SimulationResult } from '../api/types';
import { ConditionsTable } from './ConditionsTable';
import { ParsedBadges } from './ParsedBadges';
import { StatusBadge } from './StatusBadge';
import { EmptyRow, TableWrap } from './Table';

type Row = SimulationResult & { entry_id?: number };

export function SimulationTable({ items }: { items: Row[] }) {
  const [open, setOpen] = useState<Record<number, boolean>>({});
  const [onlyMatched, setOnlyMatched] = useState(false);
  const matched = items.filter((r) => r.matched).length;
  const rows = items.map((r, i) => ({ r, i })).filter(({ r }) => !onlyMatched || r.matched);
  return (
    <div className="stack">
      <div className="toolbar">
        <span>
          <strong>{matched}</strong> of {items.length} titles would match.
        </span>
        <label className="check-row">
          <input type="checkbox" checked={onlyMatched} onChange={(e) => setOnlyMatched(e.target.checked)} /> Only matches
        </label>
      </div>
      <TableWrap>
        <table className="table">
          <thead>
            <tr>
              <th>Title</th>
              <th>Matched</th>
              <th className="num">Season</th>
              <th className="num">Episode</th>
              <th>Save path</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? <EmptyRow colSpan={6}>{onlyMatched ? 'No matching titles.' : 'No titles tested.'}</EmptyRow> : null}
            {rows.map(({ r, i }) => (
              <Fragment key={i}>
                <tr className={r.matched ? 'row-match' : ''}>
                  <td className="title-cell">
                    {r.entry_id !== undefined ? (
                      <Link to={`/releases/${r.entry_id}`} className="break">
                        {r.title}
                      </Link>
                    ) : (
                      <div className="break">{r.title}</div>
                    )}
                    <div className="row-sub">
                      <ParsedBadges parsed={r.parsed} />
                    </div>
                  </td>
                  <td>
                    <StatusBadge status={r.matched ? 'matched' : 'rejected'} />
                  </td>
                  <td className="num">{r.season_number ?? '—'}</td>
                  <td className="num">{r.episode_number ?? '—'}</td>
                  <td>{r.save_path ? <code className="path-sm">{r.save_path}</code> : <span className="muted">—</span>}</td>
                  <td>
                    <button
                      type="button"
                      className="btn btn-sm btn-ghost"
                      aria-expanded={!!open[i]}
                      onClick={() => setOpen((m) => ({ ...m, [i]: !m[i] }))}
                    >
                      {open[i] ? 'Hide' : 'Why?'}
                    </button>
                  </td>
                </tr>
                {open[i] ? (
                  <tr className="detail-row">
                    <td colSpan={6}>
                      <ConditionsTable conditions={r.conditions} compact />
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            ))}
          </tbody>
        </table>
      </TableWrap>
    </div>
  );
}
