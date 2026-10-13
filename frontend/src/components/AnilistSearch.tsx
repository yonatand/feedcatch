import { useEffect, useId, useState } from 'react';
import { ApiError } from '../api/client';
import { useAnilistSearch } from '../api/hooks';
import type { AnilistMedia } from '../api/types';
import { anilistStatus, anilistSubtitle, anilistTitle, metaLine } from '../lib/anilist';
import { Cover } from './Cover';
import { ErrorBanner } from './ErrorBanner';
import { Spinner } from './Spinner';
import { Badge } from './StatusBadge';

type Props = {
  onPick: (m: AnilistMedia) => void;
  /** id currently being applied (shows a pending state on that row's button) */
  pendingId?: number | null;
  selectedId?: number | null;
  pickLabel?: string;
  label?: string;
  initialQuery?: string;
  autoFocus?: boolean;
};

const MIN_CHARS = 2;
const DEBOUNCE_MS = 400;

/**
 * AniList search box. Deliberately a <div>, not a <form>: it is embedded inside other forms
 * (wizard step 1), so Enter is swallowed instead of submitting the surrounding form.
 */
export function AnilistSearch({
  onPick,
  pendingId = null,
  selectedId = null,
  pickLabel = 'Use',
  label = 'Search AniList',
  initialQuery = '',
  autoFocus,
}: Props) {
  const inputId = useId();
  const helpId = useId();
  const [text, setText] = useState(initialQuery);
  const [q, setQ] = useState(initialQuery.trim());

  useEffect(() => {
    const t = window.setTimeout(() => setQ(text.trim()), DEBOUNCE_MS);
    return () => window.clearTimeout(t);
  }, [text]);

  const enabled = q.length >= MIN_CHARS;
  const search = useAnilistSearch(q, enabled);
  const items = enabled ? (search.data?.items ?? []) : [];
  const typing = text.trim() !== q;
  const rateLimited = search.error instanceof ApiError && search.error.status === 429;

  return (
    <div className="anilist-search">
      <label htmlFor={inputId} className="field-label">
        {label}
      </label>
      <input
        id={inputId}
        type="search"
        value={text}
        autoComplete="off"
        autoFocus={autoFocus}
        placeholder="e.g. Black Clover"
        aria-describedby={helpId}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            setQ(text.trim());
          }
        }}
      />
      <div id={helpId} className="field-help">
        Type at least {MIN_CHARS} characters. Cover images are loaded directly from AniList’s CDN.
      </div>

      <div aria-live="polite" className="anilist-status">
        {enabled && (search.isFetching || typing) ? <Spinner label="Searching AniList…" /> : null}
        {!enabled && text.trim().length > 0 ? <span className="small muted">Keep typing…</span> : null}
        {enabled && search.isSuccess && !search.isFetching && !typing && items.length === 0 ? (
          <span className="small muted">No AniList results for “{q}”.</span>
        ) : null}
      </div>
      {enabled && search.error ? (
        <ErrorBanner
          error={search.error}
          title={rateLimited ? 'AniList rate limit' : 'AniList search failed'}
          onRetry={() => void search.refetch()}
        />
      ) : null}

      {items.length > 0 ? (
        <ul className="anilist-results" aria-label="AniList results">
          {items.map((m) => {
            const title = anilistTitle(m);
            const sub = anilistSubtitle(m);
            const st = anilistStatus(m.status);
            const selected = selectedId === m.id;
            return (
              <li key={m.id} className={`anilist-row${selected ? ' selected' : ''}`}>
                <Cover url={m.cover_medium} alt={title} size="xs" />
                <div className="anilist-row-main">
                  <strong className="anilist-row-title">{title}</strong>
                  {sub ? <div className="small muted">{sub}</div> : null}
                  <div className="small anilist-row-meta">
                    <span className="muted">{metaLine(m)}</span> <Badge tone={st.tone}>{st.label}</Badge>
                  </div>
                </div>
                <button
                  type="button"
                  className={`btn btn-sm${selected ? '' : ' btn-primary'}`}
                  disabled={pendingId !== null}
                  aria-label={`${pickLabel} ${title}`}
                  onClick={() => onPick(m)}
                >
                  {pendingId === m.id ? 'Loading…' : selected ? 'Selected' : pickLabel}
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}
