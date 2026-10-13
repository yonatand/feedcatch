import { Link } from 'react-router-dom';
import { useDeleteSeries, useSeriesList, useUpdateSeries } from '../api/hooks';
import { ConfirmInline } from '../components/ConfirmInline';
import { Cover } from '../components/Cover';
import { ErrorBanner } from '../components/ErrorBanner';
import { LoadingBlock } from '../components/Spinner';
import { Badge, StatusBadge } from '../components/StatusBadge';
import { EmptyRow, PageHeader, TableWrap } from '../components/Table';
import { seriesToIn, sortSeasons } from '../lib/series';

export default function SeriesList() {
  const list = useSeriesList();
  const update = useUpdateSeries();
  const del = useDeleteSeries();
  const items = list.data?.items ?? [];

  return (
    <>
      <PageHeader
        title="Series"
        subtitle="Tracked series and their seasons. Nothing is grabbed automatically for a series until it is monitored."
        actions={
          <Link to="/series/new" className="btn btn-primary">
            New series
          </Link>
        }
      />
      <ErrorBanner error={list.error} title="Could not load series" onRetry={() => void list.refetch()} />
      <ErrorBanner error={update.error ?? del.error} onDismiss={() => { update.reset(); del.reset(); }} />
      {list.isLoading ? (
        <LoadingBlock />
      ) : (
        <TableWrap>
          <table className="table">
            <thead>
              <tr>
                <th className="cover-col">
                  <span className="sr-only">Cover</span>
                </th>
                <th>Name</th>
                <th>Monitored</th>
                <th>Seasons</th>
                <th className="num">Rules</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 ? (
                <EmptyRow colSpan={6}>
                  No series yet. <Link to="/series/new">Create one with the wizard</Link>.
                </EmptyRow>
              ) : null}
              {items.map((s) => (
                <tr key={s.id}>
                  <td className="cover-col">
                    <Cover url={s.cover_url} alt={s.name} size="sm" />
                  </td>
                  <td className="title-cell">
                    <Link to={`/series/${s.id}`}>
                      <strong>{s.name}</strong>
                    </Link>
                    {s.aliases.length > 0 ? <div className="small muted">aliases: {s.aliases.join(', ')}</div> : null}
                  </td>
                  <td>
                    <StatusBadge status={s.monitored ? 'monitored' : 'unmonitored'} />
                  </td>
                  <td>
                    {s.seasons.length === 0 ? (
                      <span className="muted small">none — add a season to enable matching</span>
                    ) : (
                      <span className="badges">
                        {sortSeasons(s.seasons).map((se) => (
                          <Badge key={se.id} tone={se.monitored ? 'green' : 'grey'} title={se.computed_save_path}>
                            S{String(se.season_number).padStart(2, '0')}
                          </Badge>
                        ))}
                      </span>
                    )}
                  </td>
                  <td className="num">{s.rule_count}</td>
                  <td>
                    <div className="actions">
                      <Link to={`/series/${s.id}`} className="btn btn-sm">
                        Open
                      </Link>
                      <button
                        type="button"
                        className="btn btn-sm"
                        disabled={update.isPending}
                        onClick={() => update.mutate({ id: s.id, body: { ...seriesToIn(s), monitored: !s.monitored } })}
                      >
                        {s.monitored ? 'Unmonitor' : 'Monitor'}
                      </button>
                      <ConfirmInline
                        label="Delete"
                        confirmLabel="Delete series"
                        message="Removes its seasons and rules. Torrents already in qBittorrent are not touched."
                        pending={del.isPending && del.variables === s.id}
                        onConfirm={() => del.mutate(s.id)}
                      />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      )}
    </>
  );
}
