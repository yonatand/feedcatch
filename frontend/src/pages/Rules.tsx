import { Fragment, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useDeleteRule, useRules, useSaveRule, useSeriesList } from '../api/hooks';
import { ConfirmInline } from '../components/ConfirmInline';
import { ErrorBanner, Notice } from '../components/ErrorBanner';
import { RuleForm, ruleToIn } from '../components/RuleForm';
import { LoadingBlock } from '../components/Spinner';
import { Badge, StatusBadge } from '../components/StatusBadge';
import { Card, EmptyRow, PageHeader, TableWrap } from '../components/Table';
import { sortSeasons } from '../lib/series';

export default function Rules() {
  const [params, setParams] = useSearchParams();
  const seriesFilter = params.get('series_id');
  const seriesId = seriesFilter ? Number(seriesFilter) : undefined;
  const series = useSeriesList();
  const rules = useRules(seriesId);
  const del = useDeleteRule();
  const save = useSaveRule();
  const [editing, setEditing] = useState<number | 'new' | null>(null);

  const seriesItems = series.data?.items ?? [];
  const seasonsFor = (sid: number) => sortSeasons(seriesItems.find((s) => s.id === sid)?.seasons ?? []);
  const items = rules.data?.items ?? [];
  const monitoredById = new Map(seriesItems.map((s) => [s.id, s.monitored]));

  return (
    <>
      <PageHeader
        title="Rules"
        subtitle="Matching rules across all series. A rule only auto-grabs when it is enabled and its series (and bound season) is monitored."
        actions={
          editing === null ? (
            <button type="button" className="btn btn-primary" disabled={seriesItems.length === 0} onClick={() => setEditing('new')}>
              Add rule
            </button>
          ) : null
        }
      />
      {series.data && seriesItems.length === 0 ? (
        <Notice kind="info">
          Create a series first: <Link to="/series/new">new series wizard</Link>.
        </Notice>
      ) : null}
      {editing === 'new' && seriesItems.length > 0 ? (
        <Card title="New rule">
          <RuleForm
            initial={null}
            defaultSeriesId={seriesId ?? seriesItems[0].id}
            seriesOptions={seriesItems}
            seasonsFor={seasonsFor}
            onDone={() => setEditing(null)}
          />
        </Card>
      ) : null}
      <div className="toolbar">
        <label htmlFor="rules-series" className="small">
          Series
        </label>
        <select
          id="rules-series"
          value={seriesFilter ?? ''}
          onChange={(e) => {
            const v = e.target.value;
            setParams(v ? { series_id: v } : {});
          }}
        >
          <option value="">All series</option>
          {seriesItems.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </div>
      <ErrorBanner error={rules.error ?? series.error} title="Could not load rules" onRetry={() => void rules.refetch()} />
      <ErrorBanner error={del.error ?? save.error} onDismiss={() => { del.reset(); save.reset(); }} />
      {rules.isLoading ? (
        <LoadingBlock />
      ) : (
        <TableWrap>
          <table className="table">
            <thead>
              <tr>
                <th>Rule</th>
                <th>Series / season</th>
                <th>Filters</th>
                <th className="num">Priority</th>
                <th>State</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 ? <EmptyRow colSpan={6}>No rules{seriesId !== undefined ? ' for this series' : ''}.</EmptyRow> : null}
              {items.map((r) => (
                <Fragment key={r.id}>
                  <tr>
                    <td>
                      <strong>{r.name}</strong>
                    </td>
                    <td className="nowrap">
                      <Link to={`/series/${r.series_id}`}>{r.series_name}</Link>{' '}
                      <span className="muted">{r.season_number !== null ? `S${String(r.season_number).padStart(2, '0')}` : 'any season'}</span>
                      {monitoredById.get(r.series_id) === false ? (
                        <div>
                          <Badge>series unmonitored</Badge>
                        </div>
                      ) : null}
                    </td>
                    <td className="small">
                      <span className="badges">
                        {r.release_group ? <Badge tone="blue">{r.require_group_prefix ? `[${r.release_group}] prefix` : r.release_group}</Badge> : null}
                        {r.resolutions.map((x) => (
                          <Badge key={`r${x}`}>{x}</Badge>
                        ))}
                        {r.sources.map((x) => (
                          <Badge key={`s${x}`}>{x}</Badge>
                        ))}
                        {r.codecs.map((x) => (
                          <Badge key={`c${x}`}>{x}</Badge>
                        ))}
                        {r.include_keywords.map((x) => (
                          <Badge key={`i${x}`} tone="green">
                            +{x}
                          </Badge>
                        ))}
                        {r.exclude_keywords.map((x) => (
                          <Badge key={`e${x}`} tone="red">
                            −{x}
                          </Badge>
                        ))}
                        {r.language_keywords.map((x) => (
                          <Badge key={`l${x}`}>{x}</Badge>
                        ))}
                        {r.regex ? (
                          <Badge tone="purple" title={r.regex}>
                            regex
                          </Badge>
                        ) : null}
                      </span>
                    </td>
                    <td className="num">{r.priority}</td>
                    <td>
                      <StatusBadge status={r.enabled ? 'enabled' : 'disabled'} />
                    </td>
                    <td>
                      <div className="actions">
                        <button type="button" className="btn btn-sm" onClick={() => setEditing(editing === r.id ? null : r.id)}>
                          {editing === r.id ? 'Close' : 'Edit'}
                        </button>
                        <button
                          type="button"
                          className="btn btn-sm"
                          disabled={save.isPending}
                          onClick={() => save.mutate({ id: r.id, body: { ...ruleToIn(r), enabled: !r.enabled } })}
                        >
                          {r.enabled ? 'Disable' : 'Enable'}
                        </button>
                        <ConfirmInline label="Delete" confirmLabel="Delete rule" pending={del.isPending && del.variables === r.id} onConfirm={() => del.mutate(r.id)} />
                      </div>
                    </td>
                  </tr>
                  {editing === r.id ? (
                    <tr className="detail-row">
                      <td colSpan={6}>
                        <RuleForm initial={r} defaultSeriesId={r.series_id} seriesOptions={seriesItems} seasonsFor={seasonsFor} onDone={() => setEditing(null)} />
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              ))}
            </tbody>
          </table>
        </TableWrap>
      )}
    </>
  );
}
