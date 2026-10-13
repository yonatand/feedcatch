/** Small helpers for consistent tables, empty states and page headers. */

export function TableWrap({ children }: { children: React.ReactNode }) {
  return <div className="table-wrap">{children}</div>;
}

export function EmptyRow({ colSpan, children }: { colSpan: number; children: React.ReactNode }) {
  return (
    <tr className="empty-row">
      <td colSpan={colSpan}>
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
}: {
  title: string;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        {subtitle ? <p className="muted">{subtitle}</p> : null}
      </div>
      {actions ? <div className="page-actions">{actions}</div> : null}
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
