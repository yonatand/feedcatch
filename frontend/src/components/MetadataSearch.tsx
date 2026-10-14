import { useEffect, useId, useState } from 'react';
import { Link } from 'react-router-dom';
import { ApiError } from '../api/client';
import { useMetadataProviders, useMetadataSearch } from '../api/hooks';
import type { MediaResult, MetadataProviderName } from '../api/types';
import { isProviderName, mediaStatus, mediaSubtitle, mediaTitle, metaLine, providerLabel } from '../lib/metadata';
import { Cover } from './Cover';
import { ErrorBanner } from './ErrorBanner';
import { Spinner } from './Spinner';
import { Badge } from './StatusBadge';

/** Stable key for "this provider entry" (ids are strings per provider). */
export function mediaKey(provider: string | null | undefined, id: string | null | undefined): string | null {
  return provider && id ? `${provider}:${id}` : null;
}

type Props = {
  onPick: (m: MediaResult) => void;
  /** mediaKey of the entry currently being applied (shows a pending state on that row's button) */
  pendingKey?: string | null;
  selectedKey?: string | null;
  pickLabel?: string;
  /** Label above the search input; defaults to "Search <provider label>". */
  label?: string;
  initialQuery?: string;
  autoFocus?: boolean;
  /** Preferred provider (e.g. the one the series is linked to); falls back to the first configured one. */
  defaultProvider?: MetadataProviderName | null;
};

const MIN_CHARS = 2;
const DEBOUNCE_MS = 400;

/**
 * Provider-generic metadata search (AniList, TMDB, ...). Deliberately a <div>, not a <form>: it is
 * embedded inside other forms (wizard step 1), so Enter is swallowed instead of submitting them.
 */
export function MetadataSearch({
  onPick,
  pendingKey = null,
  selectedKey = null,
  pickLabel = 'Use',
  label,
  initialQuery = '',
  autoFocus,
  defaultProvider = null,
}: Props) {
  const inputId = useId();
  const providerId = useId();
  const helpId = useId();
  const providersQ = useMetadataProviders();
  const providers = providersQ.data?.items ?? [];
  const [chosen, setChosen] = useState<MetadataProviderName | null>(null);
  const [text, setText] = useState(initialQuery);
  const [q, setQ] = useState(initialQuery.trim());

  const fallback =
    providers.find((p) => p.name === defaultProvider && p.configured)?.name ?? providers.find((p) => p.configured)?.name ?? null;
  const provider = chosen ?? fallback;
  const current = providers.find((p) => p.name === provider) ?? null;
  const unconfigured = providers.filter((p) => !p.configured);
  const plabel = providerLabel(provider, providers);

  useEffect(() => {
    const t = window.setTimeout(() => setQ(text.trim()), DEBOUNCE_MS);
    return () => window.clearTimeout(t);
  }, [text]);

  const enabled = q.length >= MIN_CHARS && provider !== null;
  const search = useMetadataSearch(provider, q, enabled);
  const items = enabled ? (search.data?.items ?? []) : [];
  const typing = text.trim() !== q;
  const rateLimited = search.error instanceof ApiError && search.error.status === 429;

  return (
    <div className="media-search">
      <div className="media-search-bar">
        <div className="media-search-provider">
          <label htmlFor={providerId} className="field-label">
            Source
          </label>
          <select
            id={providerId}
            value={provider ?? ''}
            disabled={providers.length === 0}
            onChange={(e) => {
              if (isProviderName(e.target.value)) setChosen(e.target.value);
            }}
          >
            {providers.length === 0 ? <option value="">{providersQ.isLoading ? 'Loading…' : 'No providers'}</option> : null}
            {providers.map((p) => (
              <option key={p.name} value={p.name} disabled={!p.configured}>
                {p.label} ({p.kind === 'anime' ? 'anime' : 'TV'}){p.configured ? '' : ` — needs a ${p.label} API key (Settings)`}
              </option>
            ))}
          </select>
        </div>
        <div className="media-search-query">
          <label htmlFor={inputId} className="field-label">
            {label ?? `Search ${current ? current.label : 'metadata'}`}
          </label>
          <input
            id={inputId}
            type="search"
            value={text}
            autoComplete="off"
            autoFocus={autoFocus}
            disabled={provider === null}
            placeholder={current?.kind === 'tv' ? 'e.g. Severance' : 'e.g. Black Clover'}
            aria-describedby={helpId}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                setQ(text.trim());
              }
            }}
          />
        </div>
      </div>
      <div id={helpId} className="field-help">
        Type at least {MIN_CHARS} characters. Cover images are loaded directly from {plabel}’s CDN.
        {unconfigured.length > 0 ? (
          <>
            {' '}
            {unconfigured.map((p) => p.label).join(', ')} {unconfigured.length === 1 ? 'needs' : 'need'} an API key:{' '}
            <Link to="/settings">Settings</Link>.
          </>
        ) : null}
      </div>
      <ErrorBanner error={providersQ.error} title="Could not load metadata providers" onRetry={() => void providersQ.refetch()} />
      {providersQ.isSuccess && provider === null ? (
        <div className="small warn-text">No metadata provider is configured. Fill in the fields manually, or add an API key in Settings.</div>
      ) : null}

      <div aria-live="polite" className="media-status">
        {enabled && (search.isFetching || typing) ? <Spinner label={`Searching ${plabel}…`} /> : null}
        {q.length < MIN_CHARS && text.trim().length > 0 ? <span className="small muted">Keep typing…</span> : null}
        {enabled && search.isSuccess && !search.isFetching && !typing && items.length === 0 ? (
          <span className="small muted">
            No {plabel} results for “{q}”.
          </span>
        ) : null}
      </div>
      {enabled && search.error ? (
        <ErrorBanner
          error={search.error}
          title={rateLimited ? `${plabel} rate limit` : `${plabel} search failed`}
          onRetry={() => void search.refetch()}
        />
      ) : null}

      {items.length > 0 ? (
        <ul className="media-results" aria-label={`${plabel} results`}>
          {items.map((m) => {
            const key = mediaKey(m.provider, m.id);
            const title = mediaTitle(m);
            const sub = mediaSubtitle(m);
            const st = mediaStatus(m.status);
            const selected = selectedKey !== null && selectedKey === key;
            return (
              <li key={key} className={`media-row${selected ? ' selected' : ''}`}>
                <Cover url={m.cover_url} alt={title} size="xs" />
                <div className="media-row-main">
                  <strong className="media-row-title">{title}</strong>
                  {sub ? <div className="small muted">{sub}</div> : null}
                  <div className="small media-row-meta">
                    <span className="muted">{metaLine(m)}</span> <Badge tone={st.tone}>{st.label}</Badge>
                  </div>
                </div>
                <button
                  type="button"
                  className={`btn btn-sm${selected ? '' : ' btn-primary'}`}
                  disabled={pendingKey !== null}
                  aria-label={`${pickLabel} ${title}`}
                  onClick={() => onPick(m)}
                >
                  {pendingKey === key ? 'Loading…' : selected ? 'Selected' : pickLabel}
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}
