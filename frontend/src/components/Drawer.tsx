import { useEffect, useRef } from 'react';

type Props = {
  title: React.ReactNode;
  onClose: () => void;
  children: React.ReactNode;
  wide?: boolean;
  /** Sticky footer with the drawer's primary action. */
  footer?: React.ReactNode;
  /** Only show the footer on mobile (desktop keeps the action inline in the body). */
  footerMobileOnly?: boolean;
};

/**
 * Right-side drawer with backdrop; Escape closes; focus moves into the panel.
 * Mobile (<= 900px): a full-screen sheet with a sticky header (title + 44px close), scrolling body and sticky footer.
 */
export function Drawer({ title, onClose, children, wide, footer, footerMobileOnly = false }: Props) {
  const panel = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const prev = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    panel.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeRef.current();
    };
    document.addEventListener('keydown', onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = overflow;
      prev?.focus();
    };
  }, []);

  return (
    <div className="drawer-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        className={`drawer${wide ? ' drawer-wide' : ''}`}
        role="dialog"
        aria-modal="true"
        tabIndex={-1}
        ref={panel}
      >
        <div className="drawer-header">
          <h2>{title}</h2>
          <button type="button" className="btn btn-ghost drawer-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <div className="drawer-body">{children}</div>
        {footer ? <div className={`drawer-footer${footerMobileOnly ? ' m-only' : ''}`}>{footer}</div> : null}
      </div>
    </div>
  );
}
