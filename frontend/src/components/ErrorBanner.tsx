import { ApiError, errorMessage } from '../api/client';

type Props = {
  error: unknown;
  title?: string;
  onDismiss?: () => void;
  onRetry?: () => void;
};

export function ErrorBanner({ error, title, onDismiss, onRetry }: Props) {
  if (error === null || error === undefined || error === false) return null;
  const msg = typeof error === 'string' ? error : errorMessage(error);
  const status = error instanceof ApiError && error.status > 0 ? ` (HTTP ${error.status})` : '';
  return (
    <div className="banner banner-error" role="alert">
      <div className="banner-body">
        {title ? <strong>{title}{status}: </strong> : status ? <strong>Error{status}: </strong> : null}
        <span className="pre-wrap">{msg}</span>
      </div>
      <div className="banner-actions">
        {onRetry ? (
          <button type="button" className="btn btn-sm" onClick={onRetry}>
            Retry
          </button>
        ) : null}
        {onDismiss ? (
          <button type="button" className="btn btn-sm btn-ghost" onClick={onDismiss} aria-label="Dismiss">
            ×
          </button>
        ) : null}
      </div>
    </div>
  );
}

export function Notice({
  kind = 'info',
  children,
}: {
  kind?: 'info' | 'warning' | 'success' | 'error';
  children: React.ReactNode;
}) {
  return (
    <div className={`banner banner-${kind}`} role={kind === 'error' || kind === 'warning' ? 'alert' : 'status'}>
      <div className="banner-body">{children}</div>
    </div>
  );
}
