/**
 * Small helpers for consistent tables, empty states and page headers.
 *
 * Mobile (<= 900px): every `.table` is rendered as a card list by styles.css. Cells carry
 * `data-label="Column"` (shown above the value via `::before`); `cell-main` marks the primary
 * text (top of the card, no label), `cell-wide` a full-width value, `cell-actions` the action buttons
 * (bottom of the card, full/half-width buttons).
 */

export function TableWrap({ children }: { children: React.ReactNode }) {
  return <div className="table-wrap">{children}</div>;
}

export function EmptyRow({ colSpan, children }: { colSpan: number; children: React.ReactNode }) {
  return (
    <tr className="empty-row">
      <td colSpan={colSpan} className="cell-main">
        <div className="empty-cell">{children}</div>
      </td>
    </tr>
  );
}

export function EmptyState({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="empty-state">
      <div className="empty-title">{title}</div>
      {children ? <div className="muted">{children}</div> : null}
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
  actionsInBar = false,
}: {
  title: string;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
  /** The page renders the same actions in a MobileActionBar: hide them here on mobile. */
  actionsInBar?: boolean;
}) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        {subtitle ? <p className="muted">{subtitle}</p> : null}
      </div>
      {actions ? <div className={`page-actions${actionsInBar ? ' d-only' : ''}`}>{actions}</div> : null}
    </header>
  );
}

export function Card({
  title,
  actions,
  children,
  className,
}: {
  title?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`card${className ? ` ${className}` : ''}`}>
      {title || actions ? (
        <div className="card-header">
          {title ? <h2>{title}</h2> : <span />}
          {actions ? <div className="card-actions">{actions}</div> : null}
        </div>
      ) : null}
      {children}
    </section>
  );
}
