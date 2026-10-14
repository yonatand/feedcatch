import type { ParsedRelease } from '../api/types';
import { pad2 } from '../lib/format';
import { Badge } from './StatusBadge';

/** Compact badges summarising parsed release metadata. Parsing is fallible; shown as hints only. */
export function ParsedBadges({ parsed }: { parsed: ParsedRelease }) {
  const ep =
    parsed.episode === null
      ? null
      : parsed.episode_end !== null && parsed.episode_end !== parsed.episode
        ? `${pad2(parsed.episode)}-${pad2(parsed.episode_end)}`
        : pad2(parsed.episode);
  const alts = parsed.alt_titles ?? [];
  return (
    <span className="badges">
      {parsed.group ? <Badge tone="blue">[{parsed.group}]</Badge> : null}
      {parsed.season !== null ? <Badge>S{pad2(parsed.season)}</Badge> : null}
      {ep !== null ? (
        <Badge
          tone={parsed.absolute ? 'orange' : 'grey'}
          title={parsed.absolute ? 'Absolute number (no explicit season); needs a season mapping' : undefined}
        >
          {parsed.absolute ? `abs ${ep}` : `E${ep}`}
        </Badge>
      ) : null}
      {parsed.version !== null ? <Badge>v{parsed.version}</Badge> : null}
      {parsed.resolution ? <Badge>{parsed.resolution}</Badge> : null}
      {parsed.source ? <Badge>{parsed.source}</Badge> : null}
      {parsed.codec ? <Badge>{parsed.codec}</Badge> : null}
      {parsed.audio ? <Badge>{parsed.audio}</Badge> : null}
      {parsed.subs.length > 0 ? <Badge>subs: {parsed.subs.join(', ')}</Badge> : null}
      {parsed.is_batch ? <Badge tone="purple">batch</Badge> : null}
      {alts.length > 0 ? (
        <span className="small muted alt-titles" title={`Also known as: ${alts.join(' / ')}`}>
          aka {alts.join(' / ')}
        </span>
      ) : null}
    </span>
  );
}

export function ParsedTable({ parsed }: { parsed: ParsedRelease }) {
  const rows: [string, React.ReactNode][] = [
    ['Title', parsed.title || '—'],
    ...((parsed.alt_titles ?? []).length > 0 ? ([['Also known as', (parsed.alt_titles ?? []).join(' / ')]] as [string, React.ReactNode][]) : []),
    ['Group', parsed.group ?? '—'],
    ['Season', parsed.season ?? '—'],
    [
      'Episode',
      parsed.episode === null
        ? '—'
        : `${parsed.episode}${parsed.episode_end !== null && parsed.episode_end !== parsed.episode ? `–${parsed.episode_end}` : ''}${parsed.absolute ? ' (absolute)' : ''}`,
    ],
    ['Version', parsed.version ?? '—'],
    ['Resolution', parsed.resolution ?? '—'],
    ['Source', parsed.source ?? '—'],
    ['Codec', parsed.codec ?? '—'],
    ['Audio', parsed.audio ?? '—'],
    ['Subs', parsed.subs.length ? parsed.subs.join(', ') : '—'],
    ['Batch', parsed.is_batch ? 'yes' : 'no'],
  ];
  return (
    <dl className="kv">
      {rows.map(([k, v]) => (
        <div key={k} className="kv-row">
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}
