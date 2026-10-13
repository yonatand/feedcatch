type Props = {
  total: number;
  limit: number;
  offset: number;
  onChange: (offset: number) => void;
  disabled?: boolean;
};

export function Pagination({ total, limit, offset, onChange, disabled }: Props) {
  if (total <= limit && offset === 0) {
    return <div className="pagination muted small">{total} total</div>;
  }
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.max(1, Math.ceil(total / limit));
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + limit, total);
  return (
    <nav className="pagination" aria-label="Pagination">
      <span className="muted small">
        {from}–{to} of {total}
      </span>
      <span className="pagination-buttons">
        <button type="button" className="btn btn-sm" disabled={disabled || offset === 0} onClick={() => onChange(0)}>
          « First
        </button>
        <button
          type="button"
          className="btn btn-sm"
          disabled={disabled || offset === 0}
          onClick={() => onChange(Math.max(0, offset - limit))}
        >
          ‹ Prev
        </button>
        <span className="small">
          Page {page} / {pages}
        </span>
        <button
          type="button"
          className="btn btn-sm"
          disabled={disabled || offset + limit >= total}
          onClick={() => onChange(offset + limit)}
        >
          Next ›
        </button>
      </span>
    </nav>
  );
}
